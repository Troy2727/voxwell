"""Gallery: listen to ready-made voices and add them to Saved voices.

A preset's sample is generated the first time someone listens and cached, so it sounds the same
every time and the voice you save is exactly the one you heard.
"""

import importlib.util
import logging
import threading
from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from voxwell import voices
from voxwell.features.gallery.presets import BY_ID, PRESETS, Preset
from voxwell.features.voice_design import engine
from voxwell.paths import data_dir

log = logging.getLogger(__name__)

router = APIRouter(tags=["gallery"])
_generating = threading.Lock()  # one sample at a time; a second click waits and reuses it


class AddRequest(BaseModel):
    name: str = ""


def _sample_path(preset: Preset):
    return data_dir("gallery") / f"{preset.id}.wav"


def _view(preset: Preset) -> dict:
    ready = _sample_path(preset).exists()
    return {**asdict(preset), "ready": ready, "audio_url": f"/api/gallery/presets/{preset.id}/audio" if ready else None}


def _preset(preset_id: str) -> Preset:
    preset = BY_ID.get(preset_id)
    if preset is None:
        raise HTTPException(404, "Unknown voice.")
    return preset


@router.get("/status")
def status():
    return {"ready": importlib.util.find_spec("parler_tts") is not None}


@router.get("/presets")
def presets():
    return [_view(p) for p in PRESETS]


@router.post("/presets/{preset_id}/sample")
def sample(preset_id: str):
    preset = _preset(preset_id)
    with _generating:
        path = _sample_path(preset)
        if not path.exists():
            try:
                wav = engine.design(preset.description, preset.sample)
            except Exception as exc:
                log.exception("Could not create the voice")
                raise HTTPException(500, "Could not create the voice; see the Voxwell log.") from exc
            path.write_bytes(wav)
    return _view(preset)


@router.get("/presets/{preset_id}/audio")
def audio(preset_id: str):
    path = _sample_path(_preset(preset_id))
    if not path.exists():
        raise HTTPException(409, "Listen to the voice first.")
    return FileResponse(path, media_type="audio/wav")


@router.post("/presets/{preset_id}/add")
def add(preset_id: str, req: AddRequest):
    preset = _preset(preset_id)
    path = _sample_path(preset)
    if not path.exists():
        raise HTTPException(409, "Listen to the voice first.")
    voice = voices.save_voice(req.name.strip() or preset.name, path.read_bytes(), "design")
    return asdict(voice)
