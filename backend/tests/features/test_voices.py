import pytest
from fastapi.testclient import TestClient

from voxwell import voices
from voxwell.main import app

client = TestClient(app, base_url="http://127.0.0.1")


def test_status():
    assert client.get("/api/voices/status").json() == {"ready": True}


def test_list_still_served_at_root():
    voice = voices.save_voice("Alice", b"RIFF....", "upload")
    assert client.get("/api/voices").json() == [{"id": voice.id, "name": "Alice", "source": "upload"}]


def test_audio():
    voice = voices.save_voice("Alice", b"RIFF....", "upload")
    r = client.get(f"/api/voices/{voice.id}/audio")
    assert r.status_code == 200 and r.content == b"RIFF...."


def test_rename():
    voice = voices.save_voice("Alice", b"RIFF", "design")
    r = client.patch(f"/api/voices/{voice.id}", json={"name": "  Bob  "})
    assert r.json() == {"id": voice.id, "name": "Bob", "source": "design"}
    assert voices.list_voices()[0].name == "Bob"


def test_rename_requires_a_name():
    voice = voices.save_voice("Alice", b"RIFF", "upload")
    assert client.patch(f"/api/voices/{voice.id}", json={"name": "   "}).status_code == 422
    assert voices.get_voice(voice.id).name == "Alice"


def test_delete_removes_audio_and_metadata(isolated_data_dir):
    voice = voices.save_voice("Alice", b"RIFF", "upload")
    assert client.delete(f"/api/voices/{voice.id}").json() == {"deleted": voice.id}
    assert voices.list_voices() == []
    assert list((isolated_data_dir / "voices").iterdir()) == []
    assert client.get(f"/api/voices/{voice.id}/audio").status_code == 404


@pytest.mark.parametrize("bad", ["000000000000", "ABCDEF123456", "..", "%2e%2e%2f%2e%2e%2fx"])
def test_unknown_or_malformed_ids(bad):
    assert client.get(f"/api/voices/{bad}/audio").status_code in (404, 405)
    assert client.patch(f"/api/voices/{bad}", json={"name": "x"}).status_code in (404, 405)
    assert client.delete(f"/api/voices/{bad}").status_code in (404, 405)
