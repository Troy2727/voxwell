"""Story scripts: one line per utterance, written as "Speaker: what they say".

Lines without a "Speaker:" prefix are spoken by the Narrator. Blank lines are ignored.

Line moods: a line's text may start with "[mood NAME]" (after the speaker label), e.g.
"Anna: [mood dramatic] Get out." The marker is not spoken; it sets how strongly the whole line is
delivered (the speech model's exaggeration), from MOODS.
"""

import re
from dataclasses import dataclass

NARRATOR = "Narrator"
MAX_LINES = 500
MAX_LINE_LENGTH = 1000
MAX_SPEAKERS = 20
MAX_SPEAKER_LENGTH = 40

# Line moods, quietest to strongest: the exaggeration each one gives the speech model. neutral is the
# model's normal delivery. First guesses, to be tuned by ear.
MOODS = {"calm": 0.3, "neutral": 0.5, "lively": 0.8, "dramatic": 1.2, "intense": 1.6}
# "[mood NAME]", any case and spacing; "[moods]" or "[mood-board]" is ordinary text.
_MOOD = re.compile(r"\[\s*mood(?:\s+([^\]]*?))?\s*\]", re.IGNORECASE)

# A speaker name is a short label before the first colon, followed by a space or the end of the
# line, e.g. "Anna: Hi" or "Old Tom:". A colon inside a word ("3:30", "https://") is not one.
_PREFIX = re.compile(rf"^\s*([^:\n]{{1,{MAX_SPEAKER_LENGTH}}}?)\s*:(\s.*|)$")


class ScriptError(ValueError):
    """The script cannot be performed; the message says why."""


@dataclass
class Line:
    speaker: str
    text: str
    mood: str | None = None  # a name from MOODS


def _split(raw: str) -> Line:
    m = _PREFIX.match(raw)
    # The label must also look like a name (a letter, then letters, digits, spaces, . ' -), so
    # "1. Step one: go" stays narration.
    if m and re.fullmatch(r"[^\W\d_][\w .'-]*", m.group(1)):
        return Line(m.group(1).strip(), m.group(2).strip())
    return Line(NARRATOR, raw.strip())


def _mood_names() -> str:
    names = list(MOODS)
    return f"{', '.join(names[:-1])} or {names[-1]}"


def _with_mood(line: Line, number: int) -> Line:
    """`line` with its mood marker taken off the text; `number` is its line in the script, for errors."""
    found = list(_MOOD.finditer(line.text))
    if not found:
        return line
    if found[0].start() != 0 or len(found) > 1:
        raise ScriptError(f"Line {number}: put the mood at the start of the line, right after the speaker.")
    name = (found[0].group(1) or "").strip()
    if not name:
        raise ScriptError(f"Line {number} has a mood with no name. Use {_mood_names()}.")
    if name.lower() not in MOODS:
        raise ScriptError(f"Line {number} has an unknown mood '{name}'. Use {_mood_names()}.")
    return Line(line.speaker, line.text[found[0].end() :].strip(), name.lower())


def parse(script: str) -> list[Line]:
    lines = [_with_mood(_split(raw), number) for number, raw in enumerate(script.splitlines(), 1) if raw.strip()]
    lines = [line for line in lines if line.text]
    if not lines:
        raise ScriptError("The script is empty.")
    if len(lines) > MAX_LINES:
        raise ScriptError(f"The script is too long ({MAX_LINES} lines max).")
    for i, line in enumerate(lines, 1):
        if len(line.text) > MAX_LINE_LENGTH:
            raise ScriptError(f"Line {i} is too long ({MAX_LINE_LENGTH} characters max).")
    if len(speakers(lines)) > MAX_SPEAKERS:
        raise ScriptError(f"Too many speakers ({MAX_SPEAKERS} max).")
    return lines


def speakers(lines: list[Line]) -> list[str]:
    """Speakers in order of first appearance."""
    return list(dict.fromkeys(line.speaker for line in lines))
