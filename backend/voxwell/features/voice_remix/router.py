import asyncio
import importlib.util
import re
import time
import uuid
from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from voxwell import voices
from voxwell.features.voice_remix import engine
from voxwell.paths import data_dir

router = APIRouter(tags=["voice_remix"])

MAX_PROMPT = 500
MAX_SCRIPT = 500
PREVIEW_TTL_SECONDS = 24 * 60 * 60  # previews are scratch files; saving copies one into the library
_PREVIEW_ID = re.compile(r"^[0-9a-f]{32}$")


class PreviewRequest(BaseModel):
    voice_id: str
    prompt: str
    strength: str = "medium"
    script: str | None = None


class SaveRequest(BaseModel):
    preview_id: str
    name: str


def _preview_path(preview_id: str):
    path = data_dir("voice_remix") / f"{preview_id}.wav"
    if not _PREVIEW_ID.match(preview_id) or not path.exists():
        raise HTTPException(404, "Preview not found.")
    return path


@router.get("/status")
def status():
    ready = importlib.util.find_spec("parler_tts") is not None and importlib.util.find_spec("chatterbox") is not None
    return {"ready": ready, "strengths": list(engine.STRENGTHS), "default_script": engine.DEFAULT_SCRIPT}


@router.post("/preview")
async def preview(req: PreviewRequest):
    prompt = req.prompt.strip()
    script = (req.script or "").strip() or engine.DEFAULT_SCRIPT
    if not prompt:
        raise HTTPException(422, "Describe how the voice should change.")
    if len(prompt) > MAX_PROMPT:
        raise HTTPException(422, f"The description is too long ({MAX_PROMPT} characters max).")
    if len(script) > MAX_SCRIPT:
        raise HTTPException(422, f"The script is too long ({MAX_SCRIPT} characters max).")
    if req.strength not in engine.STRENGTHS:
        raise HTTPException(422, f"Strength must be one of: {', '.join(engine.STRENGTHS)}.")
    try:
        source = voices.voice_audio_path(req.voice_id)
    except KeyError:
        raise HTTPException(404, "Pick a saved voice to remix.")
    try:
        wav = await asyncio.to_thread(engine.remix, source, prompt, req.strength, script)
    except Exception as exc:
        raise HTTPException(500, f"Voice remix failed: {type(exc).__name__}: {exc}")
    folder = data_dir("voice_remix")
    cutoff = time.time() - PREVIEW_TTL_SECONDS
    for old in folder.glob("*.wav"):
        if old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)
    preview_id = uuid.uuid4().hex
    (folder / f"{preview_id}.wav").write_bytes(wav)
    return {"preview_id": preview_id, "url": f"/api/voice_remix/audio/{preview_id}"}


@router.get("/audio/{preview_id}")
def audio(preview_id: str):
    return FileResponse(_preview_path(preview_id), media_type="audio/wav")


@router.post("/save")
def save(req: SaveRequest):
    name = req.name.strip()
    if not name:
        raise HTTPException(422, "Give the voice a name.")
    path = _preview_path(req.preview_id)
    return asdict(voices.save_voice(name, path.read_bytes(), "remix"))
