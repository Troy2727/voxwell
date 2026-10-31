import pytest
from fastapi.testclient import TestClient

from voxwell import voices
from voxwell.features.voice_remix import engine
from voxwell.main import app

client = TestClient(app, base_url="http://127.0.0.1")
WAV = b"RIFFremixedwav"


@pytest.fixture
def fake_engine(monkeypatch):
    calls = []

    def remix(source, prompt, strength, script):
        calls.append({"source": source.read_bytes(), "prompt": prompt, "strength": strength, "script": script})
        return WAV

    monkeypatch.setattr(engine, "remix", remix)
    return calls


@pytest.fixture
def anna():
    return voices.save_voice("Anna", b"RIFFanna", "upload")


def test_status():
    body = client.get("/api/voice_remix/status").json()
    assert body["strengths"] == ["low", "medium", "high", "max"] and body["default_script"]


def test_preview_remixes_the_saved_voice(fake_engine, anna):
    r = client.post("/api/voice_remix/preview", json={"voice_id": anna.id, "prompt": " older, deeper ", "strength": "high"})
    assert r.status_code == 200
    assert fake_engine == [{"source": b"RIFFanna", "prompt": "older, deeper", "strength": "high", "script": engine.DEFAULT_SCRIPT}]
    assert client.get(r.json()["url"]).content == WAV


def test_save_adds_a_new_voice_and_keeps_the_original(fake_engine, anna):
    preview = client.post("/api/voice_remix/preview", json={"voice_id": anna.id, "prompt": "whisper", "script": "Hi"}).json()
    r = client.post("/api/voice_remix/save", json={"preview_id": preview["preview_id"], "name": "Anna whisper"})
    assert r.status_code == 200 and r.json()["source"] == "remix"
    assert {v.name for v in voices.list_voices()} == {"Anna", "Anna whisper"}
    assert voices.voice_audio_path(anna.id).read_bytes() == b"RIFFanna"
    assert voices.voice_audio_path(r.json()["id"]).read_bytes() == WAV


@pytest.mark.parametrize("body, status", [
    ({"voice_id": "000000000000", "prompt": "x"}, 404),
    ({"voice_id": "../../etc", "prompt": "x"}, 404),
    ({"prompt": "   "}, 422),
    ({"prompt": "x", "strength": "extreme"}, 422),
    ({"prompt": "x" * 501}, 422),
    ({"prompt": "x", "script": "y" * 501}, 422),
])
def test_preview_rejects_bad_requests(fake_engine, anna, body, status):
    r = client.post("/api/voice_remix/preview", json={"voice_id": anna.id, **body})
    assert r.status_code == status and fake_engine == []


def test_save_needs_a_real_preview_and_a_name(fake_engine, anna):
    assert client.post("/api/voice_remix/save", json={"preview_id": "f" * 32, "name": "X"}).status_code == 404
    preview = client.post("/api/voice_remix/preview", json={"voice_id": anna.id, "prompt": "x"}).json()
    assert client.post("/api/voice_remix/save", json={"preview_id": preview["preview_id"], "name": " "}).status_code == 422


def test_blend_mixes_the_two_renders_frame_by_frame():
    torch = pytest.importorskip("torch")
    original, designed = torch.zeros(1, 80, 326), torch.ones(1, 80, 325)  # renders can differ by a frame
    mixed = engine.blend(original, designed, 0.25)
    assert mixed.shape == (1, 80, 325) and torch.allclose(mixed, torch.full((1, 80, 325), 0.25))
    assert torch.equal(engine.blend(original, designed, 0.0), original[..., :325])


def test_max_strength_returns_the_designed_voice_watermarked_without_converting(monkeypatch, tmp_path):
    import io
    import wave

    import numpy as np

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x00\x10" * 4410)
    marked = []

    class Watermarker:
        def apply_watermark(self, samples, sample_rate):
            marked.append(sample_rate)
            return np.zeros_like(samples)

    class FakeVC:
        watermarker = Watermarker()

        @property
        def s3gen(self):
            pytest.fail("max must not run voice conversion")

    monkeypatch.setattr(engine.design, "design", lambda prompt, script: buf.getvalue())
    monkeypatch.setattr(engine.tools, "_load_vc", lambda: FakeVC())
    out = engine.remix(tmp_path / "unused.wav", "deep voice", "max", "Hello")
    assert marked == [44100]
    with wave.open(io.BytesIO(out)) as w:
        assert w.getframerate() == 44100 and w.getnframes() == 4410
