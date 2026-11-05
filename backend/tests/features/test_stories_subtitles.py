import io
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient

from voxwell import voices
from voxwell.features.stories import jobs, subtitles
from voxwell.features.stories.script import MAX_LINE_LENGTH, MAX_LINES, ScriptError
from voxwell.features.voice_cloning import engine
from voxwell.main import app

client = TestClient(app, base_url="http://127.0.0.1")
RATE = 24000

SRT = """1
00:00:01,000 --> 00:00:03,000
<i>Hello there.</i>

2
00:00:05,500 --> 00:00:08,000
{\\an8}Two lines
of text.
"""


def tone(seconds: float) -> bytes:
    pcm = (np.full(int(RATE * seconds), 0.5) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def samples(wav: bytes):
    with wave.open(io.BytesIO(wav)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")


def wait(job_id):
    import time

    for _ in range(200):
        body = client.get(f"/api/stories/jobs/{job_id}").json()
        if body["state"] in ("done", "error"):
            return body
        time.sleep(0.02)
    raise AssertionError("the job didn't finish")


def upload(content=SRT, name="my film.srt", **data):
    return client.post("/api/stories/subtitles", data={"language": "en", **data}, files={"file": (name, content.encode() if isinstance(content, str) else content, "text/plain")})


def test_cues_keep_their_times_and_lose_their_markup():
    cues = subtitles.parse(SRT)
    assert [(c.start, c.end, c.text) for c in cues] == [(1.0, 3.0, "Hello there."), (5.5, 8.0, "Two lines of text.")]


def test_windows_line_endings_dots_and_a_missing_number_still_parse():
    cues = subtitles.parse("00:00:01.5 --> 00:00:02.5\r\nOne.\r\n\r\n2\r\n00:01:00,000 --> 00:01:01,000\r\nTwo.\r\n")
    assert [(c.start, c.text) for c in cues] == [(1.5, "One."), (60.0, "Two.")]


def test_cues_are_put_in_time_order_and_empty_ones_are_skipped():
    cues = subtitles.parse("1\n00:00:09,000 --> 00:00:10,000\nLater.\n\n2\n00:00:01,000 --> 00:00:02,000\n<i></i>\n\n3\n00:00:03,000 --> 00:00:04,000\nSooner.\n")
    assert [c.text for c in cues] == ["Sooner.", "Later."]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("Just some plain text.", "No subtitles"),
        ("".join(f"{i}\n00:00:01,000 --> 00:00:02,000\nA\n\n" for i in range(MAX_LINES + 1)), "too many"),
        (f"1\n00:00:01,000 --> 00:00:02,000\n{'a' * (MAX_LINE_LENGTH + 1)}\n", "too long"),
    ],
)
def test_files_that_cant_be_spoken_are_refused(text, message):
    with pytest.raises(ScriptError, match=message):
        subtitles.parse(text)


def test_each_clip_starts_at_its_cue_with_silence_between():
    cues = subtitles.parse(SRT)
    out = samples(subtitles.place(cues, [tone(1), tone(1)]))
    assert len(out) == int(RATE * 6.5)
    assert not out[: RATE - 10].any(), "silent before the first cue"
    assert out[RATE + 10 : 2 * RATE - 10].all(), "speaking during the first cue"
    assert not out[2 * RATE + 10 : int(5.5 * RATE) - 10].any(), "silent between the cues"
    assert out[int(5.5 * RATE) + 10 :].any()


def test_a_clip_too_long_for_its_cue_is_sped_up_to_fit():
    cues = [subtitles.Cue(0.0, 2.0, "Long."), subtitles.Cue(2.5, 3.0, "Next.")]
    out = subtitles.place(cues, [tone(2.5), tone(0.2)])
    audio = samples(out)
    # 2.5 s in a 2 s cue: tempo 1.25, so it ends at about 2 s and the next stays on time at 2.5 s.
    assert not audio[int(2.1 * RATE) : int(2.45 * RATE)].any()
    assert audio[int(2.55 * RATE) : int(2.65 * RATE)].any()


def test_a_clip_that_still_doesnt_fit_pushes_the_next_one_later_and_loses_nothing():
    cues = [subtitles.Cue(0.0, 1.0, "Very long."), subtitles.Cue(1.0, 2.0, "Next.")]
    audio = samples(subtitles.place(cues, [tone(3), tone(1)]))
    # At the 1.5x limit the first clip takes 2 s, so the second starts at 2 s and runs its full 1 s.
    assert len(audio) / RATE >= 2.5
    assert audio[int(1.8 * RATE) : int(1.9 * RATE)].any(), "the first clip wasn't cut off at its cue's end"


def test_upload_speaks_each_cue_in_the_chosen_voice(monkeypatch):
    calls = []

    def fake(text, language, reference=None):
        calls.append((text, language, reference))
        return tone(1)

    monkeypatch.setattr(engine, "synthesize", fake)
    voice = voices.save_voice("Sub voice", tone(1), "upload")
    r = upload(voice_id=voice.id)
    assert r.status_code == 200, r.text
    body = wait(r.json()["id"])
    assert body["state"] == "done" and body["title"] == "my film"
    assert [c[0] for c in calls] == ["Hello there.", "Two lines of text."]
    assert all(c[2] == voices.voice_audio_path(voice.id) for c in calls)
    audio = client.get(body["audio_url"]).content
    assert len(samples(audio)) == int(RATE * 6.5)


def test_upload_without_a_voice_uses_the_default_one(monkeypatch):
    seen = []
    monkeypatch.setattr(engine, "synthesize", lambda text, language, reference=None: seen.append(reference) or tone(1))
    assert wait(upload().json()["id"])["state"] == "done"
    assert seen == [None, None]


def test_older_windows_subtitle_files_still_upload(monkeypatch):
    seen = []
    monkeypatch.setattr(engine, "synthesize", lambda text, language, reference=None: seen.append(text) or tone(1))
    assert upload("1\n00:00:01,000 --> 00:00:02,000\nCafé.\n".encode("cp1252")).status_code == 200
    jobs_done = [j for j in jobs.list_jobs() if j.title == "my film"]
    assert jobs_done
    wait(jobs_done[0].id)
    assert seen == ["Café."]


@pytest.mark.parametrize(
    ("kwargs", "status", "message"),
    [
        ({"content": "not subtitles"}, 422, "No subtitles"),
        ({"language": "xx"}, 422, "Unsupported language"),
        ({"voice_id": "missing"}, 422, "Unknown voice"),
        ({"content": b"x" * (3 * 1024 * 1024)}, 413, "too large"),
    ],
)
def test_bad_uploads_are_refused_with_a_reason(kwargs, status, message):
    r = upload(**kwargs)
    assert r.status_code == status
    assert message in r.json()["detail"]
