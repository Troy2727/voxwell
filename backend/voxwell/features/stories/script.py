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
MAX_JOINED_LENGTH = 250  # characters; longer pieces make the model drift (the Audiobook chunk size too)

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


@dataclass
class Joined:
    script: str
    joined: int  # lines merged into the line before them
    too_long: int  # pairs left apart because together they'd pass MAX_JOINED_LENGTH
    line: int  # 1-based: the first line that changed, or first_line when none did


def join_lines(script: str, first_line: int, last_line: int) -> Joined:
    """Join lines: merge neighbouring lines of one speaker within raw lines first_line..last_line.

    The words of a later line go after its neighbour's, one space between, and its label is
    dropped; the first line of a run keeps its form. A blank line, a line with no words or a
    different speaker ends a run, and a pair whose words would pass MAX_JOINED_LENGTH stays apart.
    Lines outside the range are untouched. Joined lines are spoken as one clip, with no gap.
    """
    # Only line breaks the page can count too (splitlines would also split on rarer separators).
    raw = script.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if raw and raw[-1] == "":
        raw.pop()
    if not 1 <= first_line <= last_line <= len(raw):
        raise ScriptError("Pick lines inside the script.")
    out = raw[: first_line - 1]
    joined = too_long = 0
    changed = None
    run: Line | None = None  # the previous line in the range, while a next one may join it
    for text in raw[first_line - 1 : last_line]:
        line = _split(text) if text.strip() else None
        if run and line and line.text and line.speaker == run.speaker:
            if len(run.text) + 1 + len(line.text) > MAX_JOINED_LENGTH:
                too_long += 1
            else:
                out[-1] = f"{out[-1].rstrip()} {line.text}"
                run = Line(run.speaker, f"{run.text} {line.text}")
                joined += 1
                changed = changed or len(out)
                continue
        out.append(text)
        run = line if line and line.text else None
    out += raw[last_line:]
    ending = "\n" if script.endswith(("\n", "\r")) else ""
    return Joined("\n".join(out) + ending, joined, too_long, changed or first_line)
