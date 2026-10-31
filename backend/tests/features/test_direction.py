import io
import shutil
import wave

import pytest
from fastapi.testclient import TestClient

from voxwell import voices
from voxwell.features.tools import direction
from voxwell.features.tools.direction import DirectionError, Settings, apply_explicit_words, parse_reply
from voxwell.features.tools.router import exaggeration_for
from voxwell.features.voice_cloning import engine as cloning_engine
from voxwell.main import app

client = TestClient(app, base_url="http://127.0.0.1")
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


def wav_bytes(seconds: float = 1.0, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x10\x00\xf0\xff" * int(seconds * rate / 2))
    return buf.getvalue()


def seconds(data: bytes) -> float:
    with wave.open(io.BytesIO(data)) as w:
        return w.getnframes() / w.getframerate()


# --- reading the model's answer ------------------------------------------------------------


@pytest.mark.parametrize("reply,expected", [
    ('{"summary": "angry shout", "energy": "high", "pace": "fast"}', Settings(0.85, "fast", "angry shout")),
    ('Sure! {"summary": "soft", "energy": "LOW", "pace": "slow"} Hope that helps.', Settings(0.2, "slow", "soft")),
    ('{"summary": "x", "energy": "medium", "pace": "sideways"}', Settings(0.5, "normal", "x")),
    ('{"energy": "medium"}', Settings(0.5, "normal", "")),
])
def test_parse_reply(reply, expected):
    assert parse_reply(reply) == expected


@pytest.mark.parametrize("reply", ["", "no json here", '{"energy": "extreme"}', '{"pace": "fast"}', "{broken"])
def test_unreadable_replies(reply):
    with pytest.raises(DirectionError):
        parse_reply(reply)


@pytest.mark.parametrize("note,model,expected", [
    ("read it quickly", Settings(0.5, "normal", ""), ("fast", 0.5)),
    ("slowly and sadly", Settings(0.5, "fast", ""), ("slow", 0.5)),
    ("whisper it", Settings(0.85, "normal", ""), ("normal", direction.QUIET_MAX_INTENSITY)),
    ("start slow, end fast", Settings(0.5, "normal", ""), ("normal", 0.5)),  # both: model decides
    ("breakfast with friends", Settings(0.5, "normal", ""), ("normal", 0.5)),  # whole words only
])
def test_explicit_words_win(note, model, expected):
    s = apply_explicit_words(note, model)
    assert (s.pace, s.intensity) == expected


def test_exaggeration_mapping():
    assert [round(exaggeration_for(i), 2) for i in (0, 0.2, 0.5, 0.85, 1, 7)] == [0.3, 0.38, 0.5, 1.13, 1.4, 1.4]


# --- endpoints -----------------------------------------------------------------------------


def test_interpret(monkeypatch):
    monkeypatch.setattr(direction, "_ask", lambda note: '{"summary": "sad whisper", "energy": "medium", "pace": "normal"}')
    r = client.post("/api/tools/direction/interpret", json={"note": "whisper it, slowly"})
    assert r.json() == {"intensity": 0.3, "pace": "slow", "summary": "sad whisper"}


@pytest.mark.parametrize("note", ["", "   ", "x" * 301])
def test_interpret_rejects(note):
    assert client.post("/api/tools/direction/interpret", json={"note": note}).status_code == 422


def test_interpret_model_errors(monkeypatch):
    monkeypatch.setattr(direction, "_ask", lambda note: "I cannot help with that.")
    assert client.post("/api/tools/direction/interpret", json={"note": "angry"}).status_code == 422

    def boom(note):
        raise RuntimeError("download failed")

    monkeypatch.setattr(direction, "_ask", boom)
    r = client.post("/api/tools/direction/interpret", json={"note": "angry"})
    assert r.status_code == 500 and "download failed" in r.json()["detail"]


@pytest.fixture
def synth(monkeypatch):
    calls = []

    def fake(text, language, reference_audio=None, *, exaggeration=0.5, cfg_weight=0.5):
        calls.append({"text": text, "voice": reference_audio and reference_audio.stem, "exaggeration": exaggeration, "cfg": cfg_weight})
        return wav_bytes(1.0)

    monkeypatch.setattr(cloning_engine, "synthesize", fake)
    return calls


def test_speak_passes_the_settings_to_the_voice_model(synth, monkeypatch):
    monkeypatch.setattr("voxwell.features.tools.router._ffmpeg_ready", lambda: False)
    voice = voices.save_voice("A", wav_bytes(), "upload")
    r = client.post("/api/tools/direction/speak", json={"text": "Hi", "voice_id": voice.id, "intensity": 0.85, "pace": "slow"})
    assert r.status_code == 200 and r.json()["tempo"] == 1.0
    assert synth == [{"text": "Hi", "voice": voice.id, "exaggeration": pytest.approx(1.13), "cfg": 0.3}]
    assert seconds(client.get(r.json()["url"]).content) == pytest.approx(1.0, abs=0.01)


@needs_ffmpeg
@pytest.mark.parametrize("pace,length", [("fast", 1 / 1.15), ("slow", 1 / 0.9), ("normal", 1.0)])
def test_pace_changes_the_length(synth, pace, length):
    r = client.post("/api/tools/direction/speak", json={"text": "Hi", "pace": pace})
    assert seconds(client.get(r.json()["url"]).content) == pytest.approx(length, abs=0.03)


@pytest.mark.parametrize("body", [{"text": ""}, {"text": "Hi", "pace": "warp"}, {"text": "Hi", "language": "xx"}, {"text": "Hi", "voice_id": "000000000000"}])
def test_speak_rejects(synth, body):
    assert client.post("/api/tools/direction/speak", json=body).status_code == 422 and synth == []
