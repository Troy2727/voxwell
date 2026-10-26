import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from voxwell.features.dictation import engine
from voxwell.paths import data_dir

router = APIRouter(tags=["dictation"])


@router.get("/status")
def status():
    return {"ready": False}


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...), language: str | None = Form(None)):
    data = await file.read()
    if not data:
        raise HTTPException(422, "The recording is empty.")
    # The upload's filename is never used; ffmpeg/PyAV sniff the container themselves.
    fd, name = tempfile.mkstemp(suffix=".audio", dir=data_dir("dictation"))
    path = Path(name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        try:
            result = engine.transcribe(path, language or None)
        except engine.AudioError as exc:
            raise HTTPException(422, str(exc))
        except Exception as exc:
            raise HTTPException(500, f"Transcription failed: {exc}")
        return {
            "text": result.text,
            "language": result.language,
            "segments": [asdict(s) for s in result.segments],
        }
    finally:
        path.unlink(missing_ok=True)
