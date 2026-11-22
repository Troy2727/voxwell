from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from voxwell import voices
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
    voice_id: str = ""  # a saved voice's own list (Voice pronunciation); empty: the language's list


class PreviewRequest(BaseModel):
    text: str
    language: str = "en"
    voice_id: str = ""


def _language(language: str) -> str:
    if language not in LANGUAGES:
        raise HTTPException(422, f"Unsupported language '{language}'.")
    return language


def _scope(language: str) -> str:
    """A language, or store.ALL for the words shared by every language."""
    return language if language == store.ALL else _language(language)


def _voice(voice_id: str) -> str | None:
    if not voice_id:
        return None
    try:
        voices.voice_audio_path(voice_id)
    except KeyError:
        raise HTTPException(404, "Unknown voice.")
    return voice_id


def _list(language: str, voice_id: str) -> tuple[str, str | None]:
    """The list a request names: a language or the shared scope, or one voice's words in a language."""
    scope, voice = _scope(language), _voice(voice_id)
    if voice and scope == store.ALL:
        raise HTTPException(422, "A voice's words are kept per language. Pick a language.")
    return scope, voice


@router.get("/status")
def status():
    return {"ready": True}


@router.get("/entries")
def list_entries(language: str = "en", voice_id: str = ""):
    scope, voice = _list(language, voice_id)
    return [asdict(e) for e in store.list_entries(scope, voice)]


@router.post("/entries")
def add_entry(req: EntryRequest):
    try:
        scope, voice = _list(req.language, req.voice_id)
        entry = store.add_entry(scope, req.word, req.respelling, req.case_sensitive, req.whole_word, voice)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except store.DuplicateWord:
        raise HTTPException(409, f"'{req.word.strip()}' already has an entry. Edit it instead.")
    return asdict(entry)


@router.put("/entries/{entry_id}")
def update_entry(entry_id: str, req: EntryRequest):
    try:
        scope, voice = _list(req.language, req.voice_id)
        entry = store.update_entry(scope, entry_id, req.word, req.respelling, req.case_sensitive, req.whole_word, voice)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except LookupError:
        raise HTTPException(404, "Entry not found.")
    except store.DuplicateWord:
        raise HTTPException(409, f"'{req.word.strip()}' already has an entry.")
    return asdict(entry)


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: str, language: str = "en", voice_id: str = ""):
    scope, voice = _list(language, voice_id)
    try:
        store.delete_entry(scope, entry_id, voice)
    except LookupError:
        raise HTTPException(404, "Entry not found.")
    return {"ok": True}


@router.post("/preview")
def preview(req: PreviewRequest):
    """The text as the speech model will receive it; it needs a language, not the shared scope."""
    if req.language == store.ALL:
        raise HTTPException(422, "Pick a language to preview in.")
    if len(req.text) > MAX_PREVIEW:
        raise HTTPException(422, f"Text is too long ({MAX_PREVIEW} characters max).")
    return {"text": store.apply(req.text, _language(req.language), _voice(req.voice_id))}
