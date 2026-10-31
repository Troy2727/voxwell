import threading
import time

import pytest
from fastapi.testclient import TestClient

from voxwell import voices
from voxwell.features.gallery.presets import PRESETS
from voxwell.features.voice_design import engine
from voxwell.main import app

client = TestClient(app, base_url="http://127.0.0.1")
FIRST = PRESETS[0]


@pytest.fixture
def fake(monkeypatch):
    calls = []

    def design(description, sample_text):
        calls.append((description, sample_text))
        return b"RIFF" + str(len(calls)).encode()

    monkeypatch.setattr(engine, "design", design)
    return calls


def test_presets_are_listed_and_unique():
    found = client.get("/api/gallery/presets").json()
    assert len(found) == len(PRESETS) >= 8
    assert len({p["id"] for p in found}) == len(found)
    assert all(p["ready"] is False and p["audio_url"] is None for p in found)
    assert {p["category"] for p in found} == {"Narration", "Media", "Characters", "Assistants"}


def test_listening_generates_once_and_caches(fake):
    first = client.post(f"/api/gallery/presets/{FIRST.id}/sample").json()
    again = client.post(f"/api/gallery/presets/{FIRST.id}/sample").json()
    assert first["ready"] and again["audio_url"] == first["audio_url"]
    assert fake == [(FIRST.description, FIRST.sample)]
    assert client.get(first["audio_url"]).content == b"RIFF1"


def test_concurrent_clicks_generate_once(monkeypatch):
    calls = []

    def slow(description, sample_text):
        calls.append(1)
        time.sleep(0.2)
        return b"RIFF"

    monkeypatch.setattr(engine, "design", slow)
    threads = [threading.Thread(target=client.post, args=(f"/api/gallery/presets/{FIRST.id}/sample",)) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1


def test_add_saves_exactly_what_was_heard(fake):
    client.post(f"/api/gallery/presets/{FIRST.id}/sample")
    voice = client.post(f"/api/gallery/presets/{FIRST.id}/add", json={}).json()
    assert voice["name"] == FIRST.name and voice["source"] == "design"
    assert voices.voice_audio_path(voice["id"]).read_bytes() == b"RIFF1"
    named = client.post(f"/api/gallery/presets/{FIRST.id}/add", json={"name": " Narrator 2 "}).json()
    assert named["name"] == "Narrator 2"


def test_must_listen_before_adding():
    assert client.post(f"/api/gallery/presets/{FIRST.id}/add", json={}).status_code == 409
    assert client.get(f"/api/gallery/presets/{FIRST.id}/audio").status_code == 409


def test_engine_error(monkeypatch):
    def boom(*a):
        raise RuntimeError("no model")

    monkeypatch.setattr(engine, "design", boom)
    r = client.post(f"/api/gallery/presets/{FIRST.id}/sample")
    assert r.status_code == 500 and "no model" in r.json()["detail"]
    assert client.get("/api/gallery/presets").json()[0]["ready"] is False


@pytest.mark.parametrize("bad", ["nope", "..", "%2e%2e%2fsecret"])
def test_unknown_presets(bad):
    assert client.post(f"/api/gallery/presets/{bad}/sample").status_code in (404, 405)
    assert client.get(f"/api/gallery/presets/{bad}/audio").status_code in (404, 405)
