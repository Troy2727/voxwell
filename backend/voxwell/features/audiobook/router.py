import importlib.util
import io
import logging
import re
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from voxwell import voices
from voxwell.errors import user_message
from voxwell.features.audiobook import books
from voxwell.features.audiobook.importer import ImportError_, import_book
from voxwell.features.voice_cloning.engine import LANGUAGES
from voxwell.paths import attachment, child_path, data_dir, download_name

log = logging.getLogger(__name__)

router = APIRouter(tags=["audiobook"])

MAX_UPLOAD = 50 * 1024 * 1024
MAX_TITLE = 100
_BOOK_ID = re.compile(r"^[0-9a-f]{12}$")
_PREVIEW_ID = re.compile(r"^[0-9a-f]{32}$")


class ChapterSettings(BaseModel):
    include: bool


class BookSettings(BaseModel):
    language: str | None = None
    voice: str | None = None
    chapters: list[ChapterSettings] | None = None


class PreviewRequest(BaseModel):
    chapter: int


def summary(book: books.Book) -> dict:
    return {
        "id": book.id, "title": book.title, "created": book.created, "language": book.language,
        "voice": book.voice, "state": book.state, "step": book.step, "percent": book.percent,
        "error": book.error,
        "chapters": [
            {**c.__dict__, "audio_url": f"/api/audiobook/books/{book.id}/chapters/{i}/audio" if c.status == "done" else None}
            for i, c in enumerate(book.chapters)
        ],
        "download_url": f"/api/audiobook/books/{book.id}/download",
    }


def _book(book_id: str) -> books.Book:
    book = books.get(book_id) if _BOOK_ID.match(book_id) else None
    if book is None:
        raise HTTPException(404, "Unknown audiobook.")
    return book


def _chapter(book: books.Book, index: int) -> int:
    if not 0 <= index < len(book.chapters):
        raise HTTPException(404, "Unknown chapter.")
    return index


@router.get("/status")
def status():
    return {"ready": importlib.util.find_spec("chatterbox") is not None, "languages": LANGUAGES}


@router.post("/books")
async def import_upload(file: UploadFile = File(...)):
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "The book is too large (50 MB max).")
    name = Path(file.filename or "")
    try:
        title, chapters = import_book(data, name.stem, name.suffix.lower())
    except ImportError_ as exc:
        raise HTTPException(422, str(exc))
    return summary(books.create(title[:MAX_TITLE], chapters))


@router.get("/books")
def list_books():
    return sorted((summary(b) for b in books.list_jobs()), key=lambda s: s["created"], reverse=True)


@router.get("/books/{book_id}")
def get_book(book_id: str):
    return summary(_book(book_id))


@router.get("/books/{book_id}/chapters/{index}/text")
def chapter_text(book_id: str, index: int):
    book = _book(book_id)
    return {"text": books.chapter_text(book, _chapter(book, index))}


@router.patch("/books/{book_id}")
def update(book_id: str, req: BookSettings):
    book = _book(book_id)
    if books.working(book):
        raise HTTPException(409, "Wait for the render to finish before changing settings.")
    if req.language is not None:
        if req.language not in LANGUAGES:
            raise HTTPException(422, f"Unsupported language '{req.language}'.")
        book.language = req.language
    if req.voice is not None:
        if req.voice != books.DEFAULT_VOICE:
            try:
                voices.voice_audio_path(req.voice)
            except KeyError:
                raise HTTPException(422, "Unknown voice.")
        book.voice = req.voice
    if req.chapters is not None:
        if len(req.chapters) != len(book.chapters):
            raise HTTPException(422, "Send a setting for every chapter.")
        for ch, setting in zip(book.chapters, req.chapters):
            ch.include = setting.include
    if req.language is not None or req.voice is not None:
        # New voice or language: finished chapters no longer match, so they render again.
        for i, ch in enumerate(book.chapters):
            ch.status = "pending"
            books.chapter_audio(book, i).unlink(missing_ok=True)
        if book.state == "done":
            book.state = "draft"
    books.save(book)
    return summary(book)


@router.post("/books/{book_id}/render")
def render(book_id: str):
    book = _book(book_id)
    if books.working(book):
        raise HTTPException(409, "The audiobook is already rendering.")
    if not any(ch.include for ch in book.chapters):
        raise HTTPException(422, "Choose at least one chapter.")
    books.start(book)
    return summary(book)


@router.post("/books/{book_id}/preview")
def preview(book_id: str, req: PreviewRequest):
    book = _book(book_id)
    index = _chapter(book, req.chapter)
    try:
        wav = books.preview(book, index)
    except Exception as exc:
        if (message := user_message(exc)) is not None:  # Voxwell's own message (e.g. a deleted voice)
            raise HTTPException(422, message) from exc
        log.exception("Preview failed")
        raise HTTPException(500, "Preview failed; see the Voxwell log.") from exc
    folder = data_dir("audiobooks_previews")
    for old in folder.glob("*.wav"):  # one preview at a time is enough
        old.unlink(missing_ok=True)
    preview_id = uuid.uuid4().hex
    (folder / f"{preview_id}.wav").write_bytes(wav)
    return {"url": f"/api/audiobook/previews/{preview_id}"}


@router.get("/previews/{preview_id}")
def preview_audio(preview_id: str):
    if not _PREVIEW_ID.match(preview_id):
        raise HTTPException(404, "Preview not found.")
    path = child_path(data_dir("audiobooks_previews"), f"{preview_id}.wav")
    if not path.exists():
        raise HTTPException(404, "Preview not found.")
    return FileResponse(path, media_type="audio/wav")


@router.get("/books/{book_id}/chapters/{index}/audio")
def chapter_audio(book_id: str, index: int):
    book = _book(book_id)
    path = books.chapter_audio(book, _chapter(book, index))
    if book.chapters[index].status != "done" or not path.exists():
        raise HTTPException(409, "This chapter has not been rendered yet.")
    name = download_name(book.chapters[index].title, ".wav", "Chapter")
    return FileResponse(path, media_type="audio/wav", filename=f"{index + 1:03} - {name}")


@router.get("/books/{book_id}/download")
def download(book_id: str):
    """All rendered chapters as one ZIP, numbered in reading order."""
    book = _book(book_id)
    done = [(i, ch) for i, ch in enumerate(book.chapters) if ch.status == "done"]
    if not done:
        raise HTTPException(409, "No chapters have been rendered yet.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:  # WAV barely compresses
        for i, ch in done:
            zf.write(books.chapter_audio(book, i), f"{i + 1:03} - {download_name(ch.title, '.wav', 'Chapter')}")
    return Response(
        buf.getvalue(), media_type="application/zip",
        headers=attachment(download_name(book.title, ".zip", "Audiobook")),
    )
