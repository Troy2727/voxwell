import pytest
from fastapi.testclient import TestClient

from voxwell.features.dictation import engine
from voxwell.main import app
from voxwell.paths import data_dir

client = TestClient(app)


def _fake(calls):
    def fake(path, language=None):
        calls.append((path, language, path.read_bytes()))
        return engine.Transcript("hello world", language or "en", [engine.Segment(0.0, 1.0, "hello world")])

    return fake


def _post(data=b"RIFFfake", language=None):
    form = {"language": language} if language else None
    return client.post("/api/dictation/transcribe", files={"file": ("../evil.webm", data, "audio/webm")}, data=form)


def test_happy_path(monkeypatch):
    calls = []
    monkeypatch.setattr(engine, "transcribe", _fake(calls))
    r = _post()
    assert r.status_code == 200
    assert r.json() == {
        "text": "hello world",
        "language": "en",
        "segments": [{"start": 0.0, "end": 1.0, "text": "hello world"}],
    }
    assert calls[0][1] is None
    assert "evil" not in calls[0][0].name


def test_language_passthrough(monkeypatch):
    calls = []
    monkeypatch.setattr(engine, "transcribe", _fake(calls))
    r = _post(language="es")
    assert r.json()["language"] == "es"
    assert calls[0][1] == "es"


def test_empty_file(monkeypatch):
    monkeypatch.setattr(engine, "transcribe", _fake([]))
    assert _post(data=b"").status_code == 422


def test_undecodable_audio(monkeypatch):
    def boom(path, language=None):
        raise engine.AudioError("Could not decode the audio.")

    monkeypatch.setattr(engine, "transcribe", boom)
    assert _post().status_code == 422


def test_engine_error_and_cleanup(monkeypatch):
    def boom(path, language=None):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(engine, "transcribe", boom)
    r = _post()
    assert r.status_code == 500
    assert "model exploded" in r.json()["detail"]
    assert list(data_dir("dictation").iterdir()) == []


def test_temp_file_cleanup_on_success(monkeypatch):
    monkeypatch.setattr(engine, "transcribe", _fake([]))
    _post()
    assert list(data_dir("dictation").iterdir()) == []


def test_engine_transcribe_with_fake_model(monkeypatch, tmp_path):
    class Seg:
        start, end, text = 0.0, 1.5, " hi there "

    class Info:
        language = "en"

    class Model:
        def transcribe(self, path, language=None):
            return iter([Seg()]), Info()

    monkeypatch.setattr(engine, "_load_model", lambda: Model())
    t = engine.transcribe(tmp_path / "a.wav")
    assert t.text == "hi there" and t.language == "en" and t.segments[0].end == 1.5
