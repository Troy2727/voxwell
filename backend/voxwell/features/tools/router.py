"""Tools: voice conversion, AI direction, speech-rate fit and file info. (Compare voices is a page
that calls /speak once per voice.)"""

import importlib.util
import io
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from voxwell import voices
from voxwell.features.dubbing.ffmpeg import DubbingError, ffmpeg_path
from voxwell.features.tools import direction, engine
from voxwell.features.voice_cloning import engine as cloning_engine
from voxwell.paths import data_dir

router = APIRouter(tags=["tools"])

MAX_UPLOAD = 50 * 1024 * 1024
MAX_COMPARE_TEXT = 300
OUTPUT_TTL_SECONDS = 24 * 60 * 60  # results are scratch files; download what you want to keep
_OUTPUT_ID = re.compile(r"^[0-9a-f]{32}$")
_EXT = re.compile(r"\.[a-z0-9]{1,6}")


def _ffmpeg_ready() -> bool:
    try:
        ffmpeg_path()
        return True
    except DubbingError:
        return False


@router.get("/status")
def status():
    return {"ready": importlib.util.find_spec("chatterbox") is not None, "ffmpeg": _ffmpeg_ready()}


async def _read_audio(file: UploadFile) -> tuple[bytes, float]:
    """Upload -> 16-bit WAV bytes and duration; 422 if it is not decodable audio."""
    import soundfile as sf

    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "The file is too large (50 MB max).")
    try:
        audio, rate = sf.read(io.BytesIO(data), dtype="int16")
    except (RuntimeError, TypeError, ValueError):  # libsndfile errors are RuntimeErrors
        raise HTTPException(422, "Could not read the file as audio. Use WAV, MP3, FLAC or OGG.")
    if len(audio) == 0:
        raise HTTPException(422, "The audio is empty.")
    buf = io.BytesIO()
    sf.write(buf, audio, rate, format="WAV", subtype="PCM_16")
    return buf.getvalue(), len(audio) / rate


def _new_output() -> tuple[str, Path]:
    folder = data_dir("tools")
    cutoff = time.time() - OUTPUT_TTL_SECONDS
    for old in folder.glob("*.wav"):
        if old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)
    output_id = uuid.uuid4().hex
    return output_id, folder / f"{output_id}.wav"


def _result(output_id: str, **extra) -> dict:
    return {"url": f"/api/tools/audio/{output_id}", **extra}


@router.post("/convert")
async def convert(file: UploadFile = File(...), voice_id: str = Form(...)):
    try:
        target = voices.voice_audio_path(voice_id)
    except KeyError:
        raise HTTPException(422, "Pick a saved voice.")
    wav, _ = await _read_audio(file)
    output_id, out = _new_output()
    source = out.with_suffix(".source.wav")
    source.write_bytes(wav)
    try:
        out.write_bytes(engine.convert(source, target))
    except Exception as exc:
        raise HTTPException(500, f"Voice conversion failed: {exc}")
    finally:
        source.unlink(missing_ok=True)
    return _result(output_id)


class SpeakRequest(BaseModel):
    text: str
    language: str = "en"
    voice_id: str | None = None


@router.post("/speak")
def speak(req: SpeakRequest):
    """One voice of a comparison. Kept out of Projects: results are scratch files."""
    text = req.text.strip()
    if not text or len(text) > MAX_COMPARE_TEXT:
        raise HTTPException(422, f"Write 1 to {MAX_COMPARE_TEXT} characters.")
    if req.language not in cloning_engine.LANGUAGES:
        raise HTTPException(422, f"Unsupported language '{req.language}'.")
    reference = None
    if req.voice_id:
        try:
            reference = voices.voice_audio_path(req.voice_id)
        except KeyError:
            raise HTTPException(422, "Unknown voice.")
    try:
        wav = cloning_engine.synthesize(text, req.language, reference)
    except Exception as exc:
        raise HTTPException(500, f"Speech synthesis failed: {exc}")
    output_id, out = _new_output()
    out.write_bytes(wav)
    return _result(output_id)


class DirectionRequest(BaseModel):
    note: str


class DirectedSpeakRequest(SpeakRequest):
    intensity: float = 0.5  # 0..1, from /direction/interpret or the sliders
    pace: str = "normal"


MAX_NOTE = 300
PACE_TEMPO = {"slow": 0.9, "normal": 1.0, "fast": 1.15}
PACE_CFG = {"slow": 0.3, "normal": 0.5, "fast": 0.5}  # lower CFG = more deliberate delivery


def exaggeration_for(intensity: float) -> float:
    """0..1 intensity -> Chatterbox exaggeration: 0.3 (flat) .. 0.5 (natural) .. 1.4 (theatrical)."""
    i = min(max(intensity, 0.0), 1.0)
    return 0.3 + i * 0.4 if i <= 0.5 else 0.5 + (i - 0.5) * 1.8


@router.post("/direction/interpret")
def interpret(req: DirectionRequest):
    note = req.note.strip()
    if not note or len(note) > MAX_NOTE:
        raise HTTPException(422, f"Write a direction of 1 to {MAX_NOTE} characters.")
    try:
        return asdict(direction.interpret(note))
    except direction.DirectionError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"The AI director failed: {exc}")


@router.post("/direction/speak")
def directed_speak(req: DirectedSpeakRequest):
    text = req.text.strip()
    if not text or len(text) > MAX_COMPARE_TEXT:
        raise HTTPException(422, f"Write 1 to {MAX_COMPARE_TEXT} characters.")
    if req.language not in cloning_engine.LANGUAGES:
        raise HTTPException(422, f"Unsupported language '{req.language}'.")
    if req.pace not in PACE_TEMPO:
        raise HTTPException(422, "Pace must be slow, normal or fast.")
    reference = None
    if req.voice_id:
        try:
            reference = voices.voice_audio_path(req.voice_id)
        except KeyError:
            raise HTTPException(422, "Unknown voice.")
    try:
        wav = cloning_engine.synthesize(
            text, req.language, reference, exaggeration=exaggeration_for(req.intensity), cfg_weight=PACE_CFG[req.pace]
        )
    except Exception as exc:
        raise HTTPException(500, f"Speech synthesis failed: {exc}")
    output_id, out = _new_output()
    tempo = PACE_TEMPO[req.pace]
    if tempo != 1.0 and _ffmpeg_ready():  # without ffmpeg, pace comes from the CFG setting alone
        source = out.with_suffix(".source.wav")
        source.write_bytes(wav)
        seconds = (len(wav) - 44) / 2 / int.from_bytes(wav[24:28], "little")
        try:
            engine.fit(source, seconds, seconds / tempo, out)
        finally:
            source.unlink(missing_ok=True)
    else:
        out.write_bytes(wav)
    return _result(output_id, exaggeration=round(exaggeration_for(req.intensity), 2), tempo=tempo if _ffmpeg_ready() else 1.0)


@router.post("/fit")
async def fit(file: UploadFile = File(...), target_seconds: float = Form(...)):
    if not 0.1 <= target_seconds <= 3600:
        raise HTTPException(422, "Choose a length between 0.1 seconds and one hour.")
    wav, seconds = await _read_audio(file)
    output_id, out = _new_output()
    source = out.with_suffix(".source.wav")
    source.write_bytes(wav)
    try:
        engine.fit(source, seconds, target_seconds, out)
    except DubbingError as exc:
        raise HTTPException(422, str(exc))
    finally:
        source.unlink(missing_ok=True)
    return _result(output_id, original_seconds=round(seconds, 3), target_seconds=target_seconds)


@router.post("/probe")
def probe(file: UploadFile = File(...)):
    # Videos can be large, so stream to a temp file; only the extension of the name is kept.
    suffix = Path(file.filename or "").suffix.lower()
    if not _EXT.fullmatch(suffix):
        suffix = ""  # ffprobe sniffs the format anyway
    with tempfile.TemporaryDirectory(dir=data_dir("tools")) as tmp:
        path = Path(tmp) / f"input{suffix}"
        with path.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        try:
            return engine.probe(path)
        except DubbingError as exc:
            raise HTTPException(422, str(exc))


@router.get("/audio/{output_id}")
def audio(output_id: str):
    path = data_dir("tools") / f"{output_id}.wav"
    if not _OUTPUT_ID.match(output_id) or not path.exists():
        raise HTTPException(404, "Result not found.")
    return FileResponse(path, media_type="audio/wav")
