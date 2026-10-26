import importlib.util
import re
import shutil
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from voxwell.features.dubbing.fitting import build_srt, srt_time
from voxwell.features.transcription import jobs

router = APIRouter(tags=["transcription"])

_JOB_ID = re.compile(r"^[0-9a-f]{12}$")
_LANGUAGE = re.compile(r"^[a-z]{2,3}$")
_EXT = re.compile(r"^\.[a-z0-9]{1,5}$")


def summary(job: jobs.Job) -> dict:
    return {
        "id": job.id, "title": job.title, "created": job.created, "language": job.language,
        "detected": job.detected, "state": job.state, "percent": job.percent, "error": job.error,
    }


def _job(job_id: str) -> jobs.Job:
    job = jobs.get(job_id) if _JOB_ID.match(job_id) else None
    if job is None:
        raise HTTPException(404, "Unknown transcription.")
    return job


@router.get("/status")
def status():
    return {"ready": importlib.util.find_spec("faster_whisper") is not None}


@router.post("/jobs")
def create_job(file: UploadFile = File(...), language: str = Form("")):
    language = language.strip().lower()
    if language and not _LANGUAGE.match(language):
        raise HTTPException(422, f"Unsupported language '{language}'.")
    name = Path(file.filename or "")
    ext = name.suffix.lower() if _EXT.match(name.suffix.lower()) else ""  # PyAV sniffs the format
    title = name.stem.strip()[:100] or "Transcript"  # display only, never a path
    job = jobs.create(ext, title, language)
    with (job.dir / job.source).open("wb") as out:
        shutil.copyfileobj(file.file, out)
    if (job.dir / job.source).stat().st_size == 0:
        jobs.discard(job)
        raise HTTPException(422, "The uploaded file is empty.")
    jobs.start(job)
    return {"id": job.id}


@router.get("/jobs")
def list_jobs():
    return sorted((summary(j) for j in jobs.list_jobs()), key=lambda s: s["created"], reverse=True)


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = _job(job_id)
    body = summary(job)
    if job.state == "done":
        body["transcript"] = jobs.result(job)
    return body


def _vtt(segments: list[dict]) -> str:
    cues = [f"{srt_time(s['start']).replace(',', '.')} --> {srt_time(s['end']).replace(',', '.')}\n{s['text']}\n" for s in segments]
    return "WEBVTT\n\n" + "\n".join(cues)


EXPORTS = {
    "txt": ("text/plain; charset=utf-8", lambda t: t["text"] + "\n"),
    "srt": ("application/x-subrip; charset=utf-8", lambda t: build_srt([(s["start"], s["end"], s["text"]) for s in t["segments"]])),
    "vtt": ("text/vtt; charset=utf-8", lambda t: _vtt(t["segments"])),
}


@router.get("/jobs/{job_id}/export/{fmt}")
def export(job_id: str, fmt: Literal["txt", "srt", "vtt"]):
    job = _job(job_id)
    if job.state != "done":
        raise HTTPException(409, "The transcription is not finished yet.")
    media_type, render = EXPORTS[fmt]
    return Response(
        render(jobs.result(job)).encode("utf-8"),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="transcript.{fmt}"'},
    )
