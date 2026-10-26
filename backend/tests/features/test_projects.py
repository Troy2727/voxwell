import io
import json
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from voxwell import voices
from voxwell.features.dictation import engine as dictation_engine
from voxwell.features.dictation.engine import Segment, Transcript
from voxwell.features.dubbing import ffmpeg, jobs
from voxwell.features.dubbing import translate as translator
from voxwell.features.voice_cloning import engine as cloning_engine
from voxwell.main import app

client = TestClient(app)


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
        out.write_bytes(wav_bytes() if out.suffix == ".wav" else b"video")

    monkeypatch.setattr(ffmpeg, "run_ffmpeg", fake_ffmpeg)
    monkeypatch.setattr(dictation_engine, "transcribe", lambda p, language=None: Transcript("hola", "es", [Segment(0.0, 1.0, "hola")]))
    monkeypatch.setattr(translator, "translate", lambda texts, s, t: texts)
    monkeypatch.setattr(cloning_engine, "synthesize", lambda text, language, reference_audio=None: wav_bytes())
    monkeypatch.setattr(jobs, "start", jobs._work)  # run synchronously


def speak(text="Hello there", voice_id=None):
    r = client.post("/api/voice_cloning/synthesize", json={"text": text, "language": "en", "voice_id": voice_id})
    assert r.status_code == 200
    return r.json()["id"]


def dub(name="Holiday clip.mp4"):
    r = client.post(
        "/api/dubbing/jobs",
        files={"file": (name, b"fakevideo", "video/mp4")},
        data={"target_language": "en", "voice": "original"},
    )
    assert r.status_code == 200
    return r.json()["id"]


def items():
    return client.get("/api/projects/items").json()


def test_empty():
    assert items() == []


def test_lists_speech_and_dubs_newest_first(mocked):
    voice = voices.save_voice("Alice", wav_bytes(), "upload")
    clip_id = speak("Hello there", voice.id)
    job_id = dub()
    found = items()
    assert [(i["kind"], i["id"]) for i in found] == [("dub", job_id), ("speech", clip_id)]
    d, s = found
    assert d["title"] == "Holiday clip" and d["state"] == "done" and d["voice"] == "Original speaker"
    assert client.get(d["video_url"]).content == b"video"
    assert s["title"] == "Hello there" and s["voice"] == "Alice" and s["language"] == "en"
    assert client.get(s["audio_url"]).content[:4] == b"RIFF"


def test_long_text_gets_a_short_title(mocked):
    speak("word " * 40)
    title = items()[0]["title"]
    assert len(title) <= 60 and title.endswith("…")


def test_rename_speech_and_dub(mocked):
    clip_id, job_id = speak(), dub()
    assert client.patch(f"/api/projects/items/speech/{clip_id}", json={"title": " Intro "}).json()["title"] == "Intro"
    assert client.patch(f"/api/projects/items/dub/{job_id}", json={"title": "Final cut"}).json()["title"] == "Final cut"
    assert {i["title"] for i in items()} == {"Intro", "Final cut"}


def test_dub_title_survives_restart(mocked, monkeypatch):
    job_id = dub()
    client.patch(f"/api/projects/items/dub/{job_id}", json={"title": "Kept"})
    monkeypatch.setattr(jobs, "_jobs", {})  # simulate a restart
    assert items()[0]["title"] == "Kept"


def test_jobs_saved_before_titles_still_list(mocked, monkeypatch):
    job_id = dub()
    state_file = jobs.get(job_id).dir / jobs.STATE_FILE
    state = json.loads(state_file.read_text(encoding="utf-8"))
    del state["title"], state["created"]
    state_file.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(jobs, "_jobs", {})
    item = items()[0]
    assert item["title"] == "Dub" and item["created"] > 0


@pytest.mark.parametrize("title", ["", "   ", "x" * 101])
def test_rename_rejects_bad_titles(mocked, title):
    clip_id = speak()
    assert client.patch(f"/api/projects/items/speech/{clip_id}", json={"title": title}).status_code == 422


def test_delete_speech_removes_files(mocked, isolated_data_dir):
    clip_id = speak()
    assert client.delete(f"/api/projects/items/speech/{clip_id}").status_code == 200
    assert items() == []
    assert list((isolated_data_dir / "voice_cloning").iterdir()) == []


def test_delete_dub_removes_folder(mocked):
    job_id = dub()
    folder = jobs.get(job_id).dir
    assert client.delete(f"/api/projects/items/dub/{job_id}").status_code == 200
    assert not folder.exists() and items() == []


def test_running_dub_cannot_be_deleted(mocked, monkeypatch):
    monkeypatch.setattr(jobs, "start", lambda job: None)  # stays queued
    job_id = dub()
    r = client.delete(f"/api/projects/items/dub/{job_id}")
    assert r.status_code == 409 and jobs.get(job_id).dir.exists()


def test_dub_with_deleted_voice_still_lists(mocked):
    voice = voices.save_voice("Alice", wav_bytes(), "upload")
    r = client.post(
        "/api/dubbing/jobs",
        files={"file": ("a.mp4", b"fakevideo", "video/mp4")},
        data={"target_language": "en", "voice": voice.id},
    )
    voices.delete_voice(voice.id)
    assert items()[0]["id"] == r.json()["id"] and items()[0]["voice"] == "Deleted voice"


@pytest.mark.parametrize("kind,item_id", [
    ("speech", "0" * 32), ("dub", "0" * 12), ("speech", "../x"), ("dub", "ABC"), ("other", "0" * 12),
])
def test_unknown_items(kind, item_id):
    assert client.patch(f"/api/projects/items/{kind}/{item_id}", json={"title": "x"}).status_code in (404, 422)
    assert client.delete(f"/api/projects/items/{kind}/{item_id}").status_code in (404, 422)
