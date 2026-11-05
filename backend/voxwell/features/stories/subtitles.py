"""Speech from a subtitle file: parse SRT, then put each spoken cue at its start time.

A cue that runs longer than its time is sped up, like dubbing does. If it still doesn't fit, it
carries on and pushes the next cue later rather than cutting off words.
"""

import re
from dataclasses import dataclass

from voxwell.features.audio_effects.dsp import Effects, decode, encode_wav, process
from voxwell.features.dubbing.fitting import tempo_for
from voxwell.features.stories.script import MAX_LINE_LENGTH, MAX_LINES, ScriptError

_TIMES = re.compile(r"(\d{1,3}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,3}):(\d{2}):(\d{2})[,.](\d{1,3})")
_MARKUP = re.compile(r"<[^>]*>|\{\\[^}]*\}")  # <i>...</i> and {\an8}


@dataclass
class Cue:
    start: float  # seconds
    end: float
    text: str


def _seconds(hours: str, minutes: str, seconds: str, millis: str) -> float:
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis.ljust(3, "0")) / 1000


def parse(text: str) -> list[Cue]:
    """The spoken cues of an SRT file, in time order; ScriptError if there are none or too many."""
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = block.split("\n")
        at = next((i for i, line in enumerate(lines[:2]) if _TIMES.search(line)), None)
        if at is None:
            continue
        times = _TIMES.search(lines[at]).groups()
        spoken = " ".join(_MARKUP.sub("", " ".join(lines[at + 1 :])).split())
        if spoken:
            cues.append(Cue(_seconds(*times[:4]), _seconds(*times[4:]), spoken))
    if not cues:
        raise ScriptError("No subtitles were found. Use an SRT file.")
    if len(cues) > MAX_LINES:
        raise ScriptError(f"The file has too many subtitles ({MAX_LINES} max).")
    for i, cue in enumerate(cues, 1):
        if len(cue.text) > MAX_LINE_LENGTH:
            raise ScriptError(f"Subtitle {i} is too long ({MAX_LINE_LENGTH} characters max).")
    return sorted(cues, key=lambda cue: cue.start)


def place(cues: list[Cue], clips: list[bytes]) -> bytes:
    """One WAV with each cue's clip (16-bit mono WAV, one sample rate) at its time."""
    import numpy as np

    rate = None
    placed = []
    cursor = 0.0
    for cue, clip in zip(cues, clips, strict=True):
        audio, rate = decode(clip)
        seconds = len(audio) / rate
        start = max(cue.start, cursor)
        tempo = tempo_for(seconds, cue.end - start)
        if tempo != 1:
            audio = process(audio, rate, Effects(speed=tempo))
        placed.append((int(start * rate), audio))
        cursor = start + len(audio) / rate
    track = np.zeros(max(offset + len(audio) for offset, audio in placed))
    for offset, audio in placed:
        track[offset : offset + len(audio)] = audio
    return encode_wav(track, rate)
