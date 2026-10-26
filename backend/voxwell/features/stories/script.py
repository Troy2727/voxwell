"""Story scripts: one line per utterance, written as "Speaker: what they say".

Lines without a "Speaker:" prefix are spoken by the Narrator. Blank lines are ignored.
"""

import re
from dataclasses import dataclass

NARRATOR = "Narrator"
MAX_LINES = 500
MAX_LINE_LENGTH = 1000
MAX_SPEAKERS = 20
MAX_SPEAKER_LENGTH = 40

# A speaker name is a short label before the first colon, followed by a space or the end of the
# line, e.g. "Anna: Hi" or "Old Tom:". A colon inside a word ("3:30", "https://") is not one.
_PREFIX = re.compile(rf"^\s*([^:\n]{{1,{MAX_SPEAKER_LENGTH}}}?)\s*:(\s.*|)$")


class ScriptError(ValueError):
    """The script cannot be performed; the message says why."""


@dataclass
class Line:
    speaker: str
    text: str


def _split(raw: str) -> Line:
    m = _PREFIX.match(raw)
    # The label must also look like a name (a letter, then letters, digits, spaces, . ' -), so
    # "1. Step one: go" stays narration.
    if m and re.fullmatch(r"[^\W\d_][\w .'-]*", m.group(1)):
        return Line(m.group(1).strip(), m.group(2).strip())
    return Line(NARRATOR, raw.strip())


def parse(script: str) -> list[Line]:
    lines = [_split(raw) for raw in script.splitlines() if raw.strip()]
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
