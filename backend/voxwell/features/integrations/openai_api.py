"""OpenAI-compatible audio endpoints, mounted at /v1, so OpenAI SDKs and tools can use Voxwell.

POST /v1/audio/speech          {model, input, voice, response_format, speed, language*}
POST /v1/audio/transcriptions  multipart: file, model, language, response_format
GET  /v1/models

`model` is accepted and ignored. `voice` is a saved voice's name or id; OpenAI's built-in voice
names ("alloy", ...) use the default voice. *`language` is a Voxwell extension (default "en").
No API key is needed: the server only listens on 127.0.0.1.
"""

import asyncio
import contextlib
import io
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel

from voxwell import voices
from voxwell.features.audiobook.books import render_text
from voxwell.features.audiobook.chunking import chapter_chunks
from voxwell.features.dictation import engine as stt
from voxwell.features.dubbing.ffmpeg import DubbingError, run_ffmpeg
from voxwell.features.dubbing.fitting import build_srt, srt_time
from voxwell.features.tools import engine as tools
from voxwell.features.transcription import jobs as transcription_jobs
from voxwell.features.voice_cloning.engine import LANGUAGES
from voxwell.paths import data_dir

router = APIRouter(tags=["openai-compatible"])

MAX_INPUT = 4096  # OpenAI's limit for /audio/speech
MAX_TRANSCRIPTION_BYTES = 25 * 1024 * 1024  # OpenAI's limit for /audio/transcriptions
_TRANSCRIBER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voxwell-openai-transcribe")
OPENAI_VOICES = {"alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse"}
MEDIA_TYPES = {"wav": "audio/wav", "mp3": "audio/mpeg", "flac": "audio/flac", "opus": "audio/ogg", "aac": "audio/aac", "pcm": "audio/pcm"}
EXTENSIONS = {"mp3": "mp3", "flac": "flac", "opus": "ogg", "aac": "m4a"}  # for ffmpeg, which picks the container by it
log = logging.getLogger(__name__)


class SpeechRequest(BaseModel):
    input: str
    model: str = "voxwell"
    voice: str = "default"
    response_format: str = "mp3"  # OpenAI's default
    speed: float = 1.0
    language: str = "en"


def _error(status: int, message: str, param: str | None = None) -> JSONResponse:
    """OpenAI-style error body, so SDKs show the message."""
    return JSONResponse({"error": {"message": message, "type": "invalid_request_error", "param": param}}, status)


def resolve_voice(name: str) -> Path | None:
    """A saved voice by id or (case-insensitive) name; None for the default voice."""
    key = name.strip()
    if not key or key.lower() in OPENAI_VOICES or key.lower() == "default":
        return None
    try:
        return voices.voice_audio_path(key)
    except KeyError:
        pass
    for v in voices.list_voices():
        if v.name.strip().lower() == key.lower():
            return voices.voice_audio_path(v.id)
    raise KeyError(name)


def _encode(wav: bytes, fmt: str) -> bytes:
    if fmt == "wav":
        return wav
    if fmt == "pcm":  # raw 16-bit little-endian mono, as OpenAI returns it
        return wav[44:]
    with tempfile.TemporaryDirectory(dir=data_dir("integrations")) as tmp:
        src, out = Path(tmp) / "in.wav", Path(tmp) / f"out.{EXTENSIONS[fmt]}"
        src.write_bytes(wav)
        codec = {"mp3": ["-c:a", "libmp3lame", "-q:a", "2"], "flac": ["-c:a", "flac"], "opus": ["-c:a", "libopus"], "aac": ["-c:a", "aac"]}[fmt]
        run_ffmpeg(["-i", str(src), *codec, str(out)])
        return out.read_bytes()


@router.get("/models")
def models():
    return {"object": "list", "data": [
        {"id": "voxwell", "object": "model", "owned_by": "voxwell"},
        {"id": "tts-1", "object": "model", "owned_by": "voxwell"},
        {"id": "whisper-1", "object": "model", "owned_by": "voxwell"},
    ]}


@router.post("/audio/speech")
def speech(req: SpeechRequest):
    text = req.input.strip()
    if not text:
        return _error(400, "input is empty.", "input")
    if len(text) > MAX_INPUT:
        return _error(400, f"input is too long ({MAX_INPUT} characters max).", "input")
    if req.response_format not in MEDIA_TYPES:
        return _error(400, f"response_format must be one of: {', '.join(MEDIA_TYPES)}.", "response_format")
    if not tools.MIN_TEMPO <= req.speed <= tools.MAX_TEMPO:
        return _error(400, f"speed must be between {tools.MIN_TEMPO} and {tools.MAX_TEMPO}.", "speed")
    if req.language not in LANGUAGES:
        return _error(400, f"language must be one of: {', '.join(sorted(LANGUAGES))}.", "language")
    try:
        reference = resolve_voice(req.voice)
    except KeyError:
        names = ", ".join(v.name for v in voices.list_voices()) or "none yet"
        return _error(400, f"Unknown voice '{req.voice}'. Saved voices: {names}.", "voice")
    try:
        # Long input is spoken in sentence-sized pieces, like an audiobook chapter.
        wav = render_text(chapter_chunks(text), req.language, reference)
        if req.speed != 1.0:
            with tempfile.TemporaryDirectory(dir=data_dir("integrations")) as tmp:
                src, out = Path(tmp) / "in.wav", Path(tmp) / "out.wav"
                src.write_bytes(wav)
                seconds = (len(wav) - 44) / 2 / int.from_bytes(wav[24:28], "little")
                tools.fit(src, seconds, seconds / req.speed, out)
                wav = out.read_bytes()
        body = _encode(wav, req.response_format)
    except DubbingError:  # ffmpeg missing or failed (other formats / speed need it)
        log.exception("ffmpeg failed for an OpenAI-compatible speech request")
        return _error(400, f"Converting the audio needs ffmpeg, which is missing or failed; see the Voxwell log. "
                           "response_format 'wav' with speed 1.0 works without ffmpeg.")
    except Exception:
        log.exception("Speech synthesis failed for an OpenAI-compatible request")
        return _error(500, "Speech synthesis failed; see the Voxwell log.")
    return Response(body, media_type=MEDIA_TYPES[req.response_format])


def _vtt(segments) -> str:
    cues = [f"{srt_time(s.start).replace(',', '.')} --> {srt_time(s.end).replace(',', '.')}\n{s.text}\n" for s in segments]
    return "WEBVTT\n\n" + "\n".join(cues)


def _transcribe(path: Path, language: str | None):
    """One transcription at a time on the shared Whisper model, like the Transcribe feature."""
    with transcription_jobs._one_at_a_time:
        return stt.transcribe(path, language)


@router.post("/audio/transcriptions")
async def transcriptions(
    file: UploadFile = File(...),
    model: str = Form("whisper-1"),
    language: str | None = Form(None),
    response_format: str = Form("json"),
):
    if response_format not in ("json", "text", "srt", "vtt", "verbose_json"):
        return _error(400, "response_format must be json, text, srt, vtt or verbose_json.", "response_format")
    data = await file.read(MAX_TRANSCRIPTION_BYTES + 1)
    if len(data) > MAX_TRANSCRIPTION_BYTES:
        return _error(413, f"The file is too large ({MAX_TRANSCRIPTION_BYTES // (1024 * 1024)} MB max, as in OpenAI's API).", "file")
    if not data:
        return _error(400, "The file is empty.", "file")
    fd, name = tempfile.mkstemp(suffix=".audio", dir=data_dir("integrations"))
    path = Path(name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        try:
            # On its own one-worker queue: the server keeps answering meanwhile, and requests
            # waiting for the Whisper lock never tie up the shared thread pool.
            t = await asyncio.get_running_loop().run_in_executor(
                _TRANSCRIBER, _transcribe, path, (language or "").strip().lower() or None
            )
        except stt.AudioError:  # transcribe() raises it only with DECODE_ERROR; never echo exception text
            return _error(400, stt.DECODE_ERROR, "file")
        except Exception:
            log.exception("Transcription failed for an OpenAI-compatible request")
            return _error(500, "Transcription failed; see the Voxwell log.")
    finally:
        # A cancelled request (server shutdown) can leave the worker still reading the file;
        # Windows then refuses the delete, which must not replace the real outcome.
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)
    segments = [s for s in t.segments if s.text]
    if response_format == "text":
        return PlainTextResponse(t.text)
    if response_format == "srt":
        return PlainTextResponse(build_srt([(s.start, s.end, s.text) for s in segments]))
    if response_format == "vtt":
        return PlainTextResponse(_vtt(segments), media_type="text/vtt")
    if response_format == "verbose_json":
        return {
            "task": "transcribe", "language": t.language, "text": t.text,
            "duration": segments[-1].end if segments else 0.0,
            "segments": [{"id": i, "start": s.start, "end": s.end, "text": s.text} for i, s in enumerate(segments)],
        }
    return {"text": t.text}
