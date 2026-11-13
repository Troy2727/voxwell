"""Cue tags: bracketed words such as "[laugh]" that the voice acts out instead of reading aloud.

The vocabulary is the one Chatterbox-Turbo defines as dedicated tokens; Turbo is English only, so
cues are voiced in English and removed everywhere else. Pure functions; no torch import.
"""

import re

# The Turbo tags, grouped for the Cues picker: (group label, tags).
GROUPS: list[tuple[str, list[str]]] = [
    ("Sounds", ["laugh", "chuckle", "sigh", "gasp", "cough", "clear throat", "sniff", "groan", "shush"]),
    ("Feelings and delivery", ["happy", "angry", "sarcastic", "surprised", "fear", "crying", "whispering"]),
    ("Style", ["narration", "dramatic", "advertisement"]),
]
VOCABULARY = frozenset(tag for _, tags in GROUPS for tag in tags)

# Languages where cues are voiced. Elsewhere STRIP_OUTSIDE_VOICED decides; it ships True (removed).
# Setting it False is not enough on its own: Multilingual names its sound tokens differently.
VOICED_LANGUAGES = ["en"]
STRIP_OUTSIDE_VOICED = True

# Sound-event tokens in Chatterbox Multilingual's tokenizer that Turbo does not define. Either
# model could voice or garble them unpredictably, so they are always removed.
RESERVED = frozenset({
    "bark", "chew", "clear_throat", "cry", "exhale", "gibberish", "giggle", "guffaw", "howl",
    "humming", "inhale", "kiss", "laughter", "meow", "mumble", "music", "shhh", "singing", "sip",
    "sneeze", "snore", "whisper", "whistle",
})

_BRACKET = re.compile(r"\[([^\[\]]*)\]")
_CLOSING = set(",.;:!?)]}…\"'”’")
_OPENING = set("([{\"'“‘")


def _key(inside: str) -> str:
    """Bracket content as compared: lowercase, whitespace runs collapsed, trimmed."""
    return " ".join(inside.split()).lower()


def find(text: str) -> list[str]:
    """The known cue tags in `text`, in order, in canonical form ("[clear throat]")."""
    return [f"[{_key(m[1])}]" for m in _BRACKET.finditer(text) if _key(m[1]) in VOCABULARY]


def spans(text: str) -> list[tuple[int, int]]:
    """(start, end) of each known cue tag in `text`."""
    return [m.span() for m in _BRACKET.finditer(text) if _key(m[1]) in VOCABULARY]


def canonical(text: str) -> str:
    """`text` with each known cue tag rewritten to lowercase, single-spaced form."""
    return _BRACKET.sub(lambda m: f"[{_key(m[1])}]" if _key(m[1]) in VOCABULARY else m[0], text)


def _strip(text: str, names: frozenset[str]) -> str:
    """Remove the bracket tags named in `names` with the spaces around them."""

    # The tag is found by itself and the spaces around it are stepped over by hand: a regex with
    # optional spaces before the bracket would be quadratic on long runs of spaces.
    out, pos = [], 0
    for m in _BRACKET.finditer(text):
        if _key(m[1]) not in names:
            continue
        start, end = m.start(), m.end()
        while start > pos and text[start - 1] in " \t":
            start -= 1
        while end < len(text) and text[end] in " \t":
            end += 1
        before = text[start - 1] if start > 0 else ""
        after = text[end] if end < len(text) else ""
        # One space between two words ("word[laugh]word" -> "word word"); none at an edge or before punctuation.
        between_words = before and not before.isspace() and after and not after.isspace()
        out += [text[pos:start], " " if between_words and after not in _CLOSING and before not in _OPENING else ""]
        pos = end
    out.append(text[pos:])
    return "".join(out)


def strip_known(text: str) -> str:
    """`text` without its known cue tags ("Well [sigh], ok." -> "Well, ok.")."""
    return _strip(text, VOCABULARY)


def strip_reserved(text: str) -> str:
    """`text` without the reserved sound-event tokens; every other bracket text stays."""
    return _strip(text, RESERVED)


def has_speech(text: str) -> bool:
    """Whether `text` still has a letter or digit once its known cue tags are removed."""
    return any(c.isalnum() for c in strip_known(text))


def status() -> dict:
    """The cue facts the page and clients need, minus availability (the engine knows that)."""
    return {
        "languages": VOICED_LANGUAGES,
        "groups": [{"label": label, "tags": [{"tag": t, "label": t.capitalize()} for t in tags]} for label, tags in GROUPS],
    }
