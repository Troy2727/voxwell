import io
import json
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from voxwell import results, voices
from voxwell.features.dictation import engine as dictation_engine
from voxwell.features.dictation.engine import Segment, Transcript
from voxwell.features.dubbing import ffmpeg, jobs
from voxwell.features.dubbing import translate as translator
from voxwell.features.music import history as music
from voxwell.features.sound import history as sounds
from voxwell.features.tools import engine as tools_engine
from voxwell.features.tools import isolation
from voxwell.features.voice_cloning import engine as cloning_engine
from voxwell.main import app

client = TestClient(app, base_url="http://127.0.0.1")


def wav_bytes(seconds: float = 1.0, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(seconds * rate))
    return buf.getvalue()


@pytest.fixture
def mocked(monkeypatch):
    def fake_ffmpeg(args):
        out = Path(args[-1])
        out.write_bytes(wav_bytes() if out.suffix == ".wav" else b"video")

    monkeypatch.setattr(ffmpeg, "run_ffmpeg", fake_ffmpeg)
    monkeypatch.setattr(dictation_engine, "transcribe", lambda p, language=None: Transcript("hola", "es", [Segment(0.0, 1.0, "hola")]))
    monkeypatch.setattr(translator, "translate", lambda texts, s, t: texts)
    monkeypatch.setattr(cloning_engine, "synthesize", lambda text, language, reference_audio=None: wav_bytes())
    monkeypatch.setattr(jobs, "start", jobs._work)  # run synchronously


def speak(text="Hello there", voice_id=None):
    r = client.post("/api/voice_cloning/synthesize", json={"text": text, "language": "en", "voice_id": voice_id})
    assert r.status_code == 200
    return r.json()["id"]


def dub(name="Holiday clip.mp4"):
    r = client.post(
        "/api/dubbing/jobs",
        files={"file": (name, b"fakevideo", "video/mp4")},
        data={"target_language": "en", "voice": "original"},
    )
    assert r.status_code == 200
    return r.json()["id"]


def items():
    return client.get("/api/projects/items").json()


def test_empty():
    assert items() == []


def test_lists_speech_and_dubs_newest_first(mocked):
    voice = voices.save_voice("Alice", wav_bytes(), "upload")
    clip_id = speak("Hello there", voice.id)
    job_id = dub()
    found = items()
    assert [(i["kind"], i["id"]) for i in found] == [("dub", job_id), ("speech", clip_id)]
    d, s = found
    assert d["title"] == "Holiday clip" and d["state"] == "done" and d["voice"] == "Original speaker"
    assert client.get(d["video_url"]).content == b"video"
    assert s["title"] == "Hello there" and s["voice"] == "Alice" and s["language"] == "en"
    assert client.get(s["audio_url"]).content[:4] == b"RIFF"


def test_long_text_gets_a_short_title(mocked):
    speak("word " * 40)
    title = items()[0]["title"]
    assert len(title) <= 60 and title.endswith("…")


def test_rename_speech_and_dub(mocked):
    clip_id, job_id = speak(), dub()
    assert client.patch(f"/api/projects/items/speech/{clip_id}", json={"title": " Intro "}).json()["title"] == "Intro"
    assert client.patch(f"/api/projects/items/dub/{job_id}", json={"title": "Final cut"}).json()["title"] == "Final cut"
    assert {i["title"] for i in items()} == {"Intro", "Final cut"}


def test_dub_title_survives_restart(mocked, monkeypatch):
    job_id = dub()
    client.patch(f"/api/projects/items/dub/{job_id}", json={"title": "Kept"})
    monkeypatch.setattr(jobs, "_jobs", {})  # simulate a restart
    assert items()[0]["title"] == "Kept"


def test_jobs_saved_before_titles_still_list(mocked, monkeypatch):
    job_id = dub()
    state_file = jobs.get(job_id).dir / jobs.STATE_FILE
    state = json.loads(state_file.read_text(encoding="utf-8"))
    del state["title"], state["created"]
    state_file.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(jobs, "_jobs", {})
    item = items()[0]
    assert item["title"] == "Dub" and item["created"] > 0


@pytest.mark.parametrize("title", ["", "   ", "x" * 101])
def test_rename_rejects_bad_titles(mocked, title):
    clip_id = speak()
    assert client.patch(f"/api/projects/items/speech/{clip_id}", json={"title": title}).status_code == 422


def test_delete_speech_removes_files(mocked, isolated_data_dir):
    clip_id = speak()
    assert client.delete(f"/api/projects/items/speech/{clip_id}").status_code == 200
    assert items() == []
    assert list((isolated_data_dir / "voice_cloning").iterdir()) == []


def test_delete_dub_removes_folder(mocked):
    job_id = dub()
    folder = jobs.get(job_id).dir
    assert client.delete(f"/api/projects/items/dub/{job_id}").status_code == 200
    assert not folder.exists() and items() == []


def test_running_dub_cannot_be_deleted(mocked, monkeypatch):
    monkeypatch.setattr(jobs, "start", lambda job: None)  # stays queued
    job_id = dub()
    r = client.delete(f"/api/projects/items/dub/{job_id}")
    assert r.status_code == 409 and jobs.get(job_id).dir.exists()


def test_dub_with_deleted_voice_still_lists(mocked):
    voice = voices.save_voice("Alice", wav_bytes(), "upload")
    r = client.post(
        "/api/dubbing/jobs",
        files={"file": ("a.mp4", b"fakevideo", "video/mp4")},
        data={"target_language": "en", "voice": voice.id},
    )
    voices.delete_voice(voice.id)
    assert items()[0]["id"] == r.json()["id"] and items()[0]["voice"] == "Deleted voice"


@pytest.mark.parametrize("kind,item_id", [
    ("speech", "0" * 32), ("dub", "0" * 12), ("speech", "../x"), ("dub", "ABC"), ("other", "0" * 12),
])
def test_unknown_items(kind, item_id):
    assert client.patch(f"/api/projects/items/{kind}/{item_id}", json={"title": "x"}).status_code in (404, 422)
    assert client.delete(f"/api/projects/items/{kind}/{item_id}").status_code in (404, 422)


# --- Music, sound effects and kept results (Tools, Audio effects, Translation) ----------------


@pytest.fixture
def tools(monkeypatch):
    def fake_isolate(source, voice_out, background_out):
        voice_out.write_bytes(wav_bytes())
        background_out.write_bytes(wav_bytes())
        return 1.0

    monkeypatch.setattr(tools_engine, "convert", lambda source, target: wav_bytes())
    monkeypatch.setattr(isolation, "isolate", fake_isolate)
    monkeypatch.setattr(cloning_engine, "synthesize", lambda text, language, reference_audio=None, **kw: wav_bytes())


def convert(name="Interview take.wav"):
    voice = voices.save_voice("Alice", wav_bytes(), "upload")
    r = client.post("/api/tools/convert", files={"file": (name, wav_bytes())}, data={"voice_id": voice.id})
    assert r.status_code == 200
    return r.json()


def test_converted_recording_is_kept(tools):
    convert()
    [item] = items()
    assert (item["kind"], item["title"], item["voice"], item["state"]) == ("conversion", "Interview take", "Alice", "done")
    [file] = item["files"]
    assert file["label"] == "Audio" and not file["video"]
    assert client.get(file["url"]).content[:4] == b"RIFF"


def test_isolation_keeps_both_parts(tools):
    r = client.post("/api/tools/isolate", files={"file": ("Song.wav", wav_bytes())})
    assert r.status_code == 200
    [item] = items()
    assert item["kind"] == "isolation" and item["title"] == "Song"
    assert [f["label"] for f in item["files"]] == ["Voice", "Background"]
    assert all(client.get(f["url"]).status_code == 200 for f in item["files"])


def test_audio_effects_result_is_kept():
    r = client.post("/api/audio_effects/apply", files={"file": ("Room.wav", wav_bytes())}, data={"reverb": "0.3"})
    assert r.status_code == 200
    [item] = items()
    assert item["kind"] == "effects" and item["title"] == "Room" and item["files"][0]["url"] == r.json()["url"]


def test_translation_is_kept(monkeypatch):
    monkeypatch.setattr(translator, "translate", lambda texts, s, t: [f"{x}-{t}" for x in texts])
    monkeypatch.setattr(cloning_engine, "synthesize", lambda text, language, reference=None, **kw: wav_bytes())
    r = client.post("/api/translation/speak", json={"text": "Good morning", "target": "de"})
    assert r.status_code == 200
    [item] = items()
    assert (item["kind"], item["title"], item["text"], item["language"]) == ("translation", "Good morning", "Good morning-de", "de")
    assert item["files"][0]["url"] == r.json()["url"]


def test_scratch_outputs_still_expire_but_kept_ones_stay(tools, isolated_data_dir):
    import os
    import time

    kept = isolated_data_dir / "tools" / (convert()["url"].rsplit("/", 1)[1] + ".wav")
    scratch = isolated_data_dir / "tools" / (client.post("/api/tools/speak", json={"text": "Hi"}).json()["url"].rsplit("/", 1)[1] + ".wav")
    for path in (kept, scratch):
        os.utime(path, (time.time() - 2 * 86400,) * 2)
    client.post("/api/tools/speak", json={"text": "Hi again"})
    assert kept.exists() and not scratch.exists()
    assert [i["kind"] for i in items()] == ["conversion"]


def test_rename_and_delete_kept_result(tools, isolated_data_dir):
    client.post("/api/tools/isolate", files={"file": ("Song.wav", wav_bytes())})
    item_id = items()[0]["id"]
    r = client.patch(f"/api/projects/items/isolation/{item_id}", json={"title": "Vocals only"})
    assert r.status_code == 200 and r.json()["title"] == "Vocals only"
    assert client.delete(f"/api/projects/items/isolation/{item_id}").status_code == 200
    assert items() == [] and list((isolated_data_dir / "tools").glob("*.*")) == []


def test_kept_result_is_only_found_under_its_own_kind(tools):
    item_id = convert()["url"].rsplit("/", 1)[1]
    assert client.patch(f"/api/projects/items/fit/{item_id}", json={"title": "x"}).status_code == 404
    assert client.delete(f"/api/projects/items/effects/{item_id}").status_code == 404
    assert len(items()) == 1


def make_track(status="done", stems=False):
    track = music.create(music.Track(
        id="c" * 32, title="Night drive", prompt="synthwave, slow", lyrics="", instrumental=True, language="en",
        duration=30, bpm=None, key="", seed=1, steps=8, created=0, status=status, stems=stems,
    ))
    music.save_audio(track.id, wav_bytes())
    return track


def test_music_tracks_are_listed_renamed_and_deleted():
    track = make_track()
    [item] = items()
    assert (item["kind"], item["title"], item["state"], item["text"]) == ("music", "Night drive", "done", "synthwave, slow")
    assert [f["label"] for f in item["files"]] == ["Song"]
    assert client.patch(f"/api/projects/items/music/{track.id}", json={"title": "Late drive"}).json()["title"] == "Late drive"
    assert music.get(track.id).title == "Late drive"
    assert client.delete(f"/api/projects/items/music/{track.id}").status_code == 200
    assert items() == []


def test_music_left_generating_by_an_earlier_run_shows_as_failed():
    make_track(status="generating")
    item = items()[0]
    assert item["state"] == "error" and item["files"] == []


def test_sound_effects_are_listed_renamed_and_deleted(isolated_data_dir):
    sounds.save("d" * 32, wav_bytes(), "rain on a tin roof", 5, 1, 100)
    [item] = items()
    assert (item["kind"], item["title"], item["text"]) == ("sound", "rain on a tin roof", "rain on a tin roof")
    assert client.patch(f"/api/projects/items/sound/{'d' * 32}", json={"title": "Rain"}).json()["title"] == "Rain"
    assert items()[0]["title"] == "Rain" and items()[0]["text"] == "rain on a tin roof"
    assert client.delete(f"/api/projects/items/sound/{'d' * 32}").status_code == 200
    assert items() == [] and list((isolated_data_dir / "sound").iterdir()) == []


@pytest.mark.parametrize("kind,item_id", [
    ("music", "0" * 32), ("sound", "0" * 32), ("sound", "../x"), ("conversion", "0" * 32), ("translation", "ABC"),
])
def test_unknown_new_kinds(kind, item_id):
    assert client.patch(f"/api/projects/items/{kind}/{item_id}", json={"title": "x"}).status_code == 404
    assert client.delete(f"/api/projects/items/{kind}/{item_id}").status_code == 404


def test_unreadable_record_does_not_hide_the_others(tools, isolated_data_dir):
    convert()
    (isolated_data_dir / "tools" / ("e" * 32 + ".json")).write_text("{not json", encoding="utf-8")
    assert [i["kind"] for i in items()] == ["conversion"]


def test_titles_are_short():
    assert results.title_from("  ", "Fallback") == "Fallback"
    assert len(results.title_from("word " * 40, "x")) <= results.TITLE_LENGTH
