"""Audiobooks: imported chapters on disk, rendered chapter by chapter in the background.

Folder layout under data_dir("audiobooks")/<id>/: book.json (settings, chapter list, state),
chapters/NNN.txt (text) and audio/NNN.wav (finished chapters). A chapter is saved as soon as
it is rendered, so a render interrupted by closing Voxwell resumes where it stopped.
"""

import io
import json
import logging
import shutil
import threading
import time
import uuid
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path

from voxwell import voices
from voxwell.errors import user_message
from voxwell.features.audiobook.chunking import chapter_chunks
from voxwell.features.audiobook.importer import Chapter
from voxwell.features.voice_cloning import engine
from voxwell.paths import child_path, data_dir

log = logging.getLogger(__name__)

STATE_FILE = "book.json"
DEFAULT_VOICE = "default"
SENTENCE_PAUSE = 0.25
PARAGRAPH_PAUSE = 0.7
PREVIEW_CHARS = 300
INTERRUPTED = "Voxwell closed while rendering. Press Resume to continue where it stopped."


@dataclass
class ChapterState:
    title: str
    chars: int
    include: bool = True
    status: str = "pending"  # pending | done


@dataclass
class Book:
    id: str
    dir: Path
    title: str
    created: float
    chapters: list[ChapterState] = field(default_factory=list)
    language: str = "en"
    voice: str = DEFAULT_VOICE
    state: str = "draft"  # draft | queued | running | paused | done | error
    step: str = ""
    percent: int = 0
    error: str | None = None


_books: dict[str, Book] = {}
_lock = threading.Lock()
_one_at_a_time = threading.Lock()


def _root() -> Path:
    return data_dir("audiobooks")


def save(book: Book) -> None:
    state = {k: v for k, v in asdict(book).items() if k not in ("id", "dir")}
    (book.dir / STATE_FILE).write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def _load(folder: Path) -> Book | None:
    path = folder / STATE_FILE
    if not path.exists():
        return None
    s = json.loads(path.read_text(encoding="utf-8"))
    s["chapters"] = [ChapterState(**c) for c in s["chapters"]]
    book = Book(folder.name, folder, **s)
    if book.state in ("queued", "running"):  # not in memory, so the app closed mid-render
        book.state, book.error = "paused", INTERRUPTED
        save(book)
    return book


def create(title: str, chapters: list[Chapter]) -> Book:
    book_id = uuid.uuid4().hex[:12]
    folder = _root() / book_id
    (folder / "chapters").mkdir(parents=True)
    (folder / "audio").mkdir()
    for i, ch in enumerate(chapters):
        (folder / "chapters" / f"{i:03}.txt").write_bytes(ch.text.encode("utf-8"))
    book = Book(book_id, folder, title, time.time(), [ChapterState(ch.title, len(ch.text)) for ch in chapters])
    save(book)
    with _lock:
        _books[book_id] = book
    return book


def get(book_id: str) -> Book | None:
    """Look up a book by an already-validated id, loading it from disk after a restart."""
    with _lock:
        book = _books.get(book_id)
        if book is None and (book := _load(child_path(_root(), book_id))):
            _books[book_id] = book
        return book


def list_jobs() -> list[Book]:
    return [book for folder in _root().iterdir() if (book := get(folder.name))]


def working(book: Book) -> bool:
    return book.state in ("queued", "running")


def chapter_text(book: Book, index: int) -> str:
    return (book.dir / "chapters" / f"{index:03}.txt").read_bytes().decode("utf-8")


def chapter_audio(book: Book, index: int) -> Path:
    return book.dir / "audio" / f"{index:03}.wav"


def rename(book: Book, title: str) -> None:
    book.title = title
    save(book)


def delete(book: Book) -> None:
    """Delete a book; ValueError while it is rendering."""
    if working(book):
        raise ValueError("The audiobook is still rendering.")
    with _lock:
        _books.pop(book.id, None)
    shutil.rmtree(book.dir, ignore_errors=True)


def _reference(voice_id: str) -> Path | None:
    if voice_id == DEFAULT_VOICE:
        return None
    try:
        return voices.voice_audio_path(voice_id)
    except KeyError:
        raise ValueError("The narrator voice was deleted. Pick another voice.")


def _join(parts: list[tuple[bytes, float]]) -> bytes:
    """Concatenate 16-bit mono WAV clips; each is followed by its pause (seconds), except the last."""
    out_frames, rate = [], None
    for i, (clip, pause) in enumerate(parts):
        with wave.open(io.BytesIO(clip)) as w:
            rate = rate or w.getframerate()
            out_frames.append(w.readframes(w.getnframes()))
        if i < len(parts) - 1:
            out_frames.append(b"\x00\x00" * int(rate * pause))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"".join(out_frames))
    return buf.getvalue()


def render_text(paragraphs: list[list[str]], language: str, reference: Path | None, progress=None) -> bytes:
    parts = []
    total = sum(len(p) for p in paragraphs)
    for p_index, paragraph in enumerate(paragraphs):
        for c_index, chunk in enumerate(paragraph):
            if progress:
                progress(len(parts), total)
            last_in_paragraph = c_index == len(paragraph) - 1
            parts.append((engine.synthesize(chunk, language, reference), PARAGRAPH_PAUSE if last_in_paragraph else SENTENCE_PAUSE))
    return _join(parts)


def preview(book: Book, index: int) -> bytes:
    """The first few sentences of a chapter, in the book's voice and language."""
    paragraphs, kept, size = chapter_chunks(chapter_text(book, index)), [], 0
    for paragraph in paragraphs:
        take = []
        for chunk in paragraph:
            if size and size + len(chunk) > PREVIEW_CHARS:
                break
            take.append(chunk)
            size += len(chunk)
        if take:
            kept.append(take)
        if size >= PREVIEW_CHARS or len(take) < len(paragraph):
            break
    return render_text(kept, book.language, _reference(book.voice))


def _work(book: Book) -> None:
    with _one_at_a_time:
        book.state = "running"
        save(book)
        try:
            reference = _reference(book.voice)
            todo = [i for i, ch in enumerate(book.chapters) if ch.include and ch.status != "done"]
            for n, index in enumerate(todo):
                ch = book.chapters[index]

                def progress(done, total, n=n, ch=ch):
                    book.step = f"Chapter {n + 1} of {len(todo)}: {ch.title}"
                    book.percent = int(99 * (n + (done / total if total else 0)) / len(todo))

                progress(0, 0)
                audio = render_text(chapter_chunks(chapter_text(book, index)), book.language, reference, progress)
                chapter_audio(book, index).write_bytes(audio)
                ch.status = "done"
                save(book)  # resume point
            book.state, book.step, book.percent, book.error = "done", "Done", 100, None
        except Exception as exc:
            if (message := user_message(exc)) is None:  # not Voxwell's own message: log it instead
                log.exception("Audiobook failed at %s", book.step)
                message = f"{book.step} failed; see the Voxwell log."
            book.state, book.error = "error", message
        save(book)


def start(book: Book) -> None:
    book.state, book.step, book.percent, book.error = "queued", "Waiting for other audiobooks", 0, None
    save(book)
    threading.Thread(target=_work, args=(book,), daemon=True).start()
