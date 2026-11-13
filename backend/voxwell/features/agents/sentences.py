"""Flow replies: cut a reply into sentences while the model is still writing it.

feed() takes text in any pieces and returns the sentences it knows are complete; finish() returns
the rest. Fed the same text in any piece sizes, the sentences come out the same. A sentence shorter
than MIN_CHARS waits to be joined with the next one (the speech model clips and loops on tiny
inputs), and none is longer than MAX_CHARS (it drifts on long ones).
"""

from voxwell.features.audiobook.chunking import MAX_CHARS

MIN_CHARS = 20

# Words that end in "." without ending a sentence (lowercase, without the dot). Data: extend freely.
ABBREVIATIONS = frozenset(
    "mr mrs ms dr prof st sr jr vs etc approx fig vol cf "  # English and Latin
    "sra sres srta dra ud uds pág "  # Spanish
    "mme mlle mm "  # French
    "hr frau nr bzw usw "  # German
    "sig sigg dott ecc "  # Italian
    .split()
)
_TERMINATORS = ".!?…"
_FULL_WIDTH = "。！？"
_CLOSERS = "\"'”’)]}»」』"


def _tidy(text: str) -> str:
    return " ".join(text.split())


def _ends_sentence(buf: str, dot: int) -> bool:
    """Whether the single "." at `dot` (followed by whitespace) ends a sentence."""
    before = buf[:dot].split()
    word = before[-1].lstrip("(\"'«“‘[{") if before else ""
    if word.lower() in ABBREVIATIONS:
        return False
    if len(word) == 1 and word.isupper():  # an initial: J. Smith
        return False
    return "." not in word  # a dotted token: U.S.A., e.g.


def _boundary(buf: str, final: bool) -> int | None:
    """The end of the first complete sentence in `buf`, or None while it can't be known yet."""
    i, n = 0, len(buf)
    while i < n:
        c = buf[i]
        if c == "\n":  # a blank line ends a paragraph, and so a sentence
            k = i + 1
            while k < n and buf[k] in " \t":
                k += 1
            if k < n and buf[k] == "\n" and buf[:i].strip():
                return i
        if c in _FULL_WIDTH:
            j = i + 1
            while j < n and buf[j] in _CLOSERS:
                j += 1
            return j
        if c in _TERMINATORS:
            j = i
            while j < n and buf[j] in _TERMINATORS:
                j += 1
            run = buf[i:j]
            while j < n and buf[j] in _CLOSERS:
                j += 1
            if j == n:  # nothing after it yet: wait, unless no more text can come into this sentence
                full = n >= MAX_CHARS and (run != "." or _ends_sentence(buf, i))
                return j if (final or full) and buf[:i].strip() else None
            if buf[j].isspace() and (run != "." or _ends_sentence(buf, i)):
                return j
            i = j
            continue
        i += 1
    return None


def _cut(buf: str) -> int:
    """Where to cut a buffer that reached MAX_CHARS with no sentence end: after a , ; or :, else a space."""
    head = buf[:MAX_CHARS]
    mark = max(head.rfind(","), head.rfind(";"), head.rfind(":"))
    if mark > 0:
        return mark + 1
    space = head.rfind(" ")
    return space if space > 0 else MAX_CHARS


class SentenceSplitter:
    def __init__(self):
        self._buf = ""
        self._waiting = ""  # a sentence too short to send alone

    def feed(self, text: str) -> list[str]:
        self._buf += text
        return self._take(final=False)

    def finish(self) -> list[str]:
        out = self._take(final=True)
        rest = _tidy(self._buf)
        self._buf = ""
        if rest:
            out += self._send(rest)
        if self._waiting:
            out.append(self._waiting)
            self._waiting = ""
        return out

    def _take(self, final: bool) -> list[str]:
        out = []
        while True:
            end = _boundary(self._buf, final)
            if end is not None and end <= MAX_CHARS:
                sentence, self._buf = self._buf[:end], self._buf[end:].lstrip()
            elif len(self._buf) >= MAX_CHARS:
                cut = _cut(self._buf)
                sentence, self._buf = self._buf[:cut], self._buf[cut:].lstrip()
            else:
                return out
            if sentence := _tidy(sentence):
                out += self._send(sentence)

    def _send(self, sentence: str) -> list[str]:
        """The sentence, joined to a waiting short one; nothing while the result is still too short."""
        if self._waiting:
            joined = f"{self._waiting} {sentence}"
            if len(joined) > MAX_CHARS:  # too long together: the short one goes alone
                waiting, self._waiting = self._waiting, ""
                return [waiting, *self._send(sentence)]
            self._waiting, sentence = "", joined
        if len(sentence) < MIN_CHARS:
            self._waiting = sentence
            return []
        return [sentence]
