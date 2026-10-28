import re
import shutil
from pathlib import Path
from typing import BinaryIO

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from voxwell import voices
from voxwell.features.dubbing import ffmpeg, jobs
from voxwell.features.dubbing.translate import LANGUAGES as TRANSLATION_LANGUAGES
from voxwell.features.voice_cloning.engine import LANGUAGES as SPEECH_LANGUAGES
from voxwell.paths import data_dir, download_name

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


def check_settings(target_language: str, voice: str) -> str:
    """Validate a dub's language and voice; returns the normalized language code."""
    target = target_language.strip().lower()
    if target not in LANGUAGES:
        raise HTTPException(422, f"Unsupported target language '{target_language}'.")
    if voice != "original":
        try:
            voices.voice_audio_path(voice)
        except KeyError:
            raise HTTPException(422, f"Unknown voice '{voice}'.")
    return target


def start_dub(source: BinaryIO, filename: str, target_language: str, voice: str) -> jobs.Job:
    """Validate, copy `source` into a new job and queue it. Used by uploads and Batch."""
    target = check_settings(target_language, voice)
    name = Path(filename or "")
    ext = name.suffix.lower()  # only the extension is used as a path, never the name
    if ext not in VIDEO_EXTS:
        raise HTTPException(422, f"Unsupported video type '{ext}'. Use one of: {', '.join(sorted(VIDEO_EXTS))}.")
    title = name.stem.strip()[:100] or "Dub"  # display only
    job = jobs.create(data_dir("dubbing", "jobs"), ext, target, voice, title)
    with job.video.open("wb") as out:
        shutil.copyfileobj(source, out)
    if job.video.stat().st_size == 0:
        jobs.discard(job)
        raise HTTPException(422, "The file is empty.")
    jobs.start(job)
    return job


@router.post("/jobs")
def create_job(
    file: UploadFile = File(...),
    target_language: str = Form(...),
    voice: str = Form("original"),
):
    return {"id": start_dub(file.file, file.filename or "", target_language, voice).id}


def _job(job_id: str) -> jobs.Job:
    job = jobs.get(job_id) if _JOB_ID.match(job_id) else None
    if job is None:
        raise HTTPException(404, "Unknown job.")
    return job


@router.get("/jobs/{job_id}")
def job_status(job_id: str):
    job = _job(job_id)
    return {"id": job.id, "state": job.state, "step": job.step, "percent": job.percent, "error": job.error}


def _output(job_id: str, key: str, media_type: str, ext: str):
    job = _job(job_id)
    if job.state != "done":
        raise HTTPException(409, "The job is not finished yet.")
    # Named like the watch folder's copies: "<video>.<language>.mp4".
    name = download_name(job.title, f".{job.target}{ext}", "Dub")
    return FileResponse(job.outputs[key], media_type=media_type, filename=name)


@router.get("/jobs/{job_id}/video")
def job_video(job_id: str):
    return _output(job_id, "video", "video/mp4", ".mp4")


@router.get("/jobs/{job_id}/subtitles")
def job_subtitles(job_id: str):
    return _output(job_id, "subtitles", "application/x-subrip; charset=utf-8", ".srt")
