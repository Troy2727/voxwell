from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from voxwell.features.pronunciation import store
from voxwell.features.voice_cloning.engine import LANGUAGES

router = APIRouter(tags=["pronunciation"])

MAX_PREVIEW = 2000


class EntryRequest(BaseModel):
    language: str = "en"
    word: str
    respelling: str
    case_sensitive: bool = False
    whole_word: bool = True


class PreviewRequest(BaseModel):
    text: str
    language: str = "en"


def _language(language: str) -> str:
    if language not in LANGUAGES:
        raise HTTPException(422, f"Unsupported language '{language}'.")
    return language


@router.get("/status")
def status():
    return {"ready": True}


@router.get("/entries")
def list_entries(language: str = "en"):
    return [asdict(e) for e in store.list_entries(_language(language))]


@router.post("/entries")
def add_entry(req: EntryRequest):
    try:
        entry = store.add_entry(_language(req.language), req.word, req.respelling, req.case_sensitive, req.whole_word)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except store.DuplicateWord:
        raise HTTPException(409, f"'{req.word.strip()}' already has an entry. Edit it instead.")
    return asdict(entry)


@router.put("/entries/{entry_id}")
def update_entry(entry_id: str, req: EntryRequest):
    try:
        entry = store.update_entry(_language(req.language), entry_id, req.word, req.respelling, req.case_sensitive, req.whole_word)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except LookupError:
        raise HTTPException(404, "Entry not found.")
    except store.DuplicateWord:
        raise HTTPException(409, f"'{req.word.strip()}' already has an entry.")
    return asdict(entry)


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: str, language: str = "en"):
    try:
        store.delete_entry(_language(language), entry_id)
    except LookupError:
        raise HTTPException(404, "Entry not found.")
    return {"ok": True}


@router.post("/preview")
def preview(req: PreviewRequest):
    """The text as the speech model will receive it."""
    if len(req.text) > MAX_PREVIEW:
        raise HTTPException(422, f"Text is too long ({MAX_PREVIEW} characters max).")
    return {"text": store.apply(req.text, _language(req.language))}
