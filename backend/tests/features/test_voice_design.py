import pytest
from fastapi.testclient import TestClient

from voxwell import voices
from voxwell.features.voice_design import engine
from voxwell.main import app

client = TestClient(app)
WAV = b"RIFFfakewav"


@pytest.fixture
def fake_engine(monkeypatch):
    calls = []

    def design(description, sample_text):
        calls.append((description, sample_text))
        return WAV

    monkeypatch.setattr(engine, "design", design)
    return calls


def test_status():
    assert "ready" in client.get("/api/voice_design/status").json()


def test_preview_and_audio(fake_engine):
    r = client.post("/api/voice_design/preview", json={"description": "warm low voice"})
    assert r.status_code == 200
    body = r.json()
    assert fake_engine[0][0] == "warm low voice" and fake_engine[0][1]
    a = client.get(body["url"])
    assert a.status_code == 200 and a.content == WAV


def test_save(fake_engine):
    pid = client.post("/api/voice_design/preview", json={"description": "x", "sample_text": "hi"}).json()["preview_id"]
    r = client.post("/api/voice_design/save", json={"preview_id": pid, "name": "Narrator"})
    assert r.status_code == 200 and r.json()["source"] == "design"
    saved = voices.list_voices()
    assert [v.name for v in saved] == ["Narrator"]
    assert voices.voice_audio_path(saved[0].id).read_bytes() == WAV


def test_new_preview_deletes_previews_older_than_a_day(fake_engine, isolated_data_dir):
    import os
    import time

    folder = isolated_data_dir / "voice_design"
    folder.mkdir(parents=True, exist_ok=True)
    old, recent = folder / f"{'a' * 32}.wav", folder / f"{'b' * 32}.wav"
    for path, age in ((old, 2 * 86400), (recent, 3600)):
        path.write_bytes(b"RIFF")
        os.utime(path, (time.time() - age, time.time() - age))

    client.post("/api/voice_design/preview", json={"description": "calm voice"})
    assert not old.exists() and recent.exists()


def test_save_missing_preview():
    r = client.post("/api/voice_design/save", json={"preview_id": "a" * 32, "name": "N"})
    assert r.status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"description": "   "},
        {"description": "x" * 501},
        {"description": "ok", "sample_text": "y" * 501},
    ],
)
def test_preview_bad_input(fake_engine, payload):
    assert client.post("/api/voice_design/preview", json=payload).status_code == 422
    assert not fake_engine


def test_engine_error(monkeypatch):
    def boom(*a):
        raise RuntimeError("no gpu")

    monkeypatch.setattr(engine, "design", boom)
    r = client.post("/api/voice_design/preview", json={"description": "x"})
    assert r.status_code == 500 and "no gpu" in r.json()["detail"]


@pytest.mark.parametrize("pid", ["..%2F..%2Fsecret", "not-a-valid-id", "%2e%2e", "a" * 31])
def test_audio_traversal_and_bad_id(pid):
    assert client.get(f"/api/voice_design/audio/{pid}").status_code == 404
