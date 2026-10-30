import asyncio
import random
import uuid
from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from voxwell.features.sound import engine, history, token

router = APIRouter(tags=["sound"])

MAX_PROMPT = 500
DEFAULT_STEPS = 100


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT)
    duration: float = Field(default=10, ge=1, le=30)
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)
    steps: int = Field(default=DEFAULT_STEPS, ge=10, le=250)


class TokenRequest(BaseModel):
    token: str


def _item(sound: history.Sound) -> dict:
    return {**asdict(sound), "url": f"/api/sound/audio/{sound.id}"}


@router.get("/status")
def status():
    """Never includes the token itself, only whether one is set."""
    return {
        "ready": True,
        "installed": engine.is_installed(),
        "token_set": token.token_set(),
        "model": engine.MODEL_ID,
        "model_url": engine.MODEL_URL,
    }


@router.put("/token")
def set_token(req: TokenRequest):
    try:
        token.save_token(req.token)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"token_set": True}


@router.delete("/token")
def clear_token():
    token.clear_token()
    return {"token_set": token.token_set()}


@router.post("/generate")
async def generate(req: GenerateRequest):
    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(422, "Describe the sound you want.")
    seed = req.seed if req.seed is not None else random.randrange(2**32)
    try:
        wav = await asyncio.to_thread(engine.generate, prompt, req.duration, req.steps, seed, token.get_token())
    except engine.Busy:
        raise HTTPException(409, "Another sound is still being generated. Wait for it to finish.")
    except engine.AccessError as exc:
        raise HTTPException(403, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Sound generation failed: {type(exc).__name__}")
    sound = history.save(uuid.uuid4().hex, wav, prompt, req.duration, seed, req.steps)
    return _item(sound)


@router.get("/history")
def list_history():
    return [_item(s) for s in history.list_sounds()]


@router.get("/audio/{sound_id}")
def get_audio(sound_id: str):
    try:
        path = history.audio_path(sound_id)
    except KeyError:
        raise HTTPException(404, "Sound not found.")
    return FileResponse(path, media_type="audio/wav", filename=f"{sound_id}.wav")


@router.delete("/history/{sound_id}")
def delete(sound_id: str):
    try:
        history.delete(sound_id)
    except KeyError:
        raise HTTPException(404, "Sound not found.")
    return {"deleted": sound_id}
