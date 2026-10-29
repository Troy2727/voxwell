import io
import os
import stat
import sys
import wave

import pytest
from fastapi.testclient import TestClient

from voxwell.features.sound import engine, history, token
from voxwell.main import app

client = TestClient(app)
SECRET = "hf_super_secret_value_123"


def wav_bytes(seconds: float = 0.5) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x10\x00\xf0\xff" * int(seconds * 44100))
    return buf.getvalue()


@pytest.fixture(autouse=True)
def no_env_token(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setattr(engine, "is_installed", lambda: False)


@pytest.fixture
def fake_engine(monkeypatch):
    calls = []

    def generate(prompt, duration, steps, seed, tok):
        calls.append({"prompt": prompt, "duration": duration, "steps": steps, "seed": seed, "token": tok})
        return wav_bytes()

    monkeypatch.setattr(engine, "generate", generate)
    return calls


def test_status_reports_token_presence_only():
    assert client.get("/api/sound/status").json() == {
        "ready": True, "installed": False, "token_set": False,
        "model": engine.MODEL_ID, "model_url": engine.MODEL_URL,
    }
    assert client.put("/api/sound/token", json={"token": f"  {SECRET} "}).json() == {"token_set": True}
    status = client.get("/api/sound/status")
    assert status.json()["token_set"] is True and SECRET not in status.text
    assert client.delete("/api/sound/token").json() == {"token_set": False}


def test_env_token_counts_as_set(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", SECRET)
    assert client.get("/api/sound/status").json()["token_set"] is True


def test_token_file_is_private_and_validated(isolated_data_dir):
    assert client.put("/api/sound/token", json={"token": "two words"}).status_code == 422
    assert client.put("/api/sound/token", json={"token": ""}).status_code == 422
    client.put("/api/sound/token", json={"token": SECRET})
    path = isolated_data_dir / "sound" / ".hf_token"
    assert path.read_text(encoding="utf-8") == SECRET
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert history.list_sounds() == []  # the token file is not a history item


def test_generate_passes_the_token_and_never_returns_it(fake_engine):
    client.put("/api/sound/token", json={"token": SECRET})
    r = client.post("/api/sound/generate", json={"prompt": "  rain on a roof ", "duration": 5, "seed": 42})
    assert r.status_code == 200 and SECRET not in r.text
    item = r.json()
    assert (item["prompt"], item["duration"], item["seed"], item["steps"]) == ("rain on a roof", 5, 42, 100)
    assert fake_engine[0]["token"] == SECRET
    assert SECRET not in client.get("/api/sound/history").text


def test_generate_picks_a_seed_when_none_given(fake_engine):
    item = client.post("/api/sound/generate", json={"prompt": "wind"}).json()
    assert item["seed"] == fake_engine[0]["seed"] and item["duration"] == 10


@pytest.mark.parametrize("body", [
    {"prompt": ""},
    {"prompt": "   "},
    {"prompt": "x" * 501},
    {"prompt": "a", "duration": 0.5},
    {"prompt": "a", "duration": 31},
    {"prompt": "a", "steps": 5},
    {"prompt": "a", "steps": 1000},
    {"prompt": "a", "seed": -1},
    {},
])
def test_request_validation(fake_engine, body):
    assert client.post("/api/sound/generate", json=body).status_code == 422
    assert fake_engine == []


def test_gated_model_gives_a_clear_message(monkeypatch):
    def gated(*args):
        raise engine.AccessError(engine.ACCESS_MESSAGE)

    monkeypatch.setattr(engine, "generate", gated)
    r = client.post("/api/sound/generate", json={"prompt": "wind"})
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert engine.MODEL_URL in detail and "token" in detail and "Accept" in detail
    assert history.list_sounds() == []


def test_engine_turns_hub_gating_errors_into_access_errors(monkeypatch):
    diffusers = pytest.importorskip("diffusers")
    from huggingface_hub.errors import GatedRepoError

    import httpx

    response = httpx.Response(403, request=httpx.Request("GET", engine.MODEL_URL))

    def boom(*a, **k):
        raise GatedRepoError("403 Client Error. Cannot access gated repo", response=response)

    monkeypatch.setattr(diffusers.StableAudioPipeline, "from_pretrained", boom)
    monkeypatch.setattr(engine, "_pipeline", None)
    with pytest.raises(engine.AccessError, match="gated model"):
        engine.generate("wind", 1, 10, 1, SECRET)


def test_other_failures_do_not_leak_details(monkeypatch):
    def broken(*args):
        raise RuntimeError(f"cuda exploded using {SECRET}")

    monkeypatch.setattr(engine, "generate", broken)
    r = client.post("/api/sound/generate", json={"prompt": "wind"})
    assert r.status_code == 500 and SECRET not in r.text


def test_busy_is_409(monkeypatch):
    def busy(*args):
        raise engine.Busy()

    monkeypatch.setattr(engine, "generate", busy)
    assert client.post("/api/sound/generate", json={"prompt": "wind"}).status_code == 409


def test_history_list_audio_and_delete(fake_engine):
    first = client.post("/api/sound/generate", json={"prompt": "one"}).json()
    second = client.post("/api/sound/generate", json={"prompt": "two"}).json()
    assert [s["prompt"] for s in client.get("/api/sound/history").json()] == ["two", "one"]
    audio = client.get(first["url"])
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/wav" and audio.content[:4] == b"RIFF"
    assert client.delete(f"/api/sound/history/{first['id']}").json() == {"deleted": first["id"]}
    assert client.get(first["url"]).status_code == 404
    assert client.delete(f"/api/sound/history/{first['id']}").status_code == 404
    assert [s["id"] for s in client.get("/api/sound/history").json()] == [second["id"]]


@pytest.mark.parametrize("bad", ["..%2F..%2Fsecret", "not-an-id", "A" * 32, "0" * 31, ".hf_token", "%2e%2e"])
def test_audio_ids_are_never_paths(isolated_data_dir, bad):
    (isolated_data_dir / "secret.wav").write_bytes(b"RIFF")
    assert client.get(f"/api/sound/audio/{bad}").status_code == 404
    assert client.delete(f"/api/sound/history/{bad}").status_code in (404, 405)


def test_to_wav_trims_and_is_stereo_16_bit():
    torch = pytest.importorskip("torch")
    data = engine._to_wav(torch.zeros(2, 44100 * 3), 44100, 1.5)
    with wave.open(io.BytesIO(data)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (2, 2, 44100, 66150)


def test_token_module_clear_is_idempotent():
    token.clear_token()
    token.save_token(SECRET)
    token.clear_token()
    assert token.get_token() is None
