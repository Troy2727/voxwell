from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from voxwell.features.dictation import engine
from voxwell.features.dictation.engine import AudioError, Word, WordTimings
from voxwell.features.transcription import alignment
from voxwell.features.transcription.alignment import AlignedWord, align, build_cues, normalize, script_words
from voxwell.main import app

client = TestClient(app)

HEARD = [(0.0, 0.4, "Hello"), (0.5, 0.9, "there"), (1.0, 1.5, "and"), (1.6, 2.2, "welcome")]


def times(result):
    return [(w.start, w.end) for w in result.words]


def monotonic(words):
    return all(a.start <= b.start for a, b in zip(words, words[1:])) and all(w.start <= w.end for w in words)


# --- text handling -------------------------------------------------------------------------


def test_normalize_ignores_case_accents_and_punctuation():
    assert normalize("Café,") == "cafe"
    assert normalize("“Don't!”") == "dont"
    assert normalize("3.5%") == "35"
    assert normalize("—") == ""


def test_script_words_keep_punctuation_and_attach_symbols():
    assert script_words("Hello, world — and  more.\n\nBye") == ["Hello,", "world —", "and", "more.", "Bye"]
    assert script_words("— Hello") == ["— Hello"]
    assert script_words("  \n ") == []


# --- alignment -----------------------------------------------------------------------------


def test_perfect_match_takes_the_heard_times():
    result = align("Hello there, and welcome!", HEARD)
    assert times(result) == [(0.0, 0.4), (0.5, 0.9), (1.0, 1.5), (1.6, 2.2)]
    assert result.matched == 4 and not result.fallback and all(w.matched for w in result.words)
    assert [w.text for w in result.words] == ["Hello", "there,", "and", "welcome!"]


def test_inserted_script_words_are_interpolated_between_neighbours():
    result = align("Hello there my dear and welcome", HEARD)
    my, dear = result.words[2], result.words[3]
    assert not my.matched and not dear.matched and result.matched == 4
    assert 0.9 <= my.start < my.end <= dear.start < dear.end <= 1.0
    assert monotonic(result.words)


def test_deleted_script_word_is_simply_skipped():
    result = align("Hello and welcome", HEARD)  # the speaker also said "there"
    assert [w.matched for w in result.words] == [True, True, True]
    assert result.words[1].start == 1.0


def test_misheard_word_of_the_same_length_keeps_the_heard_time():
    result = align("Hello their and welcome", HEARD)
    assert result.words[1].matched and times(result)[1] == (0.5, 0.9)


def test_leading_and_trailing_unmatched_words_stay_ordered_and_non_negative():
    result = align("Oh well hello there and welcome again friends", HEARD)
    assert result.matched == 4 and monotonic(result.words)
    assert result.words[0].start >= 0 and result.words[2].start == 0.0
    assert result.words[-2].start >= 2.2 and result.words[-1].end > result.words[-2].start


def test_gap_is_spread_by_word_length():
    result = align("a bbb c", [(0.0, 1.0, "a"), (4.0, 5.0, "c")])
    assert times(result)[1] == (1.0, 4.0) and not result.words[1].matched


def test_nothing_matched_falls_back_to_the_heard_span():
    result = align("alpha beta gamma delta", [(2.0, 4.0, "foo"), (4.5, 6.0, "bar")])
    assert result.fallback and result.matched == 0 and not any(w.matched for w in result.words)
    assert result.words[0].start == 2.0 and result.words[-1].end == 6.0 and monotonic(result.words)


def test_nothing_heard_estimates_from_the_word_count():
    result = align("one two three", [])
    assert result.fallback and result.words[0].start == 0.0
    assert result.words[-1].end == pytest.approx(3 * alignment.SECONDS_PER_WORD, abs=0.01)


def test_overlapping_heard_times_are_made_monotonic():
    assert monotonic(align("a b c", [(1.0, 2.0, "a"), (0.5, 0.8, "b"), (0.7, 3.0, "c")]).words)


# --- cues ----------------------------------------------------------------------------------


def words(*items):
    return [AlignedWord(t, a, b, True) for t, a, b in items]


def texts(cues):
    return [c.text for c in cues]


def test_cues_split_at_max_chars():
    ws = words(("alpha", 0, 1), ("beta", 1, 2), ("gamma", 2, 3), ("delta", 3, 4))
    assert texts(build_cues(ws, max_chars=11)) == ["alpha beta", "gamma delta"]
    assert texts(build_cues(ws, max_chars=10)) == ["alpha beta", "gamma", "delta"]  # "alpha beta" is exactly 10
    assert texts(build_cues(ws, max_chars=9)) == ["alpha", "beta", "gamma", "delta"]
    assert texts(build_cues(ws, max_chars=16)) == ["alpha beta gamma", "delta"]


def test_cues_split_at_max_seconds_and_at_pauses():
    ws = words(("a", 0, 1), ("b", 1, 2), ("c", 2, 3), ("d", 3, 4))
    assert texts(build_cues(ws, max_chars=100, max_seconds=2.5, max_gap=10)) == ["a b", "c d"]
    paused = words(("a", 0, 1), ("b", 1, 2), ("c", 2, 3), ("d", 5, 6))
    assert texts(build_cues(paused, max_chars=100, max_seconds=100, max_gap=1.0)) == ["a b c", "d"]


def test_cues_end_at_sentence_ends_once_long_enough():
    ws = words(("Hello", 0, 1), ("there.", 1, 2), ("Yes.", 2, 3), ("It", 3, 4), ("is", 4, 5))
    assert texts(build_cues(ws, max_chars=30)) == ["Hello there.", "Yes. It is"]
    assert texts(build_cues(words(("Hi.", 0, 1), ("Ok", 1, 2)), max_chars=60)) == ["Hi. Ok"]  # too short to end a cue


def test_a_word_longer_than_the_limit_gets_its_own_cue():
    ws = words(("short", 0, 1), ("extraordinarily", 1, 2), ("ok", 2, 3))
    assert texts(build_cues(ws, max_chars=10)) == ["short", "extraordinarily", "ok"]


def test_cues_are_ordered_and_never_overlap():
    ws = align("a b c", [(0, 5, "a"), (1, 6, "b"), (2, 7, "c")]).words  # overlapping input
    cues = build_cues(ws, max_chars=10, max_seconds=1)
    assert len(cues) == 3
    assert all(c.start <= c.end for c in cues) and all(a.end <= b.start for a, b in zip(cues, cues[1:]))
    assert build_cues([]) == []


# --- API -----------------------------------------------------------------------------------


@pytest.fixture
def fake(monkeypatch):
    calls = []

    def transcribe_words(path, language=None, on_progress=None):
        calls.append((path.read_bytes(), path.suffix, language))
        return WordTimings(language or "en", [Word(s, e, t) for s, e, t in HEARD])

    monkeypatch.setattr(engine, "transcribe_words", transcribe_words)
    return calls


def post(script="Hello there, and welcome!", data=b"audio", name="talk.mp3", **form):
    return client.post("/api/transcription/align", files={"file": (name, data, "audio/mpeg")}, data={"script": script, **form})


def test_align_returns_words_cues_and_subtitles(fake):
    r = post(language=" EN ")
    assert r.status_code == 200
    body = r.json()
    assert fake == [(b"audio", ".mp3", "en")]
    assert (body["matched"], body["total"], body["fallback"], body["language"]) == (4, 4, False, "en")
    assert body["words"][1] == {"text": "there,", "start": 0.5, "end": 0.9, "matched": True}
    assert body["cues"] == [{"start": 0.0, "end": 2.2, "text": "Hello there, and welcome!"}]
    assert body["srt"] == "1\n00:00:00,000 --> 00:00:02,200\nHello there, and welcome!\n"
    assert body["vtt"] == "WEBVTT\n\n00:00:00.000 --> 00:00:02.200\nHello there, and welcome!\n"


def test_align_respects_the_cue_limits(fake):
    cues = post(max_chars="12", max_seconds="6").json()["cues"]
    assert [c["text"] for c in cues] == ["Hello there,", "and welcome!"]


def test_temp_upload_is_removed(fake, isolated_data_dir):
    post()
    assert list((isolated_data_dir / "alignment").iterdir()) == []


@pytest.mark.parametrize("kw", [
    {"script": "  \n "}, {"language": "english"}, {"max_chars": "5"}, {"max_chars": "500"},
    {"max_seconds": "0"}, {"max_seconds": "99"}, {"data": b""}, {"script": "word " * 50_000},
])
def test_bad_input(fake, kw):
    assert post(**kw).status_code == 422 and fake == []


def test_engine_errors(monkeypatch):
    def fails(exc):
        def f(*a, **k):
            raise exc

        return f

    monkeypatch.setattr(engine, "transcribe_words", fails(AudioError("Could not decode the audio.")))
    r = post()
    assert r.status_code == 422 and r.json()["detail"] == "Could not decode the audio."
    monkeypatch.setattr(engine, "transcribe_words", fails(RuntimeError("out of memory")))
    r = post()
    assert r.status_code == 500 and r.json()["detail"] == "Alignment failed: out of memory"


def test_no_speech_heard_still_returns_estimated_cues(monkeypatch):
    monkeypatch.setattr(engine, "transcribe_words", lambda p, language=None, on_progress=None: WordTimings("en", []))
    body = post("one two three").json()
    assert body["fallback"] is True and body["matched"] == 0 and len(body["words"]) == 3 and body["cues"]


def test_engine_requests_word_timestamps(monkeypatch):
    def word(s, e, t):
        return SimpleNamespace(start=s, end=e, word=t)

    segs = [
        SimpleNamespace(start=0.0, end=2.0, words=[word(0.0, 1.0, " Hi"), word(1.0, 2.0, " "), word(1.0, 2.0, " you")]),
        SimpleNamespace(start=2.0, end=4.0, words=None),
    ]
    seen = {}

    def transcribe(path, language=None, word_timestamps=False):
        seen["word_timestamps"] = word_timestamps
        return iter(segs), SimpleNamespace(duration=4.0, language="en")

    monkeypatch.setattr(engine, "_load_model", lambda: SimpleNamespace(transcribe=transcribe))
    progress = []
    t = engine.transcribe_words(Path("x.wav"), on_progress=progress.append)
    assert seen == {"word_timestamps": True} and progress == [0.5, 1.0]
    assert [(w.start, w.end, w.text) for w in t.words] == [(0.0, 1.0, "Hi"), (1.0, 2.0, "you")] and t.language == "en"
