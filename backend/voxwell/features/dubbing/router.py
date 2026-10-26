import re
import shutil
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from voxwell import voices
from voxwell.features.dubbing import ffmpeg, jobs
from voxwell.features.dubbing.translate import LANGUAGES as TRANSLATION_LANGUAGES
from voxwell.features.voice_cloning.engine import LANGUAGES as SPEECH_LANGUAGES
from voxwell.paths import data_dir

router = APIRouter(tags=["dubbing"])

# A dub needs both translation into and speech synthesis in the target language.
LANGUAGES = TRANSLATION_LANGUAGES & SPEECH_LANGUAGES.keys()

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
_JOB_ID = re.compile(r"^[0-9a-f]{12}$")


@router.get("/status")
def status():
    try:
        ffmpeg.ffmpeg_path()
        return {"ready": True, "languages": sorted(LANGUAGES)}
    except ffmpeg.DubbingError as exc:
        return {"ready": False, "reason": str(exc), "languages": sorted(LANGUAGES)}


@router.post("/jobs")
def create_job(
    file: UploadFile = File(...),
    target_language: str = Form(...),
    voice: str = Form("original"),
):
    target = target_language.strip().lower()
    if target not in LANGUAGES:
        raise HTTPException(422, f"Unsupported target language '{target_language}'.")
    ext = Path(file.filename or "").suffix.lower()  # only the extension is used, never the name
    if ext not in VIDEO_EXTS:
        raise HTTPException(422, f"Unsupported video type '{ext}'. Use one of: {', '.join(sorted(VIDEO_EXTS))}.")
    if voice != "original":
        try:
            voices.voice_audio_path(voice)
        except KeyError:
            raise HTTPException(422, f"Unknown voice '{voice}'.")
    job = jobs.create(data_dir("dubbing", "jobs"), ext, target, voice)
    with job.video.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    if job.video.stat().st_size == 0:
        jobs.discard(job)
        raise HTTPException(422, "The uploaded file is empty.")
    jobs.start(job)
    return {"id": job.id}


def _job(job_id: str) -> jobs.Job:
    job = jobs.get(job_id) if _JOB_ID.match(job_id) else None
    if job is None:
        raise HTTPException(404, "Unknown job.")
    return job


@router.get("/jobs/{job_id}")
def job_status(job_id: str):
    job = _job(job_id)
    return {"id": job.id, "state": job.state, "step": job.step, "percent": job.percent, "error": job.error}


def _output(job_id: str, key: str, media_type: str, name: str):
    job = _job(job_id)
    if job.state != "done":
        raise HTTPException(409, "The job is not finished yet.")
    return FileResponse(job.outputs[key], media_type=media_type, filename=name)


@router.get("/jobs/{job_id}/video")
def job_video(job_id: str):
    return _output(job_id, "video", "video/mp4", "dubbed.mp4")


@router.get("/jobs/{job_id}/subtitles")
def job_subtitles(job_id: str):
    return _output(job_id, "subtitles", "application/x-subrip", "subtitles.srt")
