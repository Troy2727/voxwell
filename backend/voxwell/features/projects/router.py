"""Projects: everything you have made, newest first.

Each kind stays owned by its feature (voice_cloning.history, stories.jobs, audiobook.books,
dubbing.jobs, transcription.jobs, music.history, sound.history, and voxwell.results for Tools,
Audio effects and Translation); this router only lists, renames and deletes through them.
"""

import re
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from voxwell import results, voices
from voxwell.features.audiobook import books as audiobooks
from voxwell.features.audiobook.router import summary as audiobook_summary
from voxwell.features.dubbing import jobs as dub_jobs
from voxwell.features.music import history as music
from voxwell.features.music.router import _settle as settle_track
from voxwell.features.sound import history as sounds
from voxwell.features.stories import jobs as story_jobs
from voxwell.features.stories.router import summary as story_summary
from voxwell.features.transcription import jobs as transcript_jobs
from voxwell.features.voice_cloning import history

router = APIRouter(tags=["projects"])

Kind = Literal[
    "speech", "story", "audiobook", "dub", "transcript", "music", "sound",
    "conversion", "video", "isolation", "fit", "effects", "translation",
]
RESULT_KINDS = {  # kept results: kind -> the feature whose folder holds them
    "conversion": "tools", "video": "tools", "isolation": "tools", "fit": "tools",
    "effects": "audio_effects", "translation": "translation",
}
_MUSIC_STATE = {"queued": "queued", "generating": "running", "done": "done", "failed": "error"}
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


def _file(label: str, url: str, video: bool = False) -> dict:
    return {"label": label, "url": url, "video": video}


def _music(track: music.Track) -> dict:
    track = settle_track(track)
    files = []
    if track.status == "done":
        files.append(_file("Song", f"/api/music/audio/{track.id}"))
        if track.stems:
            files += [_file(part.title(), f"/api/music/audio/{track.id}?part={part}") for part in ("vocals", "instrumental")]
    return {
        "kind": "music", "id": track.id, "title": track.title or results.title_from(track.prompt, "Music"),
        "created": track.created, "language": track.language, "voice": "",
        "state": _MUSIC_STATE.get(track.status, "error"), "step": track.stage, "percent": round(track.progress * 100),
        "error": track.error or None, "text": track.prompt, "files": files,
    }


def _sound(sound: sounds.Sound) -> dict:
    return {
        "kind": "sound", "id": sound.id, "title": sound.title or results.title_from(sound.prompt, "Sound effect"),
        "created": sound.created, "language": "", "voice": "",
        "state": "done", "step": "", "percent": 100, "error": None,
        "text": sound.prompt, "files": [_file("Sound", f"/api/sound/audio/{sound.id}")],
    }


def _kept(result: results.Result) -> dict:
    def url(name: str) -> str:
        stem, ext = name.rsplit(".", 1)
        return f"/api/{result.feature}/{'video' if ext == 'mp4' else 'audio'}/{stem}"

    return {
        "kind": result.kind, "id": result.id, "title": result.title, "created": result.created,
        "language": result.language, "voice": _voice_name(result.voice) if result.voice else "",
        "state": "done", "step": "", "percent": 100, "error": None, "text": result.text,
        "files": [_file(label, url(name), name.endswith(".mp4")) for label, name in result.files.items()],
    }


def _result(kind: str, item_id: str) -> results.Result:
    try:
        result = results.get(RESULT_KINDS[kind], item_id)
    except KeyError:
        raise HTTPException(404, "Project not found.")
    if result.kind != kind:
        raise HTTPException(404, "Project not found.")
    return result


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
    found += [_music(t) for t in music.list_tracks()]
    found += [_sound(s) for s in sounds.list_sounds()]
    found += [_kept(r) for r in results.list_results()]
    return sorted(found, key=lambda item: item["created"], reverse=True)


@router.patch("/items/{kind}/{item_id}")
def rename(kind: Kind, item_id: str, req: RenameRequest):
    title = req.title.strip()
    if not title:
        raise HTTPException(422, "Title is required.")
    if len(title) > MAX_TITLE:
        raise HTTPException(422, f"Title is too long ({MAX_TITLE} characters max).")
    try:
        if kind == "speech":
            return _speech(history.rename(item_id, title))
        if kind == "music":
            return _music(music.update(item_id, title=title))
        if kind == "sound":
            return _sound(sounds.rename(item_id, title))
    except KeyError:
        raise HTTPException(404, "Project not found.")
    if kind in RESULT_KINDS:
        return _kept(results.rename(RESULT_KINDS[kind], _result(kind, item_id).id, title))
    module, show = JOB_KINDS[kind]
    job = _job(kind, item_id)
    module.rename(job, title)
    return show(job)


@router.delete("/items/{kind}/{item_id}")
def delete(kind: Kind, item_id: str):
    if kind in ("speech", "music", "sound"):
        try:
            {"speech": history.delete, "music": music.delete, "sound": sounds.delete}[kind](item_id)
        except KeyError:
            raise HTTPException(404, "Project not found.")
    elif kind in RESULT_KINDS:
        results.delete(RESULT_KINDS[kind], _result(kind, item_id).id)
    else:
        module, _ = JOB_KINDS[kind]
        try:
            module.delete(_job(kind, item_id))
        except ValueError as exc:
            raise HTTPException(409, str(exc))
    return {"deleted": item_id}
