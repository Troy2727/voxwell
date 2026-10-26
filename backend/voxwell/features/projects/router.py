"""Projects: everything you have made (speech, stories, audiobooks, dubs, transcripts), newest first.

Each kind stays owned by its feature (voice_cloning.history, stories.jobs, audiobook.books,
dubbing.jobs, transcription.jobs); this router only lists, renames and deletes through them.
"""

import re
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from voxwell import voices
from voxwell.features.audiobook import books as audiobooks
from voxwell.features.audiobook.router import summary as audiobook_summary
from voxwell.features.dubbing import jobs as dub_jobs
from voxwell.features.stories import jobs as story_jobs
from voxwell.features.stories.router import summary as story_summary
from voxwell.features.transcription import jobs as transcript_jobs
from voxwell.features.voice_cloning import history

router = APIRouter(tags=["projects"])

Kind = Literal["speech", "story", "audiobook", "dub", "transcript"]
MAX_TITLE = 100
_JOB_ID = re.compile(r"^[0-9a-f]{12}$")


class RenameRequest(BaseModel):
    title: str


def _speech(clip: history.Clip) -> dict:
    return {
        "kind": "speech", "id": clip.id, "title": clip.title, "created": clip.created,
        "language": clip.language, "voice": clip.voice, "text": clip.text,
        "audio_url": f"/api/voice_cloning/audio/{clip.id}",
    }


def _voice_name(voice_id: str) -> str:
    if voice_id == "original":
        return "Original speaker"
    try:
        return voices.get_voice(voice_id).name
    except KeyError:
        return "Deleted voice"


def _dub(job: dub_jobs.Job) -> dict:
    return {
        "kind": "dub", "id": job.id, "title": job.title, "created": job.created,
        "language": job.target, "voice": _voice_name(job.voice),
        "state": job.state, "step": job.step, "percent": job.percent, "error": job.error,
        "video_url": f"/api/dubbing/jobs/{job.id}/video",
        "subtitles_url": f"/api/dubbing/jobs/{job.id}/subtitles",
    }


def _transcript(job: transcript_jobs.Job) -> dict:
    base = f"/api/transcription/jobs/{job.id}/export"
    return {
        "kind": "transcript", "id": job.id, "title": job.title, "created": job.created,
        "language": job.detected or job.language or "auto", "voice": "",
        "state": job.state, "step": "Transcribing", "percent": job.percent, "error": job.error,
        "text": transcript_jobs.result(job)["text"] if job.state == "done" else "",
        "exports": {fmt: f"{base}/{fmt}" for fmt in ("txt", "srt", "vtt")},
    }


def _story(job: story_jobs.Job) -> dict:
    voices_used = sorted({_voice_name(v) if v != story_jobs.DEFAULT_VOICE else "Default voice" for v in job.cast.values()})
    return {**story_summary(job), "kind": "story", "voice": ", ".join(voices_used), "speakers": list(job.cast)}


# Job-backed kinds: module with get/list_jobs/rename/delete, and how to show one job.
def _audiobook(book: audiobooks.Book) -> dict:
    voice = "Default voice" if book.voice == audiobooks.DEFAULT_VOICE else _voice_name(book.voice)
    done = sum(1 for ch in book.chapters if ch.status == "done")
    return {**audiobook_summary(book), "kind": "audiobook", "voice": voice, "chapters_done": done}


JOB_KINDS = {
    "story": (story_jobs, _story),
    "audiobook": (audiobooks, _audiobook),
    "dub": (dub_jobs, _dub),
    "transcript": (transcript_jobs, _transcript),
}


def _job(kind: str, item_id: str):
    module, _ = JOB_KINDS[kind]
    job = module.get(item_id) if _JOB_ID.match(item_id) else None
    if job is None:
        raise HTTPException(404, "Project not found.")
    return job


@router.get("/status")
def status():
    return {"ready": True}


@router.get("/items")
def items():
    found = [_speech(c) for c in history.list_clips()]
    for module, show in JOB_KINDS.values():
        found += [show(j) for j in module.list_jobs()]
    return sorted(found, key=lambda item: item["created"], reverse=True)


@router.patch("/items/{kind}/{item_id}")
def rename(kind: Kind, item_id: str, req: RenameRequest):
    title = req.title.strip()
    if not title:
        raise HTTPException(422, "Title is required.")
    if len(title) > MAX_TITLE:
        raise HTTPException(422, f"Title is too long ({MAX_TITLE} characters max).")
    if kind == "speech":
        try:
            return _speech(history.rename(item_id, title))
        except KeyError:
            raise HTTPException(404, "Project not found.")
    module, show = JOB_KINDS[kind]
    job = _job(kind, item_id)
    module.rename(job, title)
    return show(job)


@router.delete("/items/{kind}/{item_id}")
def delete(kind: Kind, item_id: str):
    if kind == "speech":
        try:
            history.delete(item_id)
        except KeyError:
            raise HTTPException(404, "Project not found.")
    else:
        module, _ = JOB_KINDS[kind]
        try:
            module.delete(_job(kind, item_id))
        except ValueError as exc:
            raise HTTPException(409, str(exc))
    return {"deleted": item_id}
