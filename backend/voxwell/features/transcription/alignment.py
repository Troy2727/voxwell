"""Forced alignment: give every word of a known script a time, using the words a speech recognizer
heard in the recording. No model lives here; the recognizer's word timings come in as plain data.

Script words and heard words are compared in a normalized form (case, accents and punctuation
ignored) with a sequence alignment. A script word the recognizer got right takes its timing; a run
of script words with no match gets times spread between the neighbouring matched words. The timings
are then turned into subtitle cues.
"""

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

SECONDS_PER_WORD = 0.4  # for words with no timing evidence at all
SENTENCE_END = re.compile(r"[.!?…。！？][\"'”’)\]]*$")


@dataclass
class AlignedWord:
    text: str  # as written in the script
    start: float
    end: float
    matched: bool  # False when the time was interpolated


@dataclass
class Cue:
    start: float
    end: float
    text: str


@dataclass
class Alignment:
    words: list[AlignedWord]
    matched: int
    fallback: bool  # nothing matched, so every time is an estimate


def normalize(word: str) -> str:
    """Lowercase letters and digits only, accents removed: 'Café,' -> 'cafe'."""
    decomposed = unicodedata.normalize("NFKD", word.casefold())
    return "".join(c for c in decomposed if unicodedata.category(c)[0] in "LN")


def script_words(script: str) -> list[str]:
    """The script's words with their punctuation. A token with no letter or digit ('—') joins the word before it."""
    words: list[str] = []
    pending = ""
    for token in script.split():
        if normalize(token):
            words.append(f"{pending} {token}".strip() if pending else token)
            pending = ""
        elif words:
            words[-1] += f" {token}"
        else:
            pending = f"{pending} {token}".strip()
    return words


def _spread(keys: list[str], start: float, end: float) -> list[tuple[float, float]]:
    """Split [start, end] over words in proportion to their length."""
    weights = [max(len(k), 1) for k in keys]
    total, at, out = sum(weights), start, []
    for w in weights:
        nxt = at + (end - start) * w / total
        out.append((at, nxt))
        at = nxt
    return out


def align(script: str, heard: list[tuple[float, float, str]]) -> Alignment:
    """Time each script word. `heard` is the recognizer's (start, end, word) list in order."""
    words = script_words(script)
    keys = [normalize(w) for w in words]
    heard = [(a, b, w) for a, b, w in heard if normalize(w)]
    heard_keys = [normalize(w) for _, _, w in heard]
    times: list[tuple[float, float] | None] = [None] * len(words)

    for op, i1, i2, j1, j2 in SequenceMatcher(None, keys, heard_keys, autojunk=False).get_opcodes():
        # Equal runs are matches; so are same-size replacements (a misheard word still marks the spot).
        if op == "equal" or (op == "replace" and i2 - i1 == j2 - j1):
            for k in range(i2 - i1):
                times[i1 + k] = (heard[j1 + k][0], heard[j1 + k][1])

    found = [t is not None for t in times]
    matched = sum(found)
    if matched == 0:
        start, end = (heard[0][0], heard[-1][1]) if heard else (0.0, 0.0)
        if end <= start:
            end = start + SECONDS_PER_WORD * len(words)
        times = list(_spread(keys, start, end))
    else:
        i = 0
        while i < len(times):  # fill each run of unmatched words from its neighbours
            if times[i] is not None:
                i += 1
                continue
            j = i
            while j < len(times) and times[j] is None:
                j += 1
            run = j - i
            before = times[i - 1][1] if i > 0 else None
            after = times[j][0] if j < len(times) else None
            if before is None:
                before = max(after - SECONDS_PER_WORD * run, 0.0)
            if after is None:
                after = before + SECONDS_PER_WORD * run
            times[i:j] = _spread(keys[i:j], before, max(after, before))
            i = j

    out, last_start = [], 0.0
    for word, (start, end), exact in zip(words, times, found):
        start = max(start, last_start)  # never run backwards
        out.append(AlignedWord(word, round(start, 3), round(max(end, start), 3), exact))
        last_start = start
    return Alignment(out, matched, fallback=matched == 0)


def build_cues(words: list[AlignedWord], max_chars: int = 42, max_seconds: float = 6.0, max_gap: float = 1.0) -> list[Cue]:
    """Group words into one-line subtitle cues. A cue ends at `max_chars`, at `max_seconds` of speech,
    at a pause longer than `max_gap`, or at the end of a sentence once it holds a few words."""
    cues: list[Cue] = []
    current: list[AlignedWord] = []

    def flush():
        if current:
            cues.append(Cue(current[0].start, current[-1].end, " ".join(w.text for w in current)))
            current.clear()

    for w in words:
        if current:
            text_length = sum(len(x.text) + 1 for x in current) + len(w.text)
            if text_length > max_chars or w.end - current[0].start > max_seconds or w.start - current[-1].end > max_gap:
                flush()
        current.append(w)
        if SENTENCE_END.search(w.text) and sum(len(x.text) + 1 for x in current) >= max_chars // 3:
            flush()
    flush()
    for cue, following in zip(cues, cues[1:]):  # cues never overlap
        cue.end = max(min(cue.end, following.start), cue.start)
    return cues
