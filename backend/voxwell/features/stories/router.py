import importlib.util
import re
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from voxwell import voices
from voxwell.features.audio_effects.dsp import Effects
from voxwell.features.stories import jobs, subtitles
from voxwell.features.stories.script import NARRATOR, ScriptError, parse, speakers
from voxwell.features.voice_cloning.engine import LANGUAGES
from voxwell.paths import download_name

router = APIRouter(tags=["stories"])

MAX_TITLE = 100
MAX_SUBTITLE_BYTES = 2 * 1024 * 1024
_JOB_ID = re.compile(r"^[0-9a-f]{12}$")


class ParseRequest(BaseModel):
    script: str


class StoryRequest(BaseModel):
    title: str = ""
    language: str = "en"
    script: str
    cast: dict[str, str] = {}  # speaker -> voice id; missing speakers use the default voice
    effects: Effects | None = None


def summary(job: jobs.Job) -> dict:
    return {
        "id": job.id, "title": job.title, "created": job.created, "language": job.language,
        "state": job.state, "step": job.step, "percent": job.percent, "error": job.error,
        "audio_url": f"/api/stories/jobs/{job.id}/audio",
    }


def _job(job_id: str) -> jobs.Job:
    job = jobs.get(job_id) if _JOB_ID.match(job_id) else None
    if job is None:
        raise HTTPException(404, "Unknown story.")
    return job


@router.get("/status")
def status():
    return {"ready": importlib.util.find_spec("chatterbox") is not None, "languages": LANGUAGES}


@router.post("/parse")
def parse_script(req: ParseRequest):
    try:
        lines = parse(req.script)
    except ScriptError as exc:
        raise HTTPException(422, str(exc))
    return {"speakers": speakers(lines), "lines": len(lines)}


@router.post("/jobs")
def create_job(req: StoryRequest):
    if req.language not in LANGUAGES:
        raise HTTPException(422, f"Unsupported language '{req.language}'.")
    try:
        lines = parse(req.script)
    except ScriptError as exc:
        raise HTTPException(422, str(exc))
    cast = {}
    for speaker in speakers(lines):
        voice = req.cast.get(speaker, jobs.DEFAULT_VOICE)
        if voice != jobs.DEFAULT_VOICE:
            try:
                voices.voice_audio_path(voice)
            except KeyError:
                raise HTTPException(422, f"Unknown voice for {speaker}.")
        cast[speaker] = voice
    title = req.title.strip()[:MAX_TITLE] or lines[0].text[:60]
    job = jobs.create(title, req.language, req.script, cast, req.effects.model_dump() if req.effects else None)
    jobs.start(job)
    return {"id": job.id}


@router.post("/subtitles")
async def create_from_subtitles(file: UploadFile = File(...), language: str = Form("en"), voice_id: str = Form(""), title: str = Form("")):
    """Speak a subtitle file in one voice, each cue at its time."""
    data = await file.read(MAX_SUBTITLE_BYTES + 1)
    if len(data) > MAX_SUBTITLE_BYTES:
        raise HTTPException(413, "The subtitle file is too large (2 MB max).")
    if language not in LANGUAGES:
        raise HTTPException(422, f"Unsupported language '{language}'.")
    if voice_id:
        try:
            voices.voice_audio_path(voice_id)
        except KeyError:
            raise HTTPException(422, "Unknown voice.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")  # common for older Windows subtitle files
    try:
        cues = subtitles.parse(text)
    except ScriptError as exc:
        raise HTTPException(422, str(exc))
    name = title.strip()[:MAX_TITLE] or Path(file.filename or "").stem.strip()[:MAX_TITLE] or cues[0].text[:60]
    job = jobs.create(name, language, text, {NARRATOR: voice_id or jobs.DEFAULT_VOICE}, timed=True)
    jobs.start(job)
    return {"id": job.id}


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    return summary(_job(job_id))


@router.get("/jobs/{job_id}/audio")
def audio(job_id: str):
    job = _job(job_id)
    if job.state != "done":
        raise HTTPException(409, "The story is not finished yet.")
    return FileResponse(jobs.audio_path(job), media_type="audio/wav", filename=download_name(job.title, ".wav", "Story"))
