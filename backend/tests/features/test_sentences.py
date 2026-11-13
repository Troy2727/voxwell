import random

import pytest

from voxwell.features.agents import sentences
from voxwell.features.agents.sentences import MAX_CHARS, SentenceSplitter


def split(text: str, pieces=None) -> list[str]:
    """All sentences of `text`, fed whole or in the given piece sizes."""
    s, out, i = SentenceSplitter(), [], 0
    for size in pieces or [len(text)]:
        out += s.feed(text[i : i + size])
        i += size
    return out + s.feed(text[i:]) + s.finish()


@pytest.fixture
def no_min(monkeypatch):
    monkeypatch.setattr(sentences, "MIN_CHARS", 0)


LONG = "This is a first sentence of decent length. And here is another one, also long enough! Is this the third one?"


def test_any_piece_sizes_give_the_same_sentences():
    whole = split(LONG)
    assert split(LONG, [1] * len(LONG)) == whole
    rng = random.Random(3)
    for _ in range(50):
        assert split(LONG, [rng.randint(1, 9) for _ in range(40)]) == whole
    assert len(whole) == 3


def test_sentence_ends(no_min):
    assert split("Hello there. How are you? Fine!") == ["Hello there.", "How are you?", "Fine!"]
    s = SentenceSplitter()
    assert s.feed("All done.") == [] and s.finish() == ["All done."]  # a final "." waits for what follows
    assert split('He said "go." Then left.') == ['He said "go."', "Then left."]
    assert split("你好。今天怎么样？") == ["你好。", "今天怎么样？"]
    assert split("First line\n\nSecond paragraph") == ["First line", "Second paragraph"]
    # An ellipsis followed by a space ends a sentence like any other terminator.
    assert split("Wait... really?") == ["Wait...", "really?"]


@pytest.mark.parametrize("text", ["pi is 3.14 today", "Dr. Smith is here", "J. R. Smith left", "visit example.com now", "the U.S.A. is big", "cats, dogs, etc. are pets"])
def test_no_split_inside(no_min, text):
    assert split(text) == [text]


def test_a_number_before_a_full_stop_still_ends_it(no_min):
    assert split("It costs 5. Then more.") == ["It costs 5.", "Then more."]


def test_short_sentences_are_joined():
    assert split("Yes. I can help you with that today.") == ["Yes. I can help you with that today."]
    assert split("Okay.") == ["Okay."]
    assert split("This sentence is long enough to stand. Okay.") == ["This sentence is long enough to stand.", "Okay."]


def test_pieces_never_exceed_the_maximum():
    with_commas = ", ".join(["some words here"] * 40)
    no_spaces = "x" * 600
    for text in (with_commas, no_spaces):
        out = split(text)
        assert all(len(p) <= MAX_CHARS for p in out)
    assert " ".join(split(with_commas)) == with_commas
    assert "".join(split(no_spaces)) == no_spaces  # cut inside the one long word, so no space to restore
    assert split("   \n  ") == []


def test_no_loss_duplication_or_oversize():
    rng = random.Random(11)
    alphabet = "abcdefgh      12345.!?,"
    for _ in range(300):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 700)))
        out = split(text, [rng.randint(1, 30) for _ in range(60)])
        assert all(0 < len(p) <= MAX_CHARS for p in out)
        assert " ".join(out).replace(" ", "") == text.replace(" ", "")


def test_a_full_buffer_ending_a_sentence_splits_as_whole_text_does():
    long = "word " * 49 + "ends."  # MAX_CHARS long, ending in a full stop
    assert len(long) == MAX_CHARS
    text = long + " Next sentence is here and long enough."
    assert split(text, [MAX_CHARS, 5]) == split(text) == [long, "Next sentence is here and long enough."]


def test_no_and_ca_are_ordinary_words(no_min):
    assert split("I said no. Then I left.") == ["I said no.", "Then I left."]
