import math
import wave
from array import array

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from voxwell import live_audio
from voxwell.features.dictation import engine
from voxwell.main import app
from voxwell.paths import data_dir

client = TestClient(app, base_url="http://127.0.0.1")


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
    assert "model exploded" not in r.json()["detail"] and r.json()["detail"].endswith("see the Voxwell log.")
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


def test_status_reports_ready_when_faster_whisper_is_installed():
    import importlib.util

    expected = importlib.util.find_spec("faster_whisper") is not None
    assert client.get("/api/dictation/status").json() == {"ready": expected}


# --- live mode (WebSocket) -------------------------------------------------------------------

def speech(ms):
    return array("h", (int(9000 * math.sin(2 * math.pi * 220 * i / 16000)) for i in range(ms * 16))).tobytes()


def silence(ms):
    return bytes(ms * 32)


def _fake_by_length(calls):
    """Answers with the turn's length in tenths of a second, so tests can tell turns apart."""

    def fake(path, language=None):
        with wave.open(str(path), "rb") as w:
            assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
            tenths = round(w.getnframes() / 1600)
        calls.append(language)
        return engine.Transcript(f"{tenths}", language or "en", [])

    return fake


def _send_audio(ws, pcm, frame_ms=100):
    step = frame_ms * 32
    for i in range(0, len(pcm), step):
        ws.send_bytes(pcm[i : i + step])


def _until_done(ws):
    messages = []
    while True:
        m = ws.receive_json()
        messages.append(m)
        if m["type"] == "done" or (m["type"] == "error" and "index" not in m):
            return messages


def _live(**headers):
    return client.websocket_connect("ws://127.0.0.1/api/dictation/live", headers=headers)


def test_live_turn_by_turn(monkeypatch):
    calls = []
    monkeypatch.setattr(engine, "transcribe", _fake_by_length(calls))
    with _live() as ws:
        ws.send_json({"type": "start", "config": {"silence_ms": 500, "pre_roll_ms": 0, "language": "es"}})
        assert ws.receive_json() == {"type": "ready"}
        _send_audio(ws, speech(1000) + silence(600))
        assert ws.receive_json() == {"type": "speaking"}
        assert ws.receive_json() == {"type": "turn_end", "index": 0}
        assert ws.receive_json() == {"type": "turn", "index": 0, "text": "15", "language": "es"}
        ws.send_json({"type": "end"})
        assert ws.receive_json() == {"type": "done"}
    assert calls == ["es"]
    assert list(data_dir("live").iterdir()) == []


def test_live_results_keep_turn_order(monkeypatch):
    monkeypatch.setattr(live_audio, "QUEUE_SIZE", 10)
    monkeypatch.setattr(engine, "transcribe", _fake_by_length([]))
    with _live() as ws:
        ws.send_json({"type": "start", "config": {"silence_ms": 500, "pre_roll_ms": 0}})
        ws.receive_json()
        for ms in (400, 800, 1200):
            _send_audio(ws, speech(ms) + silence(500))
        ws.send_json({"type": "end"})
        messages = _until_done(ws)
    results = [(m["index"], m["text"]) for m in messages if m["type"] == "turn"]
    assert results == [(0, "9"), (1, "13"), (2, "17")]


def test_live_end_flushes_the_last_turn_and_ignores_clicks(monkeypatch):
    monkeypatch.setattr(engine, "transcribe", _fake_by_length([]))
    with _live() as ws:
        ws.send_json({"type": "start", "config": {"pre_roll_ms": 0}})
        ws.receive_json()
        _send_audio(ws, speech(40) + silence(1500))  # a click: not a turn
        _send_audio(ws, speech(700))  # still speaking when the user presses stop
        ws.send_json({"type": "end"})
        messages = _until_done(ws)
    assert [m["type"] for m in messages] == ["speaking", "turn_end", "turn", "done"]
    assert messages[2]["text"] == "7"


def test_live_failed_turn_is_reported_and_the_session_continues(monkeypatch):
    def boom(path, language=None):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(engine, "transcribe", boom)
    with _live() as ws:
        ws.send_json({"type": "start", "config": {}})
        ws.receive_json()
        _send_audio(ws, speech(500))
        ws.send_json({"type": "end"})
        messages = _until_done(ws)
    assert {"type": "error", "index": 0, "message": "This turn could not be processed; see the Voxwell log."} in messages
    assert messages[-1] == {"type": "done"}


@pytest.mark.parametrize("origin", ["https://evil.example", "http://localhost:3000", "null", "file://"])
def test_live_refuses_other_web_pages(origin):
    with pytest.raises(WebSocketDisconnect) as exc:
        with _live(origin=origin):
            pass
    assert exc.value.code == 1008


@pytest.mark.parametrize("origin", ["http://localhost:5173", "app://voxwell"])
def test_live_accepts_the_app(origin):
    with _live(origin=origin) as ws:
        ws.send_json({"type": "start", "config": {}})
        assert ws.receive_json() == {"type": "ready"}


@pytest.mark.parametrize(
    "first, message",
    [
        ({"type": "end"}, "first message"),
        ({"type": "start", "config": {"silence_ms": 1}}, "silence_ms"),
        ({"type": "start", "config": {"language": "../en"}}, "language"),
        ({"type": "start", "config": []}, "config"),
    ],
)
def test_live_bad_start(first, message):
    with _live() as ws:
        ws.send_json(first)
        m = ws.receive_json()
        assert m["type"] == "error" and message in m["message"]
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


@pytest.mark.parametrize("size", [live_audio.MAX_FRAME_BYTES + 2, 3])
def test_live_rejects_oversized_or_partial_frames(size):
    with _live() as ws:
        ws.send_json({"type": "start", "config": {}})
        ws.receive_json()
        ws.send_bytes(bytes(size))
        m = ws.receive_json()
        assert m["type"] == "error" and "16-bit" in m["message"]


def test_live_rejects_non_json_control():
    with _live() as ws:
        ws.send_json({"type": "start", "config": {}})
        ws.receive_json()
        ws.send_text("not json")
        assert ws.receive_json()["type"] == "error"


def test_transcribe_runs_off_the_event_loop_and_caps_the_upload(monkeypatch):
    import asyncio

    from voxwell.features.dictation import router as dictation_router

    on_loop = []

    def fake(path, language=None):
        try:
            asyncio.get_running_loop()
            on_loop.append(True)
        except RuntimeError:
            on_loop.append(False)
        return engine.Transcript("hi", "en", [engine.Segment(0.0, 1.0, "hi")])

    monkeypatch.setattr(engine, "transcribe", fake)
    assert _post().status_code == 200 and on_loop == [False]  # a worker thread: the server keeps answering
    monkeypatch.setattr(dictation_router, "MAX_UPLOAD", 4)
    assert _post(b"12345").status_code == 413
