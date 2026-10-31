"""Speech translation: live (speak and hear the translation turn by turn) and one-off (text or a recording)."""

import importlib.util
import logging
import os
import re
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, WebSocket
from fastapi.responses import FileResponse
from pydantic import BaseModel

from voxwell import live_audio
from voxwell.features.dictation import engine as stt
from voxwell.features.translation import pipeline
from voxwell.paths import child_path, data_dir

log = logging.getLogger(__name__)

router = APIRouter(tags=["translation"])

MAX_TEXT = 4096
MAX_UPLOAD = 50 * 1024 * 1024
OUTPUT_TTL_SECONDS = 24 * 60 * 60  # results are scratch files, as in Tools
_OUTPUT_ID = re.compile(r"^[0-9a-f]{32}$")


@router.get("/status")
def status():
    """Readiness, source languages (recognized and translated) and target languages (translated and spoken)."""
    ready = all(importlib.util.find_spec(m) is not None for m in ("faster_whisper", "transformers", "chatterbox"))
    return {"ready": ready, "sources": sorted(pipeline.SOURCE_LANGUAGES), "targets": sorted(pipeline.TARGET_LANGUAGES)}


def _check(source: str | None, target: str, voice: str | None):
    try:
        return pipeline.check(source, target, voice)
    except pipeline.TranslationError as exc:
        raise HTTPException(422, str(exc))


def _translate_and_speak(text: str, source: str, target: str, reference) -> dict:
    """Translate `text`, speak it and keep the WAV as a scratch file; the response gives its URL."""
    if len(text) > MAX_TEXT:
        raise HTTPException(422, f"The text is too long ({MAX_TEXT} characters max).")
    try:
        translation = pipeline.translate_text(text, source, target)
    except pipeline.TranslationError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        log.exception("Translation failed")
        raise HTTPException(500, "Translation failed; see the Voxwell log.") from exc
    try:
        wav = pipeline.speak(translation, target, reference)
    except Exception as exc:
        log.exception("Speech synthesis failed")
        raise HTTPException(500, "Speech synthesis failed; see the Voxwell log.") from exc
    folder = data_dir("translation")
    cutoff = time.time() - OUTPUT_TTL_SECONDS
    for old in folder.glob("*.wav"):
        if old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)
    output_id = uuid.uuid4().hex
    (folder / f"{output_id}.wav").write_bytes(wav)
    return {"transcript": text, "source": source, "translation": translation, "url": f"/api/translation/audio/{output_id}"}


class SpeakRequest(BaseModel):
    text: str
    source: str = "en"
    target: str
    voice: str | None = None  # a saved voice id; None for the default voice


@router.post("/speak")
def speak(req: SpeakRequest):
    """Translate text and speak the translation."""
    reference = _check(req.source, req.target, req.voice)
    if not req.text.strip():
        raise HTTPException(422, "The text is empty.")
    return _translate_and_speak(req.text.strip(), req.source, req.target, reference)


@router.post("/file")
async def translate_file(
    file: UploadFile = File(...),
    target: str = Form(...),
    source: str | None = Form(None),
    voice: str | None = Form(None),
):
    """Transcribe a recording (detecting its language unless `source` is given), translate it and speak it."""
    reference = _check(source or None, target, voice or None)
    data = await file.read(MAX_UPLOAD + 1)
    if not data:
        raise HTTPException(422, "The file is empty.")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "The file is too large (50 MB max).")
    # The upload's filename is never used; the decoder sniffs the format itself.
    fd, name = tempfile.mkstemp(suffix=".audio", dir=data_dir("translation"))
    path = Path(name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        try:
            heard = stt.transcribe(path, source or None)
        except stt.AudioError as exc:
            raise HTTPException(422, str(exc))
        except Exception as exc:
            log.exception("Transcription failed")
            raise HTTPException(500, "Transcription failed; see the Voxwell log.") from exc
    finally:
        path.unlink(missing_ok=True)
    if not heard.text:
        raise HTTPException(422, "No speech found in the recording.")
    return _translate_and_speak(heard.text, heard.language, target, reference)


@router.get("/audio/{output_id}")
def audio(output_id: str):
    if not _OUTPUT_ID.match(output_id):
        raise HTTPException(404, "Not found.")
    path = child_path(data_dir("translation"), f"{output_id}.wav")
    if not path.exists():
        raise HTTPException(404, "Not found.")
    return FileResponse(path, media_type="audio/wav")


@router.websocket("/live")
async def live(ws: WebSocket):
    """Live translation, one turn at a time (see voxwell.live_audio). Config: source (null = detect), target, voice."""

    def open_session(config: dict):
        source, target, voice = (config.get(k) or None for k in ("source", "target", "voice"))
        if not all(v is None or isinstance(v, str) for v in (source, target, voice)):
            raise ValueError("source, target and voice must be strings.")
        if target is None:
            raise ValueError("Choose a target language.")
        reference = pipeline.check(source, target, voice)
        return lambda pcm, index: pipeline.translate_turn(pcm, source, target, reference)

    await live_audio.run_session(ws, open_session)
