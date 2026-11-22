"""Natural pauses: pauses carry the take's quiet background instead of silence."""

import io
import json
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient

from voxwell.features.audio_effects import pause_fill
from voxwell.features.audio_effects.dsp import CEILING
from voxwell.features.audiobook import books
from voxwell.features.audiobook.importer import Chapter
from voxwell.features.stories import jobs
from voxwell.features.voice_cloning import engine
from voxwell.main import app

client = TestClient(app, base_url="http://127.0.0.1")
RATE = 24000
HISS = 0.003  # about -50 dBFS


def hiss(seconds, seed=1):
    white = np.random.RandomState(seed).standard_normal(int(seconds * RATE))
    low = np.convolve(white, np.ones(8) / 8, mode="same")  # low-passed: most energy in the low half
    return (low / np.sqrt(np.mean(low**2)) * HISS).astype(np.float32)


def take(seed=1):
    """Speech as a model gives it: background, a loud tone, background."""
    tone = 0.3 * np.sin(2 * np.pi * 220 * np.arange(int(0.4 * RATE)) / RATE)
    return np.concatenate([hiss(0.3, seed), hiss(0.4, seed + 10) + tone, hiss(0.3, seed + 20)]).astype(np.float32)


def rms(x):
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))


def to_wav(x):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def samples(wav):
    with wave.open(io.BytesIO(wav)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768


GAP = int(0.5 * RATE)


# --- the fill itself ----------------------------------------------------------------------------


def test_a_pause_carries_the_background_at_its_level_and_colour():
    a, b = take(1), take(2)
    out = pause_fill.join([a, GAP, b], RATE)
    assert len(out) == len(a) + GAP + len(b)
    middle = out[len(a) + 2000 : len(a) + GAP - 2000]
    assert abs(20 * np.log10(rms(middle) / HISS)) < 3
    spectrum = np.abs(np.fft.rfft(middle))
    assert spectrum[: len(spectrum) // 2].sum() > 2 * spectrum[len(spectrum) // 2 :].sum()
    untouched = len(a) - int(pause_fill.EDGE_SECONDS * RATE)  # speech before the blended edge
    np.testing.assert_array_equal(out[:untouched], a[:untouched])


def test_the_same_input_sounds_the_same_and_each_pause_is_fresh_noise():
    a, b, c = take(1), take(2), take(3)
    first = pause_fill.join([a, GAP, b, GAP, c], RATE)
    np.testing.assert_array_equal(first, pause_fill.join([a, GAP, b, GAP, c], RATE))
    one = first[len(a) + 2000 : len(a) + 4000]
    two = first[len(a) + GAP + len(b) + 2000 : len(a) + GAP + len(b) + 4000]
    assert not np.allclose(one, two)


@pytest.mark.parametrize("pieces", [
    [],  # no speech at all
    [0.2 * np.sin(np.arange(RATE) / 3).astype(np.float32)],  # no quiet stretch
    [np.zeros(RATE, dtype=np.float32)],  # only digital silence
    [take()[: int(0.15 * RATE)]],  # too little speech to measure
])
def test_with_nothing_to_match_pauses_stay_silent(pieces):
    out = pause_fill.join([*pieces, GAP], RATE)
    assert len(out) == sum(len(p) for p in pieces) + GAP
    assert not out[len(out) - GAP :].any()


def test_touching_pauses_are_one_pause():
    a, b = take(1), take(2)
    np.testing.assert_array_equal(pause_fill.join([a, 100, GAP - 100, b], RATE), pause_fill.join([a, GAP, b], RATE))


def test_the_mix_never_clips_and_has_no_click_at_the_edges():
    loud = take() * 3.2  # tone peaks near full scale
    out = pause_fill.join([loud, GAP, loud], RATE)
    # The noise never pushes past the ceiling, or past the speech's own peak when that is higher;
    # the speech itself keeps its level.
    assert np.max(np.abs(out)) <= max(CEILING, float(np.max(np.abs(loud)))) + 1e-6
    np.testing.assert_array_equal(out[: len(loud) // 2], loud[: len(loud) // 2])
    a, b = take(1), take(2)
    out = pause_fill.join([a, GAP, b], RATE)
    for edge in (len(a), len(a) + GAP):
        assert np.max(np.abs(np.diff(out[edge - 50 : edge + 50]))) < 10 * HISS


def test_wav_clips_join_with_natural_pauses():
    a, b = to_wav(take(1)), to_wav(take(2))
    out = samples(pause_fill.join_wavs([(a, 0.5), (b, 0)]))
    assert len(out) == 2 * len(take()) + GAP
    assert out[len(take()) + 2000 : len(take()) + GAP - 2000].any()


# --- where it is used -----------------------------------------------------------------------------


class Model:
    sr = RATE

    def generate(self, text, **kwargs):
        return take(len(text))


def test_synthesize_fills_pause_markers_only_when_asked(monkeypatch):
    monkeypatch.setattr(engine, "_load_model", lambda: Model())
    plain = samples(engine.synthesize("Hello. [pause 0.5] Bye.", "en"))
    expected = np.concatenate([take(6), np.zeros(GAP, dtype=np.float32), take(4)])
    np.testing.assert_array_equal(plain, samples(engine._to_wav(expected, RATE)))  # off: exactly as before
    natural = samples(engine.synthesize("Hello. [pause 0.5] Bye.", "en", natural_pauses=True))
    assert len(natural) == len(plain)
    assert natural[len(take()) + 2000 : len(take()) + GAP - 2000].any()


def test_the_cloning_request_passes_the_setting(monkeypatch):
    seen = []
    monkeypatch.setattr(engine, "synthesize", lambda text, language, reference=None, **kw: seen.append(kw) or to_wav(take()))
    client.post("/api/voice_cloning/synthesize", json={"text": "Hi.", "language": "en"})
    client.post("/api/voice_cloning/synthesize", json={"text": "Hi.", "language": "en", "natural_pauses": True})
    assert seen == [{}, {"natural_pauses": True}]


def test_a_story_fills_its_line_gaps_and_keeps_the_setting(monkeypatch):
    seen = []

    def synth(text, language, reference=None, **kw):
        seen.append(kw)
        return to_wav(take(len(text)))

    monkeypatch.setattr(engine, "synthesize", synth)
    monkeypatch.setattr(jobs, "start", jobs._work)
    gap_at = len(take())
    script = "Anna: One.\nTom: Two."
    for natural in (False, True):
        job_id = client.post("/api/stories/jobs", json={"script": script, "natural_pauses": natural}).json()["id"]
        job = jobs.get(job_id)
        out = samples(jobs.audio_path(job).read_bytes())
        gap = out[gap_at + 2000 : gap_at + int(jobs.PAUSE_SECONDS * RATE) - 2000]
        assert bool(gap.any()) == natural
        assert json.loads((job.dir / jobs.STATE_FILE).read_text())["natural_pauses"] is natural
    assert seen == [{}, {}, {"natural_pauses": True}, {"natural_pauses": True}]


def test_an_old_story_without_the_setting_still_loads():
    job = jobs.create("Old", "en", "Anna: Hi.", {"Anna": "default"})
    jobs._save(job)
    state = json.loads((job.dir / jobs.STATE_FILE).read_text())
    del state["natural_pauses"]
    (job.dir / jobs.STATE_FILE).write_text(json.dumps(state))
    assert jobs._load(job.dir).natural_pauses is False


def test_book_gaps_are_filled_only_when_asked(monkeypatch):
    seen = []
    monkeypatch.setattr(engine, "synthesize", lambda text, language, reference=None, **kw: seen.append(kw) or to_wav(take(len(text))))
    paragraphs = [["One.", "Two."], ["Three."]]
    plain = samples(books.render_text(paragraphs, "en", None))
    natural = samples(books.render_text(paragraphs, "en", None, natural_pauses=True))
    assert len(natural) == len(plain)
    for start, pause in ((len(take()), books.SENTENCE_PAUSE), (2 * len(take()) + int(books.SENTENCE_PAUSE * RATE), books.PARAGRAPH_PAUSE)):
        gap = slice(start + 1000, start + int(pause * RATE) - 1000)
        assert not plain[gap].any() and natural[gap].any()
    assert seen == [{}] * 3 + [{"natural_pauses": True}] * 3


def test_a_book_setting_change_renders_the_chapters_again(monkeypatch):
    monkeypatch.setattr(engine, "synthesize", lambda text, language, reference=None, **kw: to_wav(take(len(text))))
    book = books.create("Book", [Chapter("One", "First sentence here. Second sentence here.")])
    books._work(book)
    assert book.chapters[0].status == "done"
    assert client.patch(f"/api/audiobook/books/{book.id}", json={"natural_pauses": False}).json()["chapters"][0]["status"] == "done"
    body = client.patch(f"/api/audiobook/books/{book.id}", json={"natural_pauses": True}).json()
    assert body["natural_pauses"] is True and body["chapters"][0]["status"] == "pending"
    books._work(book)
    assert book.chapters[0].status == "done"
    state = json.loads((book.dir / books.STATE_FILE).read_text())
    assert state["natural_pauses"] is True
    del state["natural_pauses"]
    (book.dir / books.STATE_FILE).write_text(json.dumps(state))
    assert books._load(book.dir).natural_pauses is False


def test_a_short_word_between_pauses_never_doubles_the_background():
    a = take(1)
    word = take(2)[: int(0.01 * RATE)]  # 10 ms, shorter than the fades
    out = pause_fill.join([a, GAP, word, GAP, a], RATE)
    middle = out[len(a) + GAP - 200 : len(a) + GAP + len(word) + 200]
    assert rms(middle) < 2.5 * HISS


def test_pauses_in_different_takes_are_different_noise():
    one = pause_fill.join([take(1), GAP, take(2)], RATE)
    two = pause_fill.join([take(3), GAP, take(4)], RATE)
    gap = slice(len(take()) + 2000, len(take()) + 4000)
    assert not np.allclose(one[gap], two[gap])


def test_joining_no_wav_clips_is_refused():
    with pytest.raises(ValueError):
        pause_fill.join_wavs([])
