from fastapi.testclient import TestClient

from voxwell import voices
from voxwell.main import app

client = TestClient(app, base_url="http://127.0.0.1")


def make(name="Narrators") -> dict:
    r = client.post("/api/voice_collections", json={"name": name})
    assert r.status_code == 201
    return r.json()


def test_status_and_empty_list():
    assert client.get("/api/voice_collections/status").json() == {"ready": True}
    assert client.get("/api/voice_collections").json() == []


def test_create_trims_and_lists():
    c = make("  Narrators ")
    assert c["name"] == "Narrators" and c["voice_ids"] == []
    assert client.get("/api/voice_collections").json() == [c]


def test_rename_and_delete():
    c = make()
    r = client.patch(f"/api/voice_collections/{c['id']}", json={"name": "Actors"})
    assert r.json()["name"] == "Actors"
    assert client.delete(f"/api/voice_collections/{c['id']}").json() == {"deleted": c["id"]}
    assert client.get("/api/voice_collections").json() == []


def test_names_are_unique_case_insensitively_and_non_empty():
    c = make("Narrators")
    assert client.post("/api/voice_collections", json={"name": " NARRATORS"}).status_code == 409
    assert client.post("/api/voice_collections", json={"name": "   "}).status_code == 422
    other = make("Actors")
    assert client.patch(f"/api/voice_collections/{other['id']}", json={"name": "narrators"}).status_code == 409
    assert client.patch(f"/api/voice_collections/{other['id']}", json={"name": ""}).status_code == 422
    # renaming to its own name in another case is allowed
    assert client.patch(f"/api/voice_collections/{c['id']}", json={"name": "NARRATORS"}).status_code == 200


def test_add_and_remove_voices_keep_order():
    c = make()
    a = voices.save_voice("Alice", b"RIFF....", "upload")
    b = voices.save_voice("Bob", b"RIFF....", "upload")
    for v in (b, a):
        assert client.put(f"/api/voice_collections/{c['id']}/voices/{v.id}").status_code == 200
    client.put(f"/api/voice_collections/{c['id']}/voices/{a.id}")  # adding twice changes nothing
    listed = client.get(f"/api/voice_collections/{c['id']}/voices").json()
    assert [v["name"] for v in listed] == ["Bob", "Alice"]
    r = client.delete(f"/api/voice_collections/{c['id']}/voices/{b.id}")
    assert r.json()["voice_ids"] == [a.id]


def test_deleting_a_voice_removes_it_from_every_collection():
    one, two = make("One"), make("Two")
    v = voices.save_voice("Alice", b"RIFF....", "upload")
    for c in (one, two):
        client.put(f"/api/voice_collections/{c['id']}/voices/{v.id}")
    assert client.delete(f"/api/voices/{v.id}").status_code == 200
    assert all(c["voice_ids"] == [] for c in client.get("/api/voice_collections").json())


def test_deleting_a_collection_keeps_its_voices():
    c = make()
    v = voices.save_voice("Alice", b"RIFF....", "upload")
    client.put(f"/api/voice_collections/{c['id']}/voices/{v.id}")
    client.delete(f"/api/voice_collections/{c['id']}")
    assert [x.id for x in voices.list_voices()] == [v.id]


def test_collections_file_is_not_listed_as_a_voice():
    make()
    assert voices.list_voices() == []


def test_unknown_ids_are_404():
    c = make()
    v = voices.save_voice("Alice", b"RIFF....", "upload")
    assert client.patch("/api/voice_collections/nope", json={"name": "x"}).status_code == 404
    assert client.delete("/api/voice_collections/nope").status_code == 404
    assert client.get("/api/voice_collections/nope/voices").status_code == 404
    assert client.put(f"/api/voice_collections/nope/voices/{v.id}").status_code == 404
    assert client.delete(f"/api/voice_collections/nope/voices/{v.id}").status_code == 404
    assert client.put(f"/api/voice_collections/{c['id']}/voices/ffffffffffff").status_code == 404
    assert client.put(f"/api/voice_collections/{c['id']}/voices/..%2Fx").status_code == 404
