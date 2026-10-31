"""Pronunciation dictionaries: per-language words and how to respell them for the speech model.

Entries live in one JSON file per language under data_dir("pronunciation"). apply() rewrites a
text before it reaches the model; voice_cloning.engine.synthesize() calls it, so every path that
makes speech (cloning, stories, audiobook, dubbing, tools, the OpenAI-compatible API) gets it.
"""

import json
import os
import re
import threading
import uuid
from dataclasses import asdict, dataclass

from voxwell.paths import child_path, data_dir

MAX_WORD = 100
MAX_RESPELLING = 200
MAX_ENTRIES = 2000

_LANGUAGE = re.compile(r"^[a-z]{2,3}$")
_lock = threading.Lock()


class DuplicateWord(Exception):
    """The word already has an entry."""


@dataclass
class Entry:
    id: str
    word: str
    respelling: str
    case_sensitive: bool = False
    whole_word: bool = True


def _path(language: str):
    if not _LANGUAGE.match(language):  # the language names a file, so never trust it as a path
        raise ValueError(f"Invalid language '{language}'.")
    return child_path(data_dir("pronunciation"), f"{language}.json")


def list_entries(language: str) -> list[Entry]:
    path = _path(language)
    if not path.exists():
        return []
    try:
        return [Entry(**item) for item in json.loads(path.read_text(encoding="utf-8"))]
    except (ValueError, TypeError):
        return []


def _save(language: str, entries: list[Entry]) -> None:
    path = _path(language)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps([asdict(e) for e in entries], ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _clean(word: str, respelling: str) -> tuple[str, str]:
    word, respelling = word.strip(), respelling.strip()
    if not word:
        raise ValueError("Word is required.")
    if not respelling:
        raise ValueError("Respelling is required.")
    if len(word) > MAX_WORD:
        raise ValueError(f"Word is too long ({MAX_WORD} characters max).")
    if len(respelling) > MAX_RESPELLING:
        raise ValueError(f"Respelling is too long ({MAX_RESPELLING} characters max).")
    return word, respelling


def _same_word(entry: Entry, word: str, case_sensitive: bool) -> bool:
    if entry.case_sensitive and case_sensitive:
        return entry.word == word
    return entry.word.lower() == word.lower()


def add_entry(language: str, word: str, respelling: str, case_sensitive: bool = False, whole_word: bool = True) -> Entry:
    """Raises ValueError for invalid input and DuplicateWord when the word already has an entry."""
    word, respelling = _clean(word, respelling)
    with _lock:
        entries = list_entries(language)
        if len(entries) >= MAX_ENTRIES:
            raise ValueError(f"Too many entries ({MAX_ENTRIES} max per language).")
        if any(_same_word(e, word, case_sensitive) for e in entries):
            raise DuplicateWord(word)
        entry = Entry(uuid.uuid4().hex, word, respelling, case_sensitive, whole_word)
        _save(language, [*entries, entry])
        return entry


def update_entry(language: str, entry_id: str, word: str, respelling: str, case_sensitive: bool, whole_word: bool) -> Entry:
    """Raises ValueError for invalid input, LookupError for an unknown id, DuplicateWord for a duplicate word."""
    word, respelling = _clean(word, respelling)
    with _lock:
        entries = list_entries(language)
        target = next((e for e in entries if e.id == entry_id), None)
        if target is None:
            raise LookupError(entry_id)
        if any(e.id != entry_id and _same_word(e, word, case_sensitive) for e in entries):
            raise DuplicateWord(word)
        target.word, target.respelling = word, respelling
        target.case_sensitive, target.whole_word = case_sensitive, whole_word
        _save(language, entries)
        return target


def delete_entry(language: str, entry_id: str) -> None:
    """Raises LookupError for an unknown id."""
    with _lock:
        entries = list_entries(language)
        kept = [e for e in entries if e.id != entry_id]
        if len(kept) == len(entries):
            raise LookupError(entry_id)
        _save(language, kept)


def _pattern(entry: Entry) -> re.Pattern:
    body = re.escape(entry.word)
    if entry.whole_word:
        body = rf"(?<!\w){body}(?!\w)"
    return re.compile(body, 0 if entry.case_sensitive else re.IGNORECASE)


def rewrite(text: str, entries: list[Entry]) -> str:
    """Replace each entry's word in `text` by its respelling.

    Matching is one pass over the original text: where matches overlap the longest word wins
    (then the earliest), and a respelling is never searched again, so entries cannot alter each
    other's output.
    """
    found: list[tuple[int, int, str]] = []
    for entry in entries:
        found.extend((m.start(), m.end(), entry.respelling) for m in _pattern(entry).finditer(text))
    found.sort(key=lambda f: (-(f[1] - f[0]), f[0]))
    taken: list[tuple[int, int, str]] = []
    for start, end, respelling in found:
        if all(end <= s or start >= e for s, e, _ in taken):
            taken.append((start, end, respelling))
    out, pos = [], 0
    for start, end, respelling in sorted(taken):
        out += [text[pos:start], respelling]
        pos = end
    out.append(text[pos:])
    return "".join(out)


def apply(text: str, language: str) -> str:
    """`text` rewritten with the language's dictionary (unchanged when there are no entries)."""
    entries = list_entries(language)
    return rewrite(text, entries) if entries else text
