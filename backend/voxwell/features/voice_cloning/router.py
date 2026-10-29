import importlib.util
import io
import re
import uuid
from dataclasses import asdict

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from voxwell import voices
from voxwell.features.audio_effects.dsp import Effects
from voxwell.features.voice_cloning import engine, history
from voxwell.paths import data_dir

router = APIRouter(tags=["voice_cloning"])

MAX_TEXT = 2000
MAX_UPLOAD = 50 * 1024 * 1024
_AUDIO_ID = re.compile(r"^[0-9a-f]{32}$")


class SynthesizeRequest(BaseModel):
    text: str
    language: str = "en"
    voice_id: str | None = None
    effects: Effects | None = None


@router.get("/status")
def status():
    return {"ready": importlib.util.find_spec("chatterbox") is not None, "languages": engine.LANGUAGES}


@router.post("/voices")
async def upload_voice(name: str = Form(...), file: UploadFile = File(...)):
    name = name.strip()
    if not name:
        raise HTTPException(422, "Voice name is required.")
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Audio file is too large (50 MB max).")
    try:
        wav = _to_wav(data)
    except ValueError:
        raise HTTPException(422, "Could not read the file as audio. Use WAV, MP3, FLAC or OGG.")
    return asdict(voices.save_voice(name, wav, "upload"))


def _to_wav(data: bytes) -> bytes:
    """Decode any format libsndfile reads (WAV, MP3, FLAC, OGG) and re-encode as 16-bit WAV."""
    import soundfile as sf

    try:
        audio, rate = sf.read(io.BytesIO(data), dtype="int16")
    except (RuntimeError, TypeError, ValueError) as exc:  # libsndfile errors are RuntimeErrors
        raise ValueError("undecodable audio") from exc
    if len(audio) == 0:
        raise ValueError("empty audio")
    buf = io.BytesIO()
    sf.write(buf, audio, rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


@router.post("/synthesize")
def synthesize(req: SynthesizeRequest):
    text = req.text.strip()
    if not text:
        raise HTTPException(422, "Text is empty.")
    if len(text) > MAX_TEXT:
        raise HTTPException(422, f"Text is too long ({MAX_TEXT} characters max).")
    if req.language not in engine.LANGUAGES:
        raise HTTPException(422, f"Unsupported language '{req.language}'.")
    reference, voice_name = None, "Default voice"
    if req.voice_id:
        try:
            reference = voices.voice_audio_path(req.voice_id)
            voice_name = voices.get_voice(req.voice_id).name
        except KeyError:
            raise HTTPException(404, "Unknown voice.")
    try:
        extra = {"effects": req.effects} if req.effects else {}
        wav = engine.synthesize(text, req.language, reference, **extra)
    except Exception as exc:
        raise HTTPException(500, f"Speech synthesis failed: {exc}")
    audio_id = uuid.uuid4().hex
    (data_dir("voice_cloning") / f"{audio_id}.wav").write_bytes(wav)
    history.record(audio_id, text, req.language, voice_name)
    return {"id": audio_id, "url": f"/api/voice_cloning/audio/{audio_id}"}


@router.get("/audio/{audio_id}")
def get_audio(audio_id: str):
    if not _AUDIO_ID.match(audio_id):
        raise HTTPException(404, "Audio not found.")
    path = data_dir("voice_cloning") / f"{audio_id}.wav"
    if not path.exists():
        raise HTTPException(404, "Audio not found.")
    return FileResponse(path, media_type="audio/wav", filename=f"{audio_id}.wav")
