"""Transcript editing: a local language model applies a short instruction ("remove filler words") to a
transcript. The text is split on paragraph, then sentence, boundaries into chunks that fit the model;
each chunk is edited on its own, and a chunk the model fails on is kept as it was.

The model is the one AI direction uses (Qwen2.5 Instruct, Apache-2.0); see ../tools/LICENSES.md.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

CHUNK_CHARS = 1500  # about 400 tokens in, about the same out: well inside the model's context
MAX_INSTRUCTION = 500

PRESETS = {
    "filler": (
        "Remove filler words",
        "Remove filler words (um, uh, er, you know, like, I mean) and false starts. Keep every other word as it is.",
    ),
    "punctuation": (
        "Fix punctuation",
        "Fix punctuation, capitalization and spelling. Do not change, add or remove any words.",
    ),
    "formal": ("Make it formal", "Rewrite in a formal, professional tone. Keep the meaning and the facts."),
    "concise": ("Make it concise", "Tighten the wording: cut repetition and padding. Keep the meaning and the facts."),
}

SYSTEM_PROMPT = (
    "You edit transcripts of spoken audio. Apply the user's instruction to the text and reply with the edited "
    "text only: no introduction, no quotes, no notes. Stay in the text's language. Never add information that is "
    "not in the text, and never answer questions the text contains."
)

_SENTENCE_END = re.compile(r"(?<=[.!?…。！？])\s+")
_PARAGRAPH = re.compile(r"\n\s*\n")
_FENCE = re.compile(r"^```[a-z]*\n?|\n?```$", re.I)


def _hard_split(piece: str, limit: int) -> list[str]:
    """Cut a sentence that is longer than `limit` at spaces (or mid-word if it has none)."""
    parts, current = [], ""
    for word in piece.split():
        while len(word) > limit:  # no spaces to cut at
            if current:
                parts.append(current)
                current = ""
            parts.append(word[:limit])
            word = word[limit:]
        if current and len(current) + 1 + len(word) > limit:
            parts.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        parts.append(current)
    return parts


def chunk_paragraph(paragraph: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Pack whole sentences into chunks of at most `limit` characters; none is empty."""
    chunks, current = [], ""
    for sentence in (s.strip() for s in _SENTENCE_END.split(paragraph)):
        if not sentence:
            continue
        for piece in [sentence] if len(sentence) <= limit else _hard_split(sentence, limit):
            if current and len(current) + 1 + len(piece) > limit:
                chunks.append(current)
                current = piece
            else:
                current = f"{current} {piece}" if current else piece
    if current:
        chunks.append(current)
    return chunks


def chunk_text(text: str, limit: int = CHUNK_CHARS) -> list[list[str]]:
    """The text as paragraphs, each a list of chunks. Blank paragraphs are dropped."""
    paragraphs = (chunk_paragraph(p, limit) for p in _PARAGRAPH.split(text.replace("\r\n", "\n")))
    return [chunks for chunks in paragraphs if chunks]


def usable(original: str, reply: str) -> bool:
    """False for an empty, symbol-only or runaway (more than three times as long) reply."""
    return bool(re.search(r"\w", reply)) and len(reply) <= 3 * len(original) + 50


def clean_reply(reply: str) -> str:
    return " ".join(_FENCE.sub("", reply.strip()).split())


@dataclass
class Edited:
    text: str
    chunks: int
    kept: int  # chunks left as they were because the model's reply was unusable


def edit_text(text: str, instruction: str, ask: Callable[..., str] | None = None, limit: int = CHUNK_CHARS) -> Edited:
    """Apply `instruction` chunk by chunk; paragraph breaks are kept as blank lines."""
    if ask is None:
        from voxwell.features.tools import direction

        ask = direction.complete
    paragraphs, total, kept = [], 0, 0
    for chunks in chunk_text(text, limit):
        out = []
        for chunk in chunks:
            total += 1
            # A token per character: CJK text needs about that, and the model stops at the end of
            # its answer anyway, so a generous cap never cuts an edited chunk short.
            reply = clean_reply(ask(SYSTEM_PROMPT, f"Instruction: {instruction}\n\nText:\n{chunk}", max_new_tokens=len(chunk) + 64))
            if usable(chunk, reply):
                out.append(reply)
            else:
                out.append(chunk)
                kept += 1
        paragraphs.append(" ".join(out))
    return Edited("\n\n".join(paragraphs), total, kept)
