import importlib.util
import logging
import os
import re
import tempfile
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, WebSocket

from voxwell import live_audio
from voxwell.features.dictation import engine
from voxwell.paths import data_dir

log = logging.getLogger(__name__)

router = APIRouter(tags=["dictation"])


@router.get("/status")
def status():
    return {"ready": importlib.util.find_spec("faster_whisper") is not None}


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
            log.exception("Transcription failed")
            raise HTTPException(500, "Transcription failed; see the Voxwell log.") from exc
        return {
            "text": result.text,
            "language": result.language,
            "segments": [asdict(s) for s in result.segments],
        }
    finally:
        path.unlink(missing_ok=True)


@router.websocket("/live")
async def live(ws: WebSocket):
    """Live dictation: each turn (speech up to a pause) is transcribed as it ends. See voxwell.live_audio."""

    def open_session(config: dict):
        language = config.get("language") or None
        if language is not None and not (isinstance(language, str) and re.fullmatch(r"[a-z]{2,3}", language)):
            raise ValueError("language must be an ISO 639-1 code such as en.")

        def process(pcm: bytes, index: int) -> dict:
            # An AudioError's message reaches the user; any other failure is logged (live_audio).
            result = live_audio.transcribe_turn(pcm, language)
            return {"text": result.text, "language": result.language}

        return process

    await live_audio.run_session(ws, open_session)
