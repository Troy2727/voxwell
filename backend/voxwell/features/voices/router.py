"""Saved voices: play, rename and delete the clips in the shared voice library.

The list itself is GET /api/voices (main.py), which every feature uses.
"""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from voxwell import voices

router = APIRouter(tags=["voices"])


class RenameRequest(BaseModel):
    name: str


@router.get("/status")
def status():
    return {"ready": True}


@router.get("/{voice_id}/audio")
def audio(voice_id: str):
    try:
        return FileResponse(voices.voice_audio_path(voice_id), media_type="audio/wav")
    except KeyError:
        raise HTTPException(404, "Unknown voice.")


@router.patch("/{voice_id}")
def rename(voice_id: str, req: RenameRequest):
    name = req.name.strip()
    if not name:
        raise HTTPException(422, "Voice name is required.")
    try:
        return asdict(voices.rename_voice(voice_id, name))
    except KeyError:
        raise HTTPException(404, "Unknown voice.")


@router.delete("/{voice_id}")
def delete(voice_id: str):
    try:
        voices.delete_voice(voice_id)
    except KeyError:
        raise HTTPException(404, "Unknown voice.")
    return {"deleted": voice_id}
