import io
import threading
import time
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from voxwell.features.batch import watch
from voxwell.features.dictation import engine as dictation_engine
from voxwell.features.dictation.engine import Segment, Transcript
from voxwell.features.dubbing import ffmpeg, jobs, pipeline
from voxwell.features.dubbing import translate as translator
from voxwell.features.voice_cloning import engine as cloning_engine
from voxwell.main import app

client = TestClient(app, base_url="http://127.0.0.1")


def wav_bytes(seconds: float = 1.0, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(seconds * rate))
    return buf.getvalue()


@pytest.fixture
def mocked(monkeypatch):
    def fake_ffmpeg(args):
        out = Path(args[-1])
        out.write_bytes(wav_bytes() if out.suffix == ".wav" else b"dubbed video")

    monkeypatch.setattr(ffmpeg, "run_ffmpeg", fake_ffmpeg)
    monkeypatch.setattr(dictation_engine, "transcribe", lambda p, language=None: Transcript("hola", "es", [Segment(0.0, 1.0, "hola")]))
    monkeypatch.setattr(translator, "translate", lambda texts, s, t: texts)
    monkeypatch.setattr(cloning_engine, "synthesize", lambda text, language, reference_audio=None: wav_bytes())
    monkeypatch.setattr(jobs, "start", jobs._work)  # run synchronously


def upload(names, lang="en", voice="original"):
    files = [("files", (n, b"fakevideo", "video/mp4")) for n in names]
    return client.post("/api/batch/jobs", files=files, data={"target_language": lang, "voice": voice})


# --- several uploads -----------------------------------------------------------------------


def test_queues_every_valid_file_and_reports_the_rest(mocked):
    r = upload(["one.mp4", "notes.txt", "two.mkv"])
    assert r.status_code == 200
    body = r.json()
    assert [j["name"] for j in body["jobs"]] == ["one.mp4", "two.mkv"]
    assert body["errors"] == [{"name": "notes.txt", "error": "Unsupported video type '.txt'. Use one of: .avi, .m4v, .mkv, .mov, .mp4, .webm."}]
    for j in body["jobs"]:
        assert client.get(f"/api/dubbing/jobs/{j['id']}").json()["state"] == "done"
    assert sorted(i["title"] for i in client.get("/api/projects/items").json()) == ["one", "two"]


@pytest.mark.parametrize("lang,voice", [("xx", "original"), ("en", "000000000000")])
def test_bad_settings_fail_the_whole_batch(mocked, lang, voice):
    assert upload(["one.mp4"], lang, voice).status_code == 422
    assert client.get("/api/projects/items").json() == []


def test_dubs_run_one_at_a_time(monkeypatch):
    """Concurrent dubs would load the models twice and fight over the GPU."""
    active, peak, lock = 0, 0, threading.Lock()

    def slow_pipeline(job_dir, video, target, voice, progress):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.2)
        with lock:
            active -= 1
        out = job_dir / "dubbed.mp4"
        out.write_bytes(b"v")
        (job_dir / "subtitles.srt").write_text("")
        return {"video": out, "subtitles": job_dir / "subtitles.srt"}

    monkeypatch.setattr(pipeline, "run", slow_pipeline)
    ids = [j["id"] for j in upload(["a.mp4", "b.mp4", "c.mp4"]).json()["jobs"]]
    assert any(client.get(f"/api/dubbing/jobs/{i}").json()["step"] == "Waiting for other dubs" for i in ids)
    deadline = time.time() + 10
    while time.time() < deadline and any(client.get(f"/api/dubbing/jobs/{i}").json()["state"] != "done" for i in ids):
        time.sleep(0.05)
    assert all(client.get(f"/api/dubbing/jobs/{i}").json()["state"] == "done" for i in ids)
    assert peak == 1


# --- watch folder --------------------------------------------------------------------------


@pytest.fixture
def folder(tmp_path):
    path = tmp_path / "inbox"
    path.mkdir()
    return path


def enable(folder, lang="en", voice="original"):
    return client.put("/api/batch/watch", json={"enabled": True, "folder": str(folder), "target_language": lang, "voice": voice})


def files():
    return {f["name"]: f for f in client.get("/api/batch/watch").json()["files"]}


def test_disabled_by_default():
    body = client.get("/api/batch/watch").json()
    assert body["enabled"] is False and body["files"] == []


def test_dubs_new_videos_and_saves_next_to_them(mocked, folder):
    (folder / "old.mp4").write_bytes(b"already here")
    assert enable(folder).json()["skipped"] == 1
    (folder / "new clip.mp4").write_bytes(b"fresh")
    (folder / "readme.txt").write_text("ignored")

    watch.poll_once()  # first sighting: wait for the file to settle
    assert files() == {"new clip.mp4": {"name": "new clip.mp4", "status": "new", "error": None}}
    watch.poll_once()  # unchanged since last poll: dub it (synchronously here)
    watch.poll_once()  # finished: save the outputs
    assert files()["new clip.mp4"]["status"] == "saved"
    assert (folder / "dubbed" / "new clip.en.mp4").read_bytes() == b"dubbed video"
    assert (folder / "dubbed" / "new clip.en.srt").exists()
    assert not (folder / "dubbed" / "old.en.mp4").exists()

    watch.poll_once()  # nothing is dubbed twice
    assert len(client.get("/api/projects/items").json()) == 1


def test_waits_while_a_file_is_still_being_copied(mocked, folder):
    enable(folder)
    video = folder / "big.mp4"
    video.write_bytes(b"part")
    watch.poll_once()
    video.write_bytes(b"part and more")  # still growing
    watch.poll_once()
    assert files()["big.mp4"]["status"] == "new"
    watch.poll_once()
    assert files()["big.mp4"]["status"] in ("dubbing", "saved")


def test_empty_files_are_not_started(mocked, folder):
    enable(folder)
    (folder / "placeholder.mp4").write_bytes(b"")
    for _ in range(3):
        watch.poll_once()
    assert files()["placeholder.mp4"]["status"] == "new"


def test_failed_dub_is_reported(mocked, folder, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("no GPU")

    monkeypatch.setattr(dictation_engine, "transcribe", broken)
    enable(folder)
    (folder / "clip.mp4").write_bytes(b"x")
    for _ in range(3):
        watch.poll_once()
    entry = files()["clip.mp4"]
    assert entry["status"] == "failed" and "no GPU" not in entry["error"] and entry["error"].endswith("failed; see the Voxwell log.")


def test_missing_folder_is_reported(mocked, folder):
    enable(folder)
    folder.rmdir()
    watch.poll_once()
    assert client.get("/api/batch/watch").json()["problem"] == "The watched folder no longer exists."


def test_disabled_watch_does_nothing(mocked, folder):
    enable(folder)
    client.put("/api/batch/watch", json={"enabled": False})
    (folder / "clip.mp4").write_bytes(b"x")
    watch.poll_once()
    watch.poll_once()
    assert files() == {}


@pytest.mark.parametrize("settings", [
    {"enabled": True, "folder": ""},
    {"enabled": True, "folder": "Z:/does/not/exist", "target_language": "en"},
])
def test_rejects_a_missing_folder(settings):
    assert client.put("/api/batch/watch", json=settings).status_code == 422


def test_rejects_bad_language(folder):
    assert enable(folder, lang="xx").status_code == 422


def test_server_start_launches_the_watcher(monkeypatch):
    started = []
    monkeypatch.setattr(watch, "start", lambda: started.append(True))
    from voxwell.features import FEATURES
    import voxwell.features as features

    patched = [f if f.id != "batch" else features.Feature("batch", f.router, watch.start) for f in FEATURES]
    monkeypatch.setattr("voxwell.main.FEATURES", patched)
    with TestClient(app, base_url="http://127.0.0.1"):
        pass
    assert started == [True]


@pytest.mark.parametrize("folder", [r"\\server\share\inbox", "//server/share/inbox", r"\\server", r"\\?\UNC\server\share"])
def test_watch_refuses_network_folders(mocked, folder):
    r = client.put("/api/batch/watch", json={"enabled": True, "folder": folder, "target_language": "en", "voice": "original"})
    assert r.status_code == 422 and "network" in r.json()["detail"]


def test_a_saved_network_folder_is_never_opened(mocked, folder, monkeypatch):
    """A config saved before network folders were refused: the watcher reports it, untouched."""
    enable(folder)
    cfg = watch.load()
    cfg["folder"] = r"\\server\share\inbox"
    watch._save(cfg)
    opened = []
    monkeypatch.setattr(watch, "_videos", lambda path: opened.append(path) or [])
    watch.poll_once()
    assert opened == [] and "another computer" in client.get("/api/batch/watch").json()["problem"]
