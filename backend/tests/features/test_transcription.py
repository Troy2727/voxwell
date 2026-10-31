from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from voxwell.features.dictation import engine
from voxwell.features.dictation.engine import AudioError, Segment, Transcript
from voxwell.features.transcription import jobs
from voxwell.main import app

client = TestClient(app, base_url="http://127.0.0.1")

SEGMENTS = [Segment(0.0, 1.5, "Hello there."), Segment(2.0, 3.25, "Welcome to Voxwell.")]


@pytest.fixture
def fake(monkeypatch):
    calls = []

    def transcribe(audio_path, language=None, on_progress=None):
        calls.append((audio_path.read_bytes(), language))
        if on_progress:
            on_progress(0.5)
        return Transcript("Hello there. Welcome to Voxwell.", language or "en", SEGMENTS)

    monkeypatch.setattr(engine, "transcribe", transcribe)
    monkeypatch.setattr(jobs, "start", jobs._work)  # run synchronously
    return calls


def post(name="Interview.mp3", data=b"fake audio", language=""):
    return client.post("/api/transcription/jobs", files={"file": (name, data, "audio/mpeg")}, data={"language": language})


def done_job(**kw):
    r = post(**kw)
    assert r.status_code == 200
    return client.get(f"/api/transcription/jobs/{r.json()['id']}").json()


def test_status():
    assert isinstance(client.get("/api/transcription/status").json()["ready"], bool)


def test_happy_path(fake):
    job = done_job()
    assert job["state"] == "done" and job["percent"] == 100 and job["error"] is None
    assert job["title"] == "Interview" and job["detected"] == "en" and job["language"] == ""
    assert job["transcript"]["text"] == "Hello there. Welcome to Voxwell."
    assert job["transcript"]["segments"][1] == {"start": 2.0, "end": 3.25, "text": "Welcome to Voxwell."}
    assert fake == [(b"fake audio", None)]  # auto-detect


def test_the_upload_name_never_picks_the_decoder(fake, monkeypatch):
    """Named .m3u8, an upload would be decoded as a playlist that can point at other local files."""
    seen = []
    monkeypatch.setattr(engine, "transcribe", lambda audio_path, language=None, on_progress=None: seen.append(audio_path.name) or Transcript("", "en", []))
    done_job(name="list.m3u8")
    assert seen == ["input.audio"]


def test_video_files_and_language(fake):
    job = done_job(name="talk.MP4", language=" ES ")
    assert job["state"] == "done" and job["language"] == "es" and fake[0][1] == "es"


def test_upload_is_deleted_and_result_survives_restart(fake, monkeypatch):
    job = done_job()
    folder = jobs.get(job["id"]).dir
    assert sorted(p.name for p in folder.iterdir()) == ["job.json", "transcript.json"]
    monkeypatch.setattr(jobs, "_jobs", {})
    again = client.get(f"/api/transcription/jobs/{job['id']}").json()
    assert again["state"] == "done" and again["transcript"]["text"] == job["transcript"]["text"]


def test_interrupted_job_is_marked_after_restart(fake, monkeypatch):
    monkeypatch.setattr(jobs, "start", lambda job: jobs._save(job))  # never runs
    jid = post().json()["id"]
    monkeypatch.setattr(jobs, "_jobs", {})
    job = client.get(f"/api/transcription/jobs/{jid}").json()
    assert job["state"] == "error" and "closed" in job["error"]
    assert [p.name for p in jobs.get(jid).dir.iterdir()] == ["job.json"]


@pytest.mark.parametrize("fmt,expected", [
    ("txt", "Hello there. Welcome to Voxwell.\n"),
    ("srt", "1\n00:00:00,000 --> 00:00:01,500\nHello there.\n"),
    ("vtt", "WEBVTT\n\n00:00:00.000 --> 00:00:01.500\nHello there.\n\n00:00:02.000 --> 00:00:03.250\nWelcome to Voxwell.\n"),
])
def test_exports(fake, fmt, expected):
    job = done_job()
    r = client.get(f"/api/transcription/jobs/{job['id']}/export/{fmt}")
    assert r.status_code == 200 and r.text.startswith(expected)
    assert f'filename="Interview.{fmt}"' in r.headers["content-disposition"]


def test_export_names_keep_non_ascii_titles(fake):
    """Downloads are named after the file, encoded so any title survives (Starlette's FileResponse style)."""
    job = done_job(name="Entrevista café: día 1.mp3")
    disposition = client.get(f"/api/transcription/jobs/{job['id']}/export/srt").headers["content-disposition"]
    assert disposition == "attachment; filename*=utf-8''Entrevista%20caf%C3%A9%20d%C3%ADa%201.srt"


def test_export_needs_a_finished_job(fake, monkeypatch):
    monkeypatch.setattr(jobs, "start", lambda job: None)
    jid = post().json()["id"]
    assert client.get(f"/api/transcription/jobs/{jid}/export/txt").status_code == 409
    assert client.get(f"/api/transcription/jobs/{jid}/export/pdf").status_code == 422


def test_rejects_bad_input(fake):
    assert post(data=b"").status_code == 422
    assert post(language="english").status_code == 422
    assert post(language="../x").status_code == 422


def test_no_speech_is_an_error(monkeypatch):
    monkeypatch.setattr(engine, "transcribe", lambda p, language=None, on_progress=None: Transcript("", "en", [Segment(0, 1, "")]))
    monkeypatch.setattr(jobs, "start", jobs._work)
    job = done_job()
    assert job["state"] == "error" and "No speech" in job["error"]


@pytest.mark.parametrize("exc,message", [
    (AudioError("Could not decode the audio."), "Could not decode the audio."),
    (RuntimeError("CUDA out of memory"), "Transcription failed: CUDA out of memory"),
])
def test_engine_errors(monkeypatch, exc, message):
    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(engine, "transcribe", boom)
    monkeypatch.setattr(jobs, "start", jobs._work)
    job = done_job()
    assert job["state"] == "error" and job["error"] == message
    assert [p.name for p in jobs.get(job["id"]).dir.iterdir()] == ["job.json"]


def test_list_newest_first(fake):
    first, second = done_job(name="a.wav"), done_job(name="b.wav")
    assert [j["id"] for j in client.get("/api/transcription/jobs").json()] == [second["id"], first["id"]]


@pytest.mark.parametrize("bad", ["000000000000", "ABCDEF123456", "..", "%2e%2e%2fx"])
def test_unknown_ids(bad):
    assert client.get(f"/api/transcription/jobs/{bad}").status_code in (404, 405)
    assert client.get(f"/api/transcription/jobs/{bad}/export/txt").status_code in (404, 405)


def test_projects_list_rename_delete(fake):
    job = done_job()
    item = client.get("/api/projects/items").json()[0]
    assert item["kind"] == "transcript" and item["title"] == "Interview" and item["text"].startswith("Hello")
    assert client.get(item["exports"]["srt"]).status_code == 200
    path = f"/api/projects/items/transcript/{job['id']}"
    assert client.patch(path, json={"title": "Board meeting"}).json()["title"] == "Board meeting"
    assert client.delete(path).status_code == 200
    assert client.get("/api/projects/items").json() == []


def test_running_transcript_cannot_be_deleted(fake, monkeypatch):
    monkeypatch.setattr(jobs, "start", lambda job: None)
    jid = post().json()["id"]
    assert client.delete(f"/api/projects/items/transcript/{jid}").status_code == 409


def test_engine_reports_progress(monkeypatch):
    """The real engine calls on_progress with the fraction of audio done after each segment."""
    segs = [SimpleNamespace(start=0.0, end=5.0, text=" a "), SimpleNamespace(start=5.0, end=10.0, text="b")]
    model = SimpleNamespace(transcribe=lambda path, language=None: (iter(segs), SimpleNamespace(duration=10.0, language="en")))
    monkeypatch.setattr(engine, "_load_model", lambda: model)
    seen = []
    t = engine.transcribe(__import__("pathlib").Path("x.wav"), on_progress=seen.append)
    assert seen == [0.5, 1.0] and t.text == "a b"
