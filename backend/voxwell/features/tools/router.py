"""Tools: voice conversion, video voice conversion, voice isolation, AI direction, speech-rate fit and
file info. (Compare voices is a page that calls /speak once per voice.)"""

import importlib.util
import io
import logging
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
from voxwell.features.tools import direction, engine, isolation
from voxwell.features.voice_cloning import engine as cloning_engine
from voxwell.paths import child_path, data_dir

log = logging.getLogger(__name__)

router = APIRouter(tags=["tools"])

MAX_UPLOAD = 50 * 1024 * 1024
MAX_COMPARE_TEXT = 300
MAX_ISOLATE_SECONDS = 10 * 60  # about 1 GB of working memory; longer files take a while on CPU
MAX_VIDEO_UPLOAD = 2 * 1024**3  # Convert video streams the upload to disk, so this is about disk space
NO_SPEECH_PEAK = 1e-4
NOTE_WHOLE_SOUNDTRACK = "The voice could not be separated from the background, so the whole soundtrack was converted, background included."
NOTE_AUDIO_ONLY = "The video could not be rebuilt with the new voice, so this is the converted audio instead. Your original file is unchanged."
OUTPUT_TTL_SECONDS = 24 * 60 * 60  # results are scratch files; download what you want to keep
_OUTPUT_ID = re.compile(r"^[0-9a-f]{32}$")


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
        # Read as float: libsndfile does not scale float WAVs to int16, so they would arrive silent.
        audio, rate = sf.read(io.BytesIO(data), dtype="float32")
    except (RuntimeError, TypeError, ValueError):  # libsndfile errors are RuntimeErrors
        raise HTTPException(422, "Could not read the file as audio. Use WAV, MP3, FLAC or OGG.")
    if len(audio) == 0:
        raise HTTPException(422, "The audio is empty.")
    buf = io.BytesIO()
    sf.write(buf, audio.clip(-1, 1), rate, format="WAV", subtype="PCM_16")
    return buf.getvalue(), len(audio) / rate


def _new_output() -> tuple[str, Path]:
    folder = data_dir("tools")
    cutoff = time.time() - OUTPUT_TTL_SECONDS
    for old in [*folder.glob("*.wav"), *folder.glob("*.mp4")]:
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
        log.exception("Voice conversion failed")
        raise HTTPException(500, "Voice conversion failed; see the Voxwell log.") from exc
    finally:
        source.unlink(missing_ok=True)
    return _result(output_id)


@router.post("/convert-video")
def convert_video(file: UploadFile = File(...), voice_id: str = Form(...)):
    """Convert video: the voice in a video re-spoken in a saved voice; picture and background kept."""
    import soundfile as sf

    try:
        target = voices.voice_audio_path(voice_id)
    except KeyError:
        raise HTTPException(422, "Pick a saved voice.")
    notes: list[str] = []
    # Nothing here uses the upload's name: ffmpeg would read a name like .m3u8 as a playlist.
    with tempfile.TemporaryDirectory(dir=data_dir("tools")) as tmp:
        work = Path(tmp)
        upload = work / "input"
        size = 0
        with upload.open("wb") as out:
            while chunk := file.file.read(1 << 20):
                size += len(chunk)
                if size > MAX_VIDEO_UPLOAD:
                    raise HTTPException(413, "The video is too large (2 GB max).")
                out.write(chunk)
        try:
            picture, sound = engine.video_streams(upload)
        except DubbingError as exc:
            raise HTTPException(422, str(exc))
        if not picture:
            raise HTTPException(422, "This file has no video picture. Use Convert voice for audio files.")
        if not sound:
            raise HTTPException(422, "This video has no audio track to convert.")
        soundtrack = work / "soundtrack.wav"
        try:
            engine.extract_soundtrack(upload, soundtrack, MAX_ISOLATE_SECONDS + 1)
        except DubbingError as exc:
            raise HTTPException(422, str(exc))
        if sf.info(str(soundtrack)).duration > MAX_ISOLATE_SECONDS:
            raise HTTPException(422, f"Use a video of up to {MAX_ISOLATE_SECONDS // 60} minutes.")

        voice, background = work / "voice.wav", work / "background.wav"
        try:
            isolation.isolate(soundtrack, voice, background)
        except Exception:  # e.g. the isolation weights can't be downloaded: convert everything instead
            log.exception("Voice isolation failed; converting the whole soundtrack")
            notes.append(NOTE_WHOLE_SOUNDTRACK)
            voice, background = soundtrack, None
        samples, _ = sf.read(str(voice), dtype="float32")
        if not len(samples) or float(abs(samples).max()) < NO_SPEECH_PEAK:
            raise HTTPException(422, "No speech was found, so there is nothing to convert.")

        output_id, out = _new_output()
        try:
            converted, rate = engine.convert_long(voice, target, work)
            if background is not None:
                engine.mix_voice(background, converted, rate, out)
            else:
                sf.write(str(out), converted, rate, subtype="PCM_16")
        except Exception as exc:
            out.unlink(missing_ok=True)
            log.exception("Voice conversion failed")
            raise HTTPException(500, "Voice conversion failed; see the Voxwell log.") from exc

        video_out = out.with_suffix(".mp4")
        try:
            engine.rebuild_video(upload, out, video_out)
        except DubbingError:  # e.g. a picture codec MP4 can't hold
            log.exception("Could not rebuild the video")
            video_out.unlink(missing_ok=True)
            notes.append(NOTE_AUDIO_ONLY)
        seconds = sf.info(str(out)).duration
    video_url = f"/api/tools/video/{output_id}" if video_out.exists() else None
    return _result(output_id, video_url=video_url, seconds=round(seconds, 3), notes=notes)


@router.post("/isolate")
async def isolate(file: UploadFile = File(...)):
    """Split a recording into the voice and the background (music, noise, effects)."""
    wav, seconds = await _read_audio(file)
    if seconds > MAX_ISOLATE_SECONDS:
        raise HTTPException(422, f"Use a recording of up to {MAX_ISOLATE_SECONDS // 60} minutes.")
    voice_id, voice_out = _new_output()
    background_id, background_out = _new_output()
    source = voice_out.with_suffix(".source.wav")
    source.write_bytes(wav)
    try:
        isolation.isolate(source, voice_out, background_out)
    except isolation.IsolationError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        log.exception("Voice isolation failed")
        raise HTTPException(500, "Voice isolation failed; see the Voxwell log.") from exc
    finally:
        source.unlink(missing_ok=True)
    return {"voice": _result(voice_id), "background": _result(background_id), "seconds": round(seconds, 3)}


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
    except cloning_engine.NothingToSay as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        log.exception("Speech synthesis failed")
        raise HTTPException(500, "Speech synthesis failed; see the Voxwell log.") from exc
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
PACE_CFG = direction.PACE_CFG
exaggeration_for = direction.exaggeration_for


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
        log.exception("The AI director failed")
        raise HTTPException(500, "The AI director failed; see the Voxwell log.") from exc


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
    except cloning_engine.NothingToSay as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        log.exception("Speech synthesis failed")
        raise HTTPException(500, "Speech synthesis failed; see the Voxwell log.") from exc
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
    # Videos can be large, so stream to a temp file. ffprobe sniffs the format, so the upload's name
    # is not used at all: a name like .m3u8 would make it read the upload as a playlist of other files.
    with tempfile.TemporaryDirectory(dir=data_dir("tools")) as tmp:
        path = Path(tmp) / "input"
        with path.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        try:
            return engine.probe(path)
        except DubbingError as exc:
            raise HTTPException(422, str(exc))


@router.get("/video/{output_id}")
def video(output_id: str):
    if not _OUTPUT_ID.match(output_id):
        raise HTTPException(404, "Result not found.")
    path = child_path(data_dir("tools"), f"{output_id}.mp4")
    if not path.exists():
        raise HTTPException(404, "Result not found.")
    return FileResponse(path, media_type="video/mp4")


@router.get("/audio/{output_id}")
def audio(output_id: str):
    if not _OUTPUT_ID.match(output_id):
        raise HTTPException(404, "Result not found.")
    path = child_path(data_dir("tools"), f"{output_id}.wav")
    if not path.exists():
        raise HTTPException(404, "Result not found.")
    return FileResponse(path, media_type="audio/wav")
