import asyncio
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
from voxwell.features.transcription import editing
from voxwell.paths import data_dir

log = logging.getLogger(__name__)

router = APIRouter(tags=["dictation"])

MAX_UPLOAD = 50 * 1024 * 1024  # as translation's file upload


@router.get("/status")
def status():
    return {"ready": importlib.util.find_spec("faster_whisper") is not None}


@router.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...), language: str | None = Form(None), cleanup: str | None = Form(None)
):
    if cleanup and cleanup not in editing.PRESETS:
        raise HTTPException(422, f"Unknown clean-up '{cleanup}'. Options: {', '.join(editing.PRESETS)}.")
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "The recording is too large (50 MB max).")
    if not data:
        raise HTTPException(422, "The recording is empty.")
    # The upload's filename is never used; ffmpeg/PyAV sniff the container themselves.
    fd, name = tempfile.mkstemp(suffix=".audio", dir=data_dir("dictation"))
    path = Path(name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        try:
            # In a worker thread, so the server (live audio included) keeps answering meanwhile.
            result = await asyncio.to_thread(engine.transcribe, path, language or None, speech_only=True)
        except engine.AudioError as exc:
            raise HTTPException(422, str(exc))
        except Exception as exc:
            log.exception("Transcription failed")
            raise HTTPException(500, "Transcription failed; see the Voxwell log.") from exc
        text, cleanup_error = result.text, None
        if cleanup and text.strip():
            try:
                text = (await asyncio.to_thread(editing.edit_text, text, editing.PRESETS[cleanup][1])).text
            except Exception:  # the dictation still succeeds, with what Whisper heard
                log.exception("Dictation clean-up failed")
                cleanup_error = "Clean-up failed, so this is the original text."
        return {
            "text": text,
            "original": result.text,
            "language": result.language,
            "segments": [asdict(s) for s in result.segments],
            **({"cleanup_error": cleanup_error} if cleanup_error else {}),
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
