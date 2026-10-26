"""Split chapter text into chunks short enough for the speech model to read well."""

import re

MAX_CHARS = 250  # Chatterbox drifts on long inputs; a sentence or two at a time sounds best
MIN_STANDALONE = 40  # shorter paragraphs are joined to the next one (see chapter_chunks)

# A sentence ends at . ! ? or … (optionally followed by one closing quote/bracket) and a space.
# Split on the space only, so no text is lost. Abbreviations ("Mr. Smith") may split, but short
# pieces are merged back together below.
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+|(?<=[.!?…][\"'”’)\]])\s+")


def _split_long(sentence: str) -> list[str]:
    """Break an over-long sentence at commas/semicolons, then at spaces, into <= MAX_CHARS."""
    pieces, current = [], ""
    for part in re.split(r"(?<=[,;:])\s+", sentence):
        while len(part) > MAX_CHARS:  # no punctuation to break on: cut at the last space
            cut = part.rfind(" ", 0, MAX_CHARS)
            cut = cut if cut > 0 else MAX_CHARS
            if current:
                pieces.append(current)
                current = ""
            pieces.append(part[:cut].strip())
            part = part[cut:].strip()
        if current and len(current) + 1 + len(part) > MAX_CHARS:
            pieces.append(current)
            current = part
        else:
            current = f"{current} {part}".strip()
    if current:
        pieces.append(current)
    return pieces


def chunks(paragraph: str) -> list[str]:
    """Sentences of one paragraph, merged while they fit in MAX_CHARS."""
    out, current = [], ""
    for sentence in _SENTENCE_END.split(paragraph.strip()):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > MAX_CHARS:
            if current:
                out.append(current)
                current = ""
            out.extend(_split_long(sentence))
        elif current and len(current) + 1 + len(sentence) > MAX_CHARS:
            out.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        out.append(current)
    return out


def chapter_chunks(text: str) -> list[list[str]]:
    """Chunks for each paragraph of a chapter (paragraphs are separated by blank lines).

    A very short paragraph (usually a heading such as "The Ship") is spoken together with the
    next one: on its own, Chatterbox tends to loop or ramble on title-like phrases ("The ship.
    The ship."), and no generation setting prevents it reliably.
    """
    merged, carry = [], ""
    for paragraph in (p.strip() for p in text.split("\n\n")):
        if not paragraph:
            continue
        if carry:
            paragraph = f"{carry} {paragraph}"
            carry = ""
        if len(paragraph) < MIN_STANDALONE:
            carry = paragraph if paragraph[-1] in ".!?…:;" else paragraph + "."
        else:
            merged.append(paragraph)
    if carry:  # a short last paragraph has nothing to join; speak it as it is
        merged.append(carry)
    return [c for c in (chunks(p) for p in merged) if c]
