"""Apply reverb, distance, background noise and stereo pan to an uploaded recording."""

import asyncio
import logging
import re
import time
import uuid
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from voxwell.features.audio_effects import dsp
from voxwell.paths import child_path, data_dir

log = logging.getLogger(__name__)

router = APIRouter(tags=["audio_effects"])

MAX_UPLOAD = 50 * 1024 * 1024
MAX_SECONDS = 30 * 60
OUTPUT_TTL_SECONDS = 24 * 60 * 60  # results are scratch files; download what you want to keep
_OUTPUT_ID = re.compile(r"^[0-9a-f]{32}$")


@router.get("/status")
def status():
    return {"ready": True}


@router.post("/apply")
async def apply(
    file: UploadFile = File(...),
    reverb: float = Form(0.0),
    distance: float = Form(0.0),
    noise: float = Form(0.0),
    noise_color: Literal["pink", "brown"] = Form("pink"),
    pan: float = Form(0.0),
):
    try:
        fx = dsp.Effects(reverb=reverb, distance=distance, noise=noise, noise_color=noise_color, pan=pan)
    except ValueError:
        raise HTTPException(422, "reverb, distance and noise go from 0 to 1; pan goes from -1 to 1.")
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "The file is too large (50 MB max).")
    try:
        # Decoding and the DSP take seconds on a long file; keep them off the event loop.
        audio, rate = await asyncio.to_thread(dsp.decode, data)
    except ValueError:
        raise HTTPException(422, "Could not read the file as audio. Use WAV, MP3, FLAC or OGG.")
    if len(audio) / rate > MAX_SECONDS:
        raise HTTPException(422, f"Use a recording of up to {MAX_SECONDS // 60} minutes.")
    folder = data_dir("audio_effects")
    cutoff = time.time() - OUTPUT_TTL_SECONDS
    for old in folder.glob("*.wav"):
        if old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)
    output_id = uuid.uuid4().hex
    try:
        wav = await asyncio.to_thread(lambda: dsp.encode_wav(dsp.process(audio, rate, fx), rate))
        (folder / f"{output_id}.wav").write_bytes(wav)
    except Exception as exc:
        log.exception("Applying the effects failed")
        raise HTTPException(500, "Applying the effects failed; see the Voxwell log.") from exc
    return {"id": output_id, "url": f"/api/audio_effects/audio/{output_id}"}


@router.get("/audio/{output_id}")
def get_audio(output_id: str):
    if not _OUTPUT_ID.match(output_id):
        raise HTTPException(404, "Audio not found.")
    path = child_path(data_dir("audio_effects"), f"{output_id}.wav")
    if not path.exists():
        raise HTTPException(404, "Audio not found.")
    return FileResponse(path, media_type="audio/wav", filename=f"{output_id}.wav")
