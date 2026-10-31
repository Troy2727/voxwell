import importlib.util
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from voxwell.features.dictation import engine
from voxwell.features.dubbing.fitting import build_srt, srt_time
from voxwell.features.transcription import alignment, diarization, editing, jobs
from voxwell.paths import attachment, data_dir, download_name

router = APIRouter(tags=["transcription"])

_JOB_ID = re.compile(r"^[0-9a-f]{12}$")
_LANGUAGE = re.compile(r"^[a-z]{2,3}$")


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
def create_job(file: UploadFile = File(...), language: str = Form(""), speakers: bool = Form(False), num_speakers: int = Form(0)):
    language = language.strip().lower()
    if language and not _LANGUAGE.match(language):
        raise HTTPException(422, f"Unsupported language '{language}'.")
    if not 0 <= num_speakers <= diarization.MAX_SPEAKERS:
        raise HTTPException(422, f"The number of speakers must be 0 (detect) or 1 to {diarization.MAX_SPEAKERS}.")
    title = Path(file.filename or "").stem.strip()[:100] or "Transcript"  # display only, never a path
    # A fixed suffix: PyAV sniffs the format, and a name like .m3u8 would make it read the upload
    # as a playlist of other files on this computer.
    job = jobs.create(".audio", title, language, speakers=speakers, num_speakers=num_speakers if speakers else 0)
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
    def text(s: dict) -> str:  # WebVTT's voice span names the speaker
        return f"<v {s['speaker']}>{s['text']}" if s.get("speaker") else s["text"]

    cues = [f"{srt_time(s['start']).replace(',', '.')} --> {srt_time(s['end']).replace(',', '.')}\n{text(s)}\n" for s in segments]
    return "WEBVTT\n\n" + "\n".join(cues)


def _txt(transcript: dict) -> str:
    """The plain text; with speaker labels, one paragraph per turn: "Speaker 1: ..."."""
    segments = transcript["segments"]
    if not any(s.get("speaker") for s in segments):
        return transcript["text"] + "\n"
    turns: list[list[str]] = []  # [speaker, text]
    for s in segments:
        speaker = s.get("speaker") or ""
        if turns and turns[-1][0] == speaker:
            turns[-1][1] += " " + s["text"]
        else:
            turns.append([speaker, s["text"]])
    return "\n\n".join(f"{speaker}: {text}" if speaker else text for speaker, text in turns) + "\n"


def _srt_text(s: dict) -> str:
    return f"{s['speaker']}: {s['text']}" if s.get("speaker") else s["text"]


EXPORTS = {
    "txt": ("text/plain; charset=utf-8", _txt),
    "srt": ("application/x-subrip; charset=utf-8", lambda t: build_srt([(s["start"], s["end"], _srt_text(s)) for s in t["segments"]])),
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
        headers=attachment(download_name(job.title, f".{fmt}", "Transcript")),
    )


MAX_SCRIPT_CHARS = 200_000


@router.post("/align")
def align_script(
    file: UploadFile = File(...),
    script: str = Form(...),
    language: str = Form(""),
    max_chars: int = Form(42),
    max_seconds: float = Form(6.0),
):
    """Time a script against its recording: word timings plus SRT and VTT subtitles. Runs while the request waits."""
    language = language.strip().lower()
    if language and not _LANGUAGE.match(language):
        raise HTTPException(422, f"Unsupported language '{language}'.")
    if not alignment.script_words(script):
        raise HTTPException(422, "Paste the script to align.")
    if len(script) > MAX_SCRIPT_CHARS:
        raise HTTPException(422, f"The script is too long (limit {MAX_SCRIPT_CHARS:,} characters).")
    if not 10 <= max_chars <= 200 or not 1 <= max_seconds <= 30:
        raise HTTPException(422, "Use 10 to 200 characters and 1 to 30 seconds per subtitle.")
    fd, name = tempfile.mkstemp(suffix=".audio", dir=data_dir("alignment"))  # the upload's name is never used, as in create_job
    path = Path(name)
    try:
        with os.fdopen(fd, "wb") as out:
            shutil.copyfileobj(file.file, out)
        if path.stat().st_size == 0:
            raise HTTPException(422, "The uploaded file is empty.")
        try:
            with jobs._one_at_a_time:  # one model, so it waits for any transcription in progress
                timings = engine.transcribe_words(path, language or None)
        except engine.AudioError as exc:
            raise HTTPException(422, str(exc))
        except Exception as exc:
            raise HTTPException(500, f"Alignment failed: {exc}")
    finally:
        path.unlink(missing_ok=True)
    result = alignment.align(script, [(w.start, w.end, w.text) for w in timings.words])
    cues = alignment.build_cues(result.words, max_chars, max_seconds)
    entries = [{"start": c.start, "end": c.end, "text": c.text} for c in cues]
    return {
        "language": timings.language,
        "words": [{"text": w.text, "start": w.start, "end": w.end, "matched": w.matched} for w in result.words],
        "cues": entries,
        "srt": EXPORTS["srt"][1]({"segments": entries}),
        "vtt": EXPORTS["vtt"][1]({"segments": entries}),
        "matched": result.matched,
        "total": len(result.words),
        "fallback": result.fallback,
    }


MAX_EDIT_CHARS = 200_000


class EditRequest(BaseModel):
    text: str | None = None  # the text to edit, or...
    job_id: str | None = None  # ...a finished transcription whose text is edited
    preset: str | None = None  # one of GET /edit/presets, or...
    instruction: str | None = None  # ...your own wording


@router.get("/edit/presets")
def edit_presets():
    return [{"id": k, "label": label, "instruction": text} for k, (label, text) in editing.PRESETS.items()]


@router.post("/edit")
def edit(req: EditRequest):
    if (req.text is None) == (req.job_id is None):
        raise HTTPException(422, "Give either text or job_id.")
    if (req.preset is None) == (req.instruction is None):
        raise HTTPException(422, "Give either preset or instruction.")
    if req.preset is not None:
        if req.preset not in editing.PRESETS:
            raise HTTPException(422, f"Unknown preset '{req.preset}'. Presets: {', '.join(editing.PRESETS)}.")
        instruction = editing.PRESETS[req.preset][1]
    else:
        instruction = " ".join(req.instruction.split())
        if not instruction or len(instruction) > editing.MAX_INSTRUCTION:
            raise HTTPException(422, f"Write an instruction of 1 to {editing.MAX_INSTRUCTION} characters.")
    if req.job_id is not None:
        job = _job(req.job_id)
        if job.state != "done":
            raise HTTPException(409, "The transcription is not finished yet.")
        text = jobs.result(job)["text"]
    else:
        text = req.text
    if not text.strip():
        raise HTTPException(422, "There is no text to edit.")
    if len(text) > MAX_EDIT_CHARS:
        raise HTTPException(422, f"The text is too long to edit (limit {MAX_EDIT_CHARS:,} characters).")
    try:
        edited = editing.edit_text(text, instruction)
    except Exception as exc:  # the model could not load or run: say so without a traceback
        raise HTTPException(500, f"The AI editor failed: {exc}")
    return {"text": edited.text, "chunks": edited.chunks, "kept": edited.kept}
