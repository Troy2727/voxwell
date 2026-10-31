import io
import json
import threading
import urllib.parse
import wave
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from voxwell.features.music import engine, history, jobs, lyrics, router, runtime
from voxwell.features.tools import direction
from voxwell.main import app

client = TestClient(app, base_url="http://127.0.0.1")


def wav_bytes(seconds: float = 12.0, rate: int = 8000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x10\x00" * int(seconds * rate))
    return buf.getvalue()


@pytest.fixture
def installed(monkeypatch):
    monkeypatch.setattr(runtime, "is_installed", lambda: True)


@pytest.fixture
def fake_engine(monkeypatch, installed):
    """Generation runs synchronously against a fake engine that records what it was asked."""
    calls = []

    def generate(fields, files, on_progress):
        on_progress(0.5, "Generating")
        calls.append({"fields": fields, "files": {k: Path(v).read_bytes() for k, v in files.items()}})
        return wav_bytes(), {"seed": fields.get("seed"), "metas": {"bpm": 96, "keyscale": "A minor"}}

    monkeypatch.setattr(engine, "generate", generate)
    monkeypatch.setattr(jobs, "submit", lambda *args: jobs._run(*args))
    return calls


def form(**overrides):
    data = {"prompt": "dreamy synth-pop", "lyrics": "[Verse]\nHello", "language": "en", "duration": "30"}
    data.update(overrides)
    return data


def test_status_before_install():
    body = client.get("/api/music/status").json()
    assert body["installed"] is False and body["install"]["state"] == "idle" and body["engine"] == "stopped"
    assert body["languages"]["en"] == "English" and "A minor" in body["keys"]


def test_generate_needs_the_engine_installed():
    r = client.post("/api/music/generate", data=form())
    assert r.status_code == 409 and "Install" in r.json()["detail"]


def test_generate_a_song(fake_engine):
    r = client.post("/api/music/generate", data=form(seed="42", bpm="", key=""))
    assert r.status_code == 200
    track_id = r.json()["id"]
    (call,) = fake_engine
    assert call["fields"] == {
        "task_type": "text2music", "prompt": "dreamy synth-pop", "lyrics": "[Verse]\nHello", "vocal_language": "en",
        "audio_duration": 30.0, "bpm": None, "key_scale": None, "inference_steps": 8, "use_random_seed": False, "seed": 42,
    }
    track = client.get(f"/api/music/tracks/{track_id}").json()
    assert track["status"] == "done" and track["progress"] == 1.0 and track["bpm"] == 96 and track["key"] == "A minor"
    audio = client.get(track["url"])
    assert audio.status_code == 200 and audio.content == wav_bytes()
    assert "dreamy%20synth-pop.wav" in audio.headers["content-disposition"]  # named after the track


def test_metadata_the_engine_did_not_detect_is_not_stored(monkeypatch, installed):
    monkeypatch.setattr(engine, "generate", lambda fields, files, on_progress: (wav_bytes(), {"seed": 1, "metas": {"bpm": "N/A", "keyscale": "N/A"}}))
    monkeypatch.setattr(jobs, "submit", lambda *args: jobs._run(*args))
    track_id = client.post("/api/music/generate", data=form()).json()["id"]
    track = client.get(f"/api/music/tracks/{track_id}").json()
    assert track["status"] == "done" and track["bpm"] is None and track["key"] == ""


def test_instrumental_ignores_lyrics(fake_engine):
    r = client.post("/api/music/generate", data=form(instrumental="true", lyrics="ignored"))
    assert r.status_code == 200 and r.json()["lyrics"] == ""
    assert fake_engine[0]["fields"]["lyrics"] == "[Instrumental]"


@pytest.mark.parametrize("overrides, message", [
    ({"prompt": "  "}, "Describe"),
    ({"lyrics": ""}, "lyrics"),
    ({"duration": "5"}, "length"),
    ({"bpm": "500"}, "Tempo"),
    ({"key": "H major"}, "key"),
    ({"steps": "50"}, "steps"),
    ({"language": "xx"}, "language"),
])
def test_generate_rejects_bad_settings(fake_engine, overrides, message):
    r = client.post("/api/music/generate", data=form(**overrides))
    assert r.status_code == 422 and message.lower() in r.json()["detail"].lower() and fake_engine == []


def test_style_reference_is_uploaded_then_removed(fake_engine, isolated_data_dir):
    r = client.post("/api/music/generate", data=form(), files={"file": ("ref.wav", wav_bytes(2), "audio/wav")})
    assert r.status_code == 200 and r.json()["has_reference"] is True
    assert list(fake_engine[0]["files"]) == ["reference_audio"]
    assert not list((isolated_data_dir / "music" / "tracks").glob("*.reference.wav"))


def test_a_failed_generation_is_reported_on_the_track(monkeypatch, installed):
    def fail(fields, files, on_progress):
        raise engine.GenerationError("Music generation failed: out of memory")

    monkeypatch.setattr(engine, "generate", fail)
    monkeypatch.setattr(jobs, "submit", lambda *args: jobs._run(*args))
    track_id = client.post("/api/music/generate", data=form()).json()["id"]
    track = client.get(f"/api/music/tracks/{track_id}").json()
    assert track["status"] == "failed" and "out of memory" in track["error"] and "url" not in track


def test_an_unexpected_generation_crash_is_logged_not_shown(monkeypatch, installed, caplog):
    def crash(fields, files, on_progress):
        raise RuntimeError("secret detail C:/internal/path")

    monkeypatch.setattr(engine, "generate", crash)
    monkeypatch.setattr(jobs, "submit", lambda *args: jobs._run(*args))
    track_id = client.post("/api/music/generate", data=form()).json()["id"]
    track = client.get(f"/api/music/tracks/{track_id}").json()
    assert track["error"] == "Music generation failed; see the Voxwell log."
    assert "secret detail" in caplog.text


def test_a_track_left_unfinished_by_an_earlier_run_shows_as_failed():
    track = history.create(history.Track(id="a" * 32, title="t", prompt="p", lyrics="", instrumental=True, language="en",
                                         duration=30, bpm=None, key="", seed=1, steps=8, created=0, status="generating"))
    (listed,) = client.get("/api/music/tracks").json()
    assert listed["id"] == track.id and listed["status"] == "failed" and "closed" in listed["error"]


def test_edit_a_section_makes_a_new_track(fake_engine):
    parent = client.post("/api/music/generate", data=form()).json()["id"]
    r = client.post(f"/api/music/tracks/{parent}/edit", json={"start": 2, "end": 8, "lyrics": "[Chorus]\nNew line"})
    assert r.status_code == 200
    child = r.json()
    assert child["parent_id"] == parent and child["edit_start"] == 2 and child["edit_end"] == 8
    assert child["title"] == "dreamy synth-pop (edited)"
    fields = fake_engine[1]["fields"]
    assert fields["task_type"] == "repaint" and fields["repainting_start"] == 2 and fields["repainting_end"] == 8
    assert fields["lyrics"] == "[Chorus]\nNew line" and fields["prompt"] == "dreamy synth-pop"
    assert fake_engine[1]["files"]["src_audio"] == wav_bytes()
    assert client.get(f"/api/music/tracks/{child['id']}").json()["status"] == "done"


def test_edit_rejects_a_bad_section(fake_engine):
    parent = client.post("/api/music/generate", data=form()).json()["id"]
    assert client.post(f"/api/music/tracks/{parent}/edit", json={"start": 4, "end": 5}).status_code == 422  # too short
    assert client.post(f"/api/music/tracks/{parent}/edit", json={"start": 4, "end": 60}).status_code == 422  # past the end
    assert client.post(f"/api/music/tracks/{'b' * 32}/edit", json={"start": 1, "end": 5}).status_code == 404


def test_split_into_vocals_and_instrumental(fake_engine, monkeypatch):
    def isolate(source, voice_out, background_out):
        voice_out.write_bytes(b"vocals")
        background_out.write_bytes(b"backing")

    monkeypatch.setattr(router.isolation, "isolate", isolate)
    track_id = client.post("/api/music/generate", data=form()).json()["id"]
    track = client.post(f"/api/music/tracks/{track_id}/stems").json()
    assert track["stems"] is True
    assert client.get(track["vocals_url"]).content == b"vocals"
    assert client.get(track["instrumental_url"]).content == b"backing"
    assert client.get(f"/api/music/audio/{track_id}?part=drums").status_code == 404


def test_rename_and_delete(fake_engine, isolated_data_dir):
    track_id = client.post("/api/music/generate", data=form()).json()["id"]
    assert client.patch(f"/api/music/tracks/{track_id}", json={"title": "  My   song "}).json()["title"] == "My song"
    assert client.delete(f"/api/music/tracks/{track_id}").json() == {"deleted": track_id}
    assert client.get(f"/api/music/tracks/{track_id}").status_code == 404
    assert not list((isolated_data_dir / "music" / "tracks").iterdir())
    assert client.delete(f"/api/music/tracks/{track_id}").status_code == 404
    assert client.get("/api/music/audio/../../secrets").status_code == 404


def test_write_lyrics_with_the_local_model(monkeypatch):
    seen = []

    def complete(system, user, max_new_tokens):
        seen.append(user)
        return "Sure! Here you go:\n```\n[Verse 1]\nCity lights\n\n\n\n[Chorus]\nWe shine\n```"

    monkeypatch.setattr(direction, "complete", complete)
    r = client.post("/api/music/lyrics", json={"description": "a city pop song", "language": "es"})
    assert r.json() == {"lyrics": "[Verse 1]\nCity lights\n\n[Chorus]\nWe shine"}
    assert "Spanish" in seen[0] and "a city pop song" in seen[0]


def test_lyrics_without_sections_are_refused():
    with pytest.raises(lyrics.LyricsError):
        lyrics.clean("I am just a chatty reply.")


def test_install_starts_once(monkeypatch):
    started = []
    monkeypatch.setattr(runtime, "start_install", lambda: not started.append(1) and len(started) == 1)
    assert client.post("/api/music/install").json() == {"started": True, "installed": False}
    assert client.post("/api/music/install").status_code == 409


def test_source_archive_is_extracted_without_its_top_folder(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ACE-Step-1.5-abc/pyproject.toml", "x")
        zf.writestr("ACE-Step-1.5-abc/acestep/api_server.py", "y")
    with zipfile.ZipFile(buf) as zf:
        runtime._extract_without_top_folder(zf, tmp_path / "src")
    assert (tmp_path / "src" / "pyproject.toml").read_text() == "x"
    assert (tmp_path / "src" / "acestep" / "api_server.py").read_text() == "y"


def test_source_archive_with_an_escaping_path_is_refused(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("top/../../evil.txt", "x")
    with zipfile.ZipFile(buf) as zf, pytest.raises(runtime.EngineError):
        runtime._extract_without_top_folder(zf, tmp_path / "src")
    assert not (tmp_path / "evil.txt").exists()


class FakeAceStep(BaseHTTPRequestHandler):
    """ACE-Step's documented API: release a task, report progress once, then the finished file."""

    KEY = "secret-key"
    released: list = []
    polls = 0

    def log_message(self, *args):
        pass

    def _send(self, body, content_type="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self):
        if self.headers.get("Authorization") != f"Bearer {self.KEY}":
            self.send_response(401)
            self.end_headers()
            return False
        return True

    def do_POST(self):
        if not self._authorized():
            return
        body = self.rfile.read(int(self.headers["Content-Length"]))
        if self.path == "/release_task":
            FakeAceStep.released.append((self.headers["Content-Type"], body))
            self._send({"data": {"task_id": "t1"}, "code": 200, "error": None})
        elif self.path == "/query_result":
            FakeAceStep.polls += 1
            if FakeAceStep.polls == 1:
                item = {"task_id": "t1", "status": 0, "progress": 0.4, "stage": "diffusion"}
            else:
                result = [{"file": "/v1/audio?path=%2Ftmp%2Fsong.wav", "seed_value": "777", "metas": {"bpm": 120}}]
                item = {"task_id": "t1", "status": 1, "result": json.dumps(result)}
            self._send({"data": [item], "code": 200, "error": None})

    def do_GET(self):
        if self._authorized() and self.path.startswith("/v1/audio"):
            path = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)["path"][0]
            self._send(f"audio:{path}".encode(), "audio/wav")


def test_engine_speaks_ace_steps_api(monkeypatch, tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeAceStep)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    FakeAceStep.released, FakeAceStep.polls = [], 0
    monkeypatch.setattr(runtime, "ensure_running", lambda: (f"http://127.0.0.1:{server.server_port}", FakeAceStep.KEY))
    monkeypatch.setattr(engine, "POLL_SECONDS", 0)
    reference = tmp_path / "ref.wav"
    reference.write_bytes(b"REFERENCE-BYTES")
    progress = []
    try:
        wav, info = engine.generate({"prompt": "lo-fi", "seed": 5, "bpm": None}, {"reference_audio": reference},
                                    lambda f, s: progress.append((f, s)))
    finally:
        server.shutdown()
    assert wav == b"audio:/tmp/song.wav" and info == {"metas": {"bpm": 120}}
    assert (0.4, "Diffusion") in progress
    (content_type, body), = FakeAceStep.released
    assert content_type.startswith("multipart/form-data")
    assert b'name="prompt"\r\n\r\nlo-fi' in body and b'name="audio_format"\r\n\r\nwav' in body
    assert b'name="thinking"\r\n\r\nfalse' in body and b'name="bpm"' not in body  # None is left out
    assert b'name="reference_audio"; filename=' in body and b"REFERENCE-BYTES" in body


def test_an_unreadable_track_record_does_not_hide_the_others(fake_engine, isolated_data_dir):
    track_id = client.post("/api/music/generate", data=form()).json()["id"]
    (isolated_data_dir / "music" / "tracks" / f"{'c' * 32}.json").write_text('{"id": "cc', encoding="utf-8")  # cut short
    assert [t["id"] for t in client.get("/api/music/tracks").json()] == [track_id]


def test_a_track_deleted_while_generating_leaves_no_audio(monkeypatch, installed, isolated_data_dir):
    def generate(fields, files, on_progress):
        client.delete(f"/api/music/tracks/{track_ids[0]}")  # the user deletes it meanwhile
        return wav_bytes(), {"metas": {}}

    track_ids = []
    monkeypatch.setattr(engine, "generate", generate)
    monkeypatch.setattr(jobs, "submit", lambda track_id, *rest: track_ids.append(track_id) or jobs._run(track_id, *rest))
    client.post("/api/music/generate", data=form())
    assert not list((isolated_data_dir / "music" / "tracks").iterdir())


def test_a_claimed_track_is_not_settled_as_orphaned():
    jobs.claim("d" * 32)
    try:
        history.create(history.Track(id="d" * 32, title="t", prompt="p", lyrics="", instrumental=True, language="en",
                                     duration=30, bpm=None, key="", seed=1, steps=8, created=0))
        assert client.get(f"/api/music/tracks/{'d' * 32}").json()["status"] == "queued"
    finally:
        jobs._active.discard("d" * 32)


def test_a_broken_source_download_leaves_no_half_installed_folder(monkeypatch):
    monkeypatch.setattr(runtime.urllib.request, "urlopen", lambda url, timeout: io.BytesIO(b"not a zip"))
    with pytest.raises(runtime.EngineError):
        runtime._download_source()
    assert not runtime.source_dir().exists()


class FakeInstallClient:
    def __init__(self, states):
        self.states, self.posted = list(states), []

    def get_json(self, path):
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return {"installed": state == "installed", "install": {"state": "idle" if state == "installed" else state, "percent": 0, "step": "", "error": "boom"}}

    def post_json(self, path, body):
        self.posted.append(path)


def test_cli_install_joins_a_running_install(monkeypatch):
    from voxwell import cli

    monkeypatch.setattr(cli, "POLL_SECONDS", 0)
    running = FakeInstallClient(["installing", "installing", "installed"])
    cli._install_music(running, quiet=True)
    assert running.posted == []  # no second install was started
    fresh = FakeInstallClient(["idle", "installing", "installed"])
    cli._install_music(fresh, quiet=True)
    assert fresh.posted == ["/api/music/install"]


def test_cli_install_stops_when_voxwell_restarts_mid_install(monkeypatch):
    from voxwell import cli

    monkeypatch.setattr(cli, "POLL_SECONDS", 0)
    with pytest.raises(cli.CliError, match="stopped"):
        cli._install_music(FakeInstallClient(["installing", "idle"]), quiet=True)


def test_a_record_save_survives_a_brief_sharing_violation(monkeypatch):
    from voxwell import paths

    calls, real = [], paths._replace

    def flaky(src, dst):
        calls.append(dst)
        if len(calls) <= 2:
            exc = PermissionError(13, "The process cannot access the file")
            exc.winerror = 32
            raise exc
        real(src, dst)

    monkeypatch.setattr(paths, "_replace", flaky)
    monkeypatch.setattr(paths, "_sleep", lambda s: None)
    track = history.create(history.Track(id="e" * 32, title="t", prompt="p", lyrics="", instrumental=True, language="en",
                                         duration=30, bpm=None, key="", seed=1, steps=8, created=0))
    assert len(calls) == 3 and history.get(track.id).title == "t"
