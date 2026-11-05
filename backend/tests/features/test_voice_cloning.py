import io
import wave

import pytest
from fastapi.testclient import TestClient

from voxwell.features.voice_cloning import engine
from voxwell.main import app

client = TestClient(app, base_url="http://127.0.0.1")


def make_wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x01" * 1600)
    return buf.getvalue()


@pytest.fixture
def fake_engine(monkeypatch):
    calls = []

    def fake(text, language, reference_audio=None):
        calls.append((text, language, reference_audio))
        return make_wav()

    monkeypatch.setattr(engine, "synthesize", fake)
    return calls


def upload(name="Alice", data=None):
    return client.post(
        "/api/voice_cloning/voices",
        data={"name": name},
        files={"file": ("a.wav", data if data is not None else make_wav(), "audio/wav")},
    )


def test_status():
    body = client.get("/api/voice_cloning/status").json()
    assert isinstance(body["ready"], bool)


def test_upload_and_listed():
    r = upload()
    assert r.status_code == 200
    voice = r.json()
    assert voice["name"] == "Alice" and voice["source"] == "upload"
    assert voice["id"] in [v["id"] for v in client.get("/api/voices").json()]


@pytest.mark.parametrize("fmt", ["FLAC", "OGG", "MP3"])
def test_upload_converts_other_formats_to_wav(fmt):
    sf = pytest.importorskip("soundfile")
    from voxwell import voices

    buf = io.BytesIO()
    sf.write(buf, [0.1, -0.1] * 4000, 16000, format=fmt)
    r = upload(data=buf.getvalue())
    assert r.status_code == 200
    stored = voices.voice_audio_path(r.json()["id"]).read_bytes()
    assert stored[:4] == b"RIFF" and stored[8:12] == b"WAVE"


def test_upload_keeps_the_level_of_a_float_wav():
    sf = pytest.importorskip("soundfile")
    np = pytest.importorskip("numpy")
    from voxwell import voices

    buf = io.BytesIO()
    sf.write(buf, 0.5 * np.sin(np.linspace(0, 2000, 16000)), 16000, format="WAV", subtype="FLOAT")
    r = upload(data=buf.getvalue())
    assert r.status_code == 200
    stored, _ = sf.read(str(voices.voice_audio_path(r.json()["id"])), dtype="int16")
    assert 16000 < np.abs(stored).max() < 16500  # half of full scale, as sent, not silence


def test_upload_rejects_non_audio_and_blank_name():
    assert upload(data=b"not audio").status_code == 422
    assert upload(name="  ").status_code == 422


def test_synthesize_happy_path(fake_engine):
    voice_id = upload().json()["id"]
    r = client.post("/api/voice_cloning/synthesize", json={"text": "Hello", "language": "en", "voice_id": voice_id})
    assert r.status_code == 200
    body = r.json()
    assert fake_engine[0][2].name == f"{voice_id}.wav"
    audio = client.get(body["url"])
    assert audio.status_code == 200 and audio.content[:4] == b"RIFF"


def test_synthesize_without_voice(fake_engine):
    r = client.post("/api/voice_cloning/synthesize", json={"text": "Hi", "language": "fr"})
    assert r.status_code == 200 and fake_engine[0][2] is None


def test_unknown_voice(fake_engine):
    r = client.post("/api/voice_cloning/synthesize", json={"text": "Hi", "language": "en", "voice_id": "000000000000"})
    assert r.status_code == 404


@pytest.mark.parametrize("text", ["", "   ", "x" * 2001])
def test_bad_text(fake_engine, text):
    r = client.post("/api/voice_cloning/synthesize", json={"text": text, "language": "en"})
    assert r.status_code == 422


def test_unsupported_language_is_rejected_before_synthesis(fake_engine):
    r = client.post("/api/voice_cloning/synthesize", json={"text": "Hi", "language": "vi"})
    assert r.status_code == 422 and "vi" in r.json()["detail"]


def test_engine_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no model")

    monkeypatch.setattr(engine, "synthesize", boom)
    r = client.post("/api/voice_cloning/synthesize", json={"text": "Hi", "language": "en"})
    assert r.status_code == 500 and "no model" not in r.json()["detail"] and r.json()["detail"].endswith("see the Voxwell log.")


@pytest.mark.parametrize("bad", ["..%2F..%2Fsecret", "..", "abc", "%2e%2e%2f%2e%2e%2fx"])
def test_audio_traversal(bad):
    assert client.get(f"/api/voice_cloning/audio/{bad}").status_code in (404, 405)


def test_audio_unknown_id():
    assert client.get("/api/voice_cloning/audio/" + "0" * 32).status_code == 404


class FakeModel:
    """Half a second of a constant level per generate call, at the model's real interface."""

    sr = 24000

    def __init__(self):
        self.texts = []

    def generate(self, text, **kwargs):
        import numpy as np

        self.texts.append(text)
        return np.full(self.sr // 2, 0.5, dtype=np.float32)


@pytest.fixture
def fake_model(monkeypatch):
    model = FakeModel()
    monkeypatch.setattr(engine, "_load_model", lambda: model)
    return model


def wav_seconds(wav: bytes) -> float:
    with wave.open(io.BytesIO(wav)) as w:
        return w.getnframes() / w.getframerate()


def test_text_is_split_at_pause_tags():
    assert engine.split_pauses("Hello there.") == ["Hello there."]
    assert engine.split_pauses("One. [pause 2] Two.") == ["One.", 2.0, "Two."]
    assert engine.split_pauses("[PAUSE 1.5]Go[pause]") == [1.5, "Go", engine.DEFAULT_PAUSE]
    assert engine.split_pauses("Wait [pause 999] up") == ["Wait", engine.MAX_PAUSE, "up"]
    assert engine.split_pauses("Only. [pause] .") == ["Only.", engine.DEFAULT_PAUSE], "lone punctuation isn't spoken"
    assert engine.split_pauses("Keep [laughter] and [pause-ish] as text") == ["Keep [laughter] and [pause-ish] as text"]


def test_a_pause_tag_becomes_silence_and_is_never_spoken(fake_model):
    wav = engine.synthesize("First part. [pause 2] Second part.", "en")
    assert fake_model.texts == ["First part.", "Second part."]
    assert wav_seconds(wav) == pytest.approx(0.5 + 2 + 0.5)
    with wave.open(io.BytesIO(wav)) as w:
        w.setpos(int(w.getframerate() * 1.5))  # the middle of the pause
        assert set(w.readframes(100)) == {0}


def test_text_with_only_pauses_gives_silence_without_generating(fake_model):
    assert wav_seconds(engine.synthesize("[pause 1]", "en")) == pytest.approx(1)
    assert fake_model.texts == []


def test_pronunciation_cannot_break_a_pause_tag(fake_model, monkeypatch):
    monkeypatch.setattr(engine.pronunciation, "apply", lambda text, language: text.replace("pause", "stop"))
    engine.synthesize("A pause here. [pause 1] Done.", "en")
    assert fake_model.texts == ["A stop here.", "Done."]


def test_without_tags_the_text_is_generated_once(fake_model):
    assert wav_seconds(engine.synthesize("Just one line.", "en")) == pytest.approx(0.5)
    assert fake_model.texts == ["Just one line."]
