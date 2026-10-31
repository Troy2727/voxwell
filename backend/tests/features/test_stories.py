import io
import wave

import pytest
from fastapi.testclient import TestClient

from voxwell import voices
from voxwell.features.stories import jobs
from voxwell.features.stories.script import NARRATOR, Line, ScriptError, parse, speakers
from voxwell.features.voice_cloning import engine
from voxwell.main import app

client = TestClient(app, base_url="http://127.0.0.1")
RATE = 24000

SCRIPT = """
Anna: Did you hear that?
Old Tom: Just the wind, love.

The door creaked open.
Anna: That was not the wind.
"""


def wav_bytes(seconds: float) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"\x01\x00" * int(seconds * RATE))
    return buf.getvalue()


@pytest.fixture
def fake(monkeypatch):
    calls = []

    def synth(text, language, reference_audio=None):
        calls.append((text, language, reference_audio.stem if reference_audio else None))
        return wav_bytes(1.0)

    monkeypatch.setattr(engine, "synthesize", synth)
    monkeypatch.setattr(jobs, "start", jobs._work)  # run synchronously
    return calls


def create(**body):
    return client.post("/api/stories/jobs", json={"script": SCRIPT, "language": "en", **body})


# --- script parsing ------------------------------------------------------------------------


def test_parse_speakers_and_narration():
    lines = parse(SCRIPT)
    assert lines == [
        Line("Anna", "Did you hear that?"),
        Line("Old Tom", "Just the wind, love."),
        Line(NARRATOR, "The door creaked open."),
        Line("Anna", "That was not the wind."),
    ]
    assert speakers(lines) == ["Anna", "Old Tom", NARRATOR]


@pytest.mark.parametrize("text", ["At 3:30 we left.", "See https://example.com", "1. Step one: go"])
def test_colons_in_ordinary_text_stay_narration(text):
    assert parse(text) == [Line(NARRATOR, text)]


def test_empty_speaker_lines_are_skipped():
    assert parse("Anna:\nBob: Hi") == [Line("Bob", "Hi")]


@pytest.mark.parametrize("script,error", [
    ("", "empty"),
    ("   \n\n", "empty"),
    ("\n".join(f"line {i}" for i in range(501)), "too long"),
    ("x" * 1001, "Line 1 is too long"),
    ("\n".join(f"Speaker{chr(65 + i)}: hi" for i in range(21)), "Too many speakers"),
])
def test_parse_rejects(script, error):
    with pytest.raises(ScriptError, match=error):
        parse(script)


def test_parse_endpoint():
    assert client.post("/api/stories/parse", json={"script": SCRIPT}).json() == {"speakers": ["Anna", "Old Tom", NARRATOR], "lines": 4}
    assert client.post("/api/stories/parse", json={"script": ""}).status_code == 422


# --- generating ----------------------------------------------------------------------------


def test_each_speaker_uses_their_voice(fake):
    anna = voices.save_voice("Anna's voice", wav_bytes(1), "upload")
    r = create(title="The Storm", cast={"Anna": anna.id})
    assert r.status_code == 200
    job = client.get(f"/api/stories/jobs/{r.json()['id']}").json()
    assert job["state"] == "done" and job["title"] == "The Storm" and job["percent"] == 100
    assert fake == [
        ("Did you hear that?", "en", anna.id),
        ("Just the wind, love.", "en", None),  # not cast: default voice
        ("The door creaked open.", "en", None),
        ("That was not the wind.", "en", anna.id),
    ]


def test_lines_are_joined_with_pauses(fake):
    jid = create().json()["id"]
    audio = client.get(f"/api/stories/jobs/{jid}/audio")
    assert audio.status_code == 200
    with wave.open(io.BytesIO(audio.content)) as w:
        seconds = w.getnframes() / w.getframerate()
    assert seconds == pytest.approx(4 * 1.0 + 3 * jobs.PAUSE_SECONDS, abs=0.01)


def test_title_defaults_to_the_first_line(fake):
    jid = create().json()["id"]
    assert client.get(f"/api/stories/jobs/{jid}").json()["title"] == "Did you hear that?"


@pytest.mark.parametrize("body,status", [
    ({"language": "xx"}, 422),
    ({"script": ""}, 422),
    ({"cast": {"Anna": "000000000000"}}, 422),
])
def test_rejects_bad_requests(fake, body, status):
    assert create(**body).status_code == status
    assert fake == []


def test_deleted_voice_fails_with_a_clear_message(fake, monkeypatch):
    anna = voices.save_voice("Anna", wav_bytes(1), "upload")
    monkeypatch.setattr(jobs, "start", lambda job: jobs._save(job))  # queue without running
    jid = create(cast={"Anna": anna.id}).json()["id"]
    voices.delete_voice(anna.id)
    jobs._work(jobs.get(jid))
    job = client.get(f"/api/stories/jobs/{jid}").json()
    assert job["state"] == "error" and "deleted" in job["error"]


def test_engine_failure_is_reported(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("out of memory")

    monkeypatch.setattr(engine, "synthesize", boom)
    monkeypatch.setattr(jobs, "start", jobs._work)
    jid = create().json()["id"]
    job = client.get(f"/api/stories/jobs/{jid}").json()
    assert job["state"] == "error" and job["error"] == "Speaking line 1 of 4 failed: out of memory"


def test_audio_needs_a_finished_story(fake, monkeypatch):
    monkeypatch.setattr(jobs, "start", lambda job: jobs._save(job))
    jid = create().json()["id"]
    assert client.get(f"/api/stories/jobs/{jid}/audio").status_code == 409


def test_interrupted_story_is_marked_after_restart(fake, monkeypatch):
    monkeypatch.setattr(jobs, "start", lambda job: jobs._save(job))
    jid = create().json()["id"]
    monkeypatch.setattr(jobs, "_jobs", {})
    job = client.get(f"/api/stories/jobs/{jid}").json()
    assert job["state"] == "error" and "closed" in job["error"]


@pytest.mark.parametrize("bad", ["000000000000", "ABCDEF123456", ".."])
def test_unknown_ids(bad):
    assert client.get(f"/api/stories/jobs/{bad}").status_code in (404, 405)
    assert client.get(f"/api/stories/jobs/{bad}/audio").status_code in (404, 405)


# --- projects ------------------------------------------------------------------------------


def test_projects_list_rename_delete(fake):
    anna = voices.save_voice("Anna's voice", wav_bytes(1), "upload")
    jid = create(title="The Storm", cast={"Anna": anna.id}).json()["id"]
    item = client.get("/api/projects/items").json()[0]
    assert item["kind"] == "story" and item["title"] == "The Storm"
    assert item["voice"] == "Anna's voice, Default voice" and item["speakers"] == ["Anna", "Old Tom", NARRATOR]
    assert client.get(item["audio_url"]).status_code == 200
    path = f"/api/projects/items/story/{jid}"
    assert client.patch(path, json={"title": "Night Storm"}).json()["title"] == "Night Storm"
    assert client.delete(path).status_code == 200
    assert client.get("/api/projects/items").json() == []


def test_running_story_cannot_be_deleted(fake, monkeypatch):
    monkeypatch.setattr(jobs, "start", lambda job: jobs._save(job))
    jid = create().json()["id"]
    assert client.delete(f"/api/projects/items/story/{jid}").status_code == 409
