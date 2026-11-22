"""Pronunciation dictionaries: words and how to respell them for the speech model.

Entries live in one JSON file per language under data_dir("pronunciation"), plus shared.json for the
words that apply in every language (Shared words, the scope ALL), plus voices/<voice id>.<language>.json
for the words of one saved voice (Voice pronunciation), which win when that voice speaks. apply() rewrites a
text before it reaches the model; voice_cloning.engine.synthesize() calls it, so every path that
makes speech (cloning, stories, audiobook, dubbing, tools, the OpenAI-compatible API) gets it.
"""

import json
import re
import threading
import uuid
from dataclasses import asdict, dataclass

from voxwell.paths import child_path, data_dir, replace_file

MAX_WORD = 100
MAX_RESPELLING = 200
MAX_ENTRIES = 2000

_LANGUAGE = re.compile(r"^[a-z]{2,3}$")
_VOICE = re.compile(r"^[0-9a-f]{12}$")  # a saved voice's id, as voxwell.voices makes them
ALL = "all"  # the scope of the shared list; not a language
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


def _path(language: str, voice_id: str | None = None):
    if voice_id:
        if not _VOICE.match(voice_id) or not _LANGUAGE.match(language):  # both name the file
            raise ValueError("Voice words need a saved voice and a language.")
        return child_path(data_dir("pronunciation", "voices"), f"{voice_id}.{language}.json")
    if language == ALL:
        return child_path(data_dir("pronunciation"), "shared.json")
    if not _LANGUAGE.match(language):  # the language names a file, so never trust it as a path
        raise ValueError(f"Invalid language '{language}'.")
    return child_path(data_dir("pronunciation"), f"{language}.json")


def list_entries(language: str, voice_id: str | None = None) -> list[Entry]:
    path = _path(language, voice_id)
    if not path.exists():
        return []
    try:
        return [Entry(**item) for item in json.loads(path.read_text(encoding="utf-8"))]
    except (ValueError, TypeError):
        return []


def _save(language: str, entries: list[Entry], voice_id: str | None = None) -> None:
    path = _path(language, voice_id)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps([asdict(e) for e in entries], ensure_ascii=False, indent=2), encoding="utf-8")
    replace_file(tmp, path)


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


def add_entry(language: str, word: str, respelling: str, case_sensitive: bool = False, whole_word: bool = True, voice_id: str | None = None) -> Entry:
    """Raises ValueError for invalid input and DuplicateWord when the word already has an entry in that list."""
    word, respelling = _clean(word, respelling)
    with _lock:
        entries = list_entries(language, voice_id)
        if len(entries) >= MAX_ENTRIES:
            raise ValueError(f"Too many entries ({MAX_ENTRIES} max per list).")
        if any(_same_word(e, word, case_sensitive) for e in entries):
            raise DuplicateWord(word)
        entry = Entry(uuid.uuid4().hex, word, respelling, case_sensitive, whole_word)
        _save(language, [*entries, entry], voice_id)
        return entry


def update_entry(language: str, entry_id: str, word: str, respelling: str, case_sensitive: bool, whole_word: bool, voice_id: str | None = None) -> Entry:
    """Raises ValueError for invalid input, LookupError for an unknown id, DuplicateWord for a duplicate word."""
    word, respelling = _clean(word, respelling)
    with _lock:
        entries = list_entries(language, voice_id)
        target = next((e for e in entries if e.id == entry_id), None)
        if target is None:
            raise LookupError(entry_id)
        if any(e.id != entry_id and _same_word(e, word, case_sensitive) for e in entries):
            raise DuplicateWord(word)
        target.word, target.respelling = word, respelling
        target.case_sensitive, target.whole_word = case_sensitive, whole_word
        _save(language, entries, voice_id)
        return target


def delete_entry(language: str, entry_id: str, voice_id: str | None = None) -> None:
    """Raises LookupError for an unknown id."""
    with _lock:
        entries = list_entries(language, voice_id)
        kept = [e for e in entries if e.id != entry_id]
        if len(kept) == len(entries):
            raise LookupError(entry_id)
        _save(language, kept, voice_id)


def delete_voice_entries(voice_id: str) -> None:
    """Remove every list of a saved voice (when the voice itself is deleted)."""
    if not _VOICE.match(voice_id):
        raise ValueError(f"Invalid voice id '{voice_id}'.")
    with _lock:
        for path in data_dir("pronunciation", "voices").glob(f"{voice_id}.*.json"):
            path.unlink(missing_ok=True)


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


def apply(text: str, language: str, voice_id: str | None = None) -> str:
    """`text` rewritten with the voice's, the language's and the shared entries (unchanged when there are none).

    With `voice_id` (a saved voice), that voice's words come first and replace any language or shared
    entry for the same word, whatever its capitals. The language's entries come before the shared ones,
    so for the same matched text they win (rewrite's sort is stable); otherwise the longest match wins
    whatever its list.
    """
    if language == ALL:
        raise ValueError("Speech needs a language; the shared words apply within it.")
    own = list_entries(language, voice_id) if voice_id else []
    taken = {e.word.lower() for e in own}
    entries = [*own, *(e for e in [*list_entries(language), *list_entries(ALL)] if e.word.lower() not in taken)]
    return rewrite(text, entries) if entries else text


MAX_VOCABULARY_CHARS = 500  # Whisper's prompt window is about 224 tokens; names cost 2 to 3 characters a token


def recognition_vocabulary(language: str | None) -> str | None:
    """The words to hand the speech recognizer as hints, or None when there are none.

    The language's words come first, then the shared ones; with no language (auto-detect) every language's
    list is included. Duplicates are dropped ignoring case, and the text is cut at a whole word to fit
    MAX_VOCABULARY_CHARS.
    """
    if language is None:
        folder = data_dir("pronunciation")
        languages = sorted(p.stem for p in folder.glob("*.json") if _LANGUAGE.match(p.stem))
    else:
        languages = [language]
    words, seen, length = [], set(), 0
    for lang in [*languages, ALL]:
        for entry in list_entries(lang):
            key = entry.word.lower()
            if key in seen:
                continue
            length += len(entry.word) + (2 if words else 0)  # ", " between words
            if length > MAX_VOCABULARY_CHARS:
                return ", ".join(words) or None
            seen.add(key)
            words.append(entry.word)
    return ", ".join(words) or None
