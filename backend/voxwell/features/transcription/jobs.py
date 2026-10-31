"""Transcription jobs. They run on background threads, one at a time, and are polled for progress.

Each job keeps job.json (state) and, once done, transcript.json in its folder, so results stay
available after a restart. The uploaded file is deleted when the job ends.
"""

import json
import logging
import shutil
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from voxwell.features.dictation import engine
from voxwell.features.transcription import diarization
from voxwell.paths import child_path, data_dir

log = logging.getLogger(__name__)

STATE_FILE = "job.json"
RESULT_FILE = "transcript.json"
INTERRUPTED = "Interrupted because Voxwell closed. Start the transcription again."


@dataclass
class Job:
    id: str
    dir: Path
    source: str  # uploaded file's name inside dir ("input.<ext>"), never the client's name
    title: str  # display name only
    language: str  # requested ISO code, "" for auto-detect
    created: float
    state: str = "queued"  # queued | running | done | error
    percent: int = 0
    error: str | None = None
    detected: str = ""  # language reported by the model
    speakers: bool = False  # label who speaks (off by default)
    num_speakers: int = 0  # how many speakers there are, 0 to detect it


_jobs: dict[str, Job] = {}
_lock = threading.Lock()
_one_at_a_time = threading.Lock()  # one model, so jobs wait their turn


def _root() -> Path:
    return data_dir("transcription")


def _save(job: Job) -> None:
    state = {k: v for k, v in asdict(job).items() if k not in ("id", "dir")}
    (job.dir / STATE_FILE).write_text(json.dumps(state), encoding="utf-8")


def _load(folder: Path) -> Job | None:
    path = folder / STATE_FILE
    if not path.exists():
        return None
    job = Job(folder.name, folder, **json.loads(path.read_text(encoding="utf-8")))
    if job.state in ("queued", "running"):  # not in memory, so the app closed mid-job
        job.state, job.error = "error", INTERRUPTED
        (folder / job.source).unlink(missing_ok=True)
        _save(job)
    return job


def create(ext: str, title: str, language: str, *, speakers: bool = False, num_speakers: int = 0) -> Job:
    job_id = uuid.uuid4().hex[:12]
    folder = _root() / job_id
    folder.mkdir(parents=True)
    job = Job(job_id, folder, f"input{ext}", title, language, time.time(), speakers=speakers, num_speakers=num_speakers)
    with _lock:
        _jobs[job_id] = job
    return job


def get(job_id: str) -> Job | None:
    """Look up a job by an already-validated id, loading it from disk after a restart."""
    with _lock:
        job = _jobs.get(job_id)
        if job is None and (job := _load(child_path(_root(), job_id))):
            _jobs[job_id] = job
        return job


def list_jobs() -> list[Job]:
    return [job for folder in _root().iterdir() if (job := get(folder.name))]


def result(job: Job) -> dict:
    """The saved transcript ({text, language, segments}) of a finished job."""
    return json.loads((job.dir / RESULT_FILE).read_text(encoding="utf-8"))


def discard(job: Job) -> None:
    """Forget a job and delete its folder."""
    with _lock:
        _jobs.pop(job.id, None)
    shutil.rmtree(job.dir, ignore_errors=True)


def rename(job: Job, title: str) -> None:
    job.title = title
    _save(job)


def delete(job: Job) -> None:
    """Delete a finished or failed job; ValueError while it is still working."""
    if job.state in ("queued", "running"):
        raise ValueError("The transcription is still running.")
    discard(job)


def _label_speakers(job: Job, data: dict) -> None:
    """Add a "speaker" to each segment of `data`. A failure is recorded in data["speakers_error"], so the
    transcript itself is still saved."""
    try:
        turns = diarization.diarize(
            job.dir / job.source, job.num_speakers, on_progress=lambda f: setattr(job, "percent", 80 + int(f * 19))
        )
        labels = diarization.assign_speakers([(s["start"], s["end"]) for s in data["segments"]], turns)
    except diarization.DiarizationError as exc:  # written for the user; the plain transcript stays
        data["speakers_error"] = f"Speaker labels failed: {exc}"
        return
    except Exception:  # an unexpected failure also leaves the plain transcript
        log.exception("Speaker labels failed")
        data["speakers_error"] = "Speaker labels failed; see the Voxwell log."
        return
    if not any(labels):
        data["speakers_error"] = "No speakers were found in the file."
    for segment, label in zip(data["segments"], labels):
        if label:
            segment["speaker"] = label


def _work(job: Job) -> None:
    with _one_at_a_time:
        job.state = "running"
        _save(job)
        try:
            t = engine.transcribe(
                job.dir / job.source, job.language or None,
                on_progress=lambda f: setattr(job, "percent", int(f * (80 if job.speakers else 99))),
            )
            segments = [{"start": s.start, "end": s.end, "text": s.text} for s in t.segments if s.text]
            if not segments:
                raise engine.AudioError("No speech was found in the file.")
            data = {"text": t.text, "language": t.language, "segments": segments}
            if job.speakers:
                _label_speakers(job, data)
            (job.dir / RESULT_FILE).write_bytes(json.dumps(data, ensure_ascii=False).encode("utf-8"))
            job.state, job.percent, job.detected = "done", 100, t.language
        except engine.AudioError as exc:
            job.state, job.error = "error", str(exc)
        except Exception:  # an unexpected failure: the details go to the log, not to the user
            log.exception("Transcription job failed")
            job.state, job.error = "error", "Transcription failed; see the Voxwell log."
        (job.dir / job.source).unlink(missing_ok=True)
        _save(job)


def start(job: Job) -> None:
    _save(job)
    threading.Thread(target=_work, args=(job,), daemon=True).start()
