"""Write song lyrics from a description with the local language model that AI direction uses."""

import re

from voxwell.features.tools import direction

SYSTEM_PROMPT = """You are a songwriter. Write original lyrics for the song the user describes.
Mark every section with a tag on its own line: [Verse 1], [Pre-Chorus], [Chorus], [Verse 2], [Bridge], [Outro].
Use about 4 short lines per section and repeat the chorus. Reply with the lyrics only: no title, no notes."""

MAX_NEW_TOKENS = 400
_TAG = re.compile(r"^\[[^\]\n]{1,30}\]$", re.M)


class LyricsError(ValueError):
    """The model's answer could not be used."""


def clean(reply: str) -> str:
    """Strip code fences and chatter before the first section tag; keep the lyrics."""
    text = reply.replace("```", "").strip()
    first = _TAG.search(text)
    if not first:
        raise LyricsError("The AI did not write usable lyrics. Try describing the song differently.")
    lines = [line.rstrip() for line in text[first.start():].splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def write(description: str, language: str) -> str:
    return clean(direction.complete(SYSTEM_PROMPT, f"Language: {language}\nSong: {description}", MAX_NEW_TOKENS))
