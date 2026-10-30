"""Job registry; jobs run on a background thread and are polled for progress.

Each job's state is saved to job.json in its folder, so finished dubs stay downloadable after
a restart. When a job ends, everything but its outputs (input copy, clips, extracted audio)
is deleted to keep disk use down.
"""

import json
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from voxwell.features.dubbing import pipeline
from voxwell.features.dubbing.ffmpeg import DubbingError
from voxwell.paths import data_dir

STATE_FILE = "job.json"
INTERRUPTED = "Interrupted because Voxwell closed. Start the dub again."


@dataclass
class Job:
    id: str
    dir: Path
    video: Path
    target: str
    voice: str
    state: str = "queued"  # queued | running | done | error
    step: str = "Queued"
    percent: int = 0
    error: str | None = None
    outputs: dict[str, Path] = field(default_factory=dict)
    title: str = "Dub"  # display name only, never used as a path
    created: float = 0.0
    speakers: bool = False  # keep each speaker's own voice and label them (off by default)
    num_speakers: int = 0  # how many speakers there are, 0 to detect it


_jobs: dict[str, Job] = {}
_lock = threading.Lock()
_one_at_a_time = threading.Lock()  # dubs share the models and GPU, so they wait their turn


def _save(job: Job) -> None:
    state = {
        "video": job.video.name, "target": job.target, "voice": job.voice,
        "state": job.state, "step": job.step, "percent": job.percent, "error": job.error,
        "outputs": {key: path.name for key, path in job.outputs.items()},
        "title": job.title, "created": job.created,
        "speakers": job.speakers, "num_speakers": job.num_speakers,
    }
    (job.dir / STATE_FILE).write_text(json.dumps(state), encoding="utf-8")


def _load(folder: Path) -> Job | None:
    path = folder / STATE_FILE
    if not path.exists():
        return None
    s = json.loads(path.read_text(encoding="utf-8"))
    job = Job(
        folder.name, folder, folder / s["video"], s["target"], s["voice"], s["state"], s["step"],
        s["percent"], s["error"], {key: folder / name for key, name in s["outputs"].items()},
        # Jobs saved before titles existed fall back to a generic title and the file's age.
        s.get("title", "Dub"), s.get("created", path.stat().st_mtime),
        s.get("speakers", False), s.get("num_speakers", 0),
    )
    if job.state in ("queued", "running"):  # not in memory, so the app closed mid-job
        job.state, job.error = "error", INTERRUPTED
        _cleanup(job)
        _save(job)
    return job


def _cleanup(job: Job) -> None:
    keep = {job.dir / STATE_FILE, *job.outputs.values()}
    for path in job.dir.iterdir():
        if path not in keep:
            shutil.rmtree(path) if path.is_dir() else path.unlink()


def create(dir_root: Path, ext: str, target: str, voice: str, title: str = "Dub", *, speakers: bool = False, num_speakers: int = 0) -> Job:
    job_id = uuid.uuid4().hex[:12]
    folder = dir_root / job_id
    folder.mkdir(parents=True)
    job = Job(job_id, folder, folder / f"input{ext}", target, voice, title=title, created=time.time(), speakers=speakers, num_speakers=num_speakers)
    with _lock:
        _jobs[job_id] = job
    return job


def list_jobs() -> list[Job]:
    return [job for folder in data_dir("dubbing", "jobs").iterdir() if (job := get(folder.name))]


def rename(job: Job, title: str) -> None:
    job.title = title
    _save(job)


def delete(job: Job) -> None:
    """Delete a finished or failed job; ValueError while it is still working."""
    if job.state in ("queued", "running"):
        raise ValueError("The dub is still running.")
    discard(job)


def discard(job: Job) -> None:
    """Forget a job that was never started and delete its folder."""
    with _lock:
        _jobs.pop(job.id, None)
    shutil.rmtree(job.dir, ignore_errors=True)


def get(job_id: str) -> Job | None:
    """Look up a job by an already-validated id, loading it from disk after a restart."""
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            job = _load(data_dir("dubbing", "jobs") / job_id)
            if job is not None:
                _jobs[job_id] = job
        return job


def _update(job: Job, step: str, percent: int) -> None:
    job.step, job.percent = step, percent


def _work(job: Job) -> None:
    with _one_at_a_time:
        job.state = "running"
        _save(job)
        try:
            extra = {"speakers": True, "num_speakers": job.num_speakers} if job.speakers else {}
            job.outputs = pipeline.run(job.dir, job.video, job.target, job.voice, lambda s, p: _update(job, s, p), **extra)
            job.state, job.step, job.percent = "done", "Done", 100
        except DubbingError as exc:
            job.state, job.error = "error", str(exc)
        except NotImplementedError:
            job.state, job.error = "error", f"{job.step} is not available yet."
        except Exception as exc:  # surface any engine failure as a job error, without a traceback
            job.state, job.error = "error", f"{job.step} failed: {exc}"
        _cleanup(job)
        _save(job)


def start(job: Job) -> None:
    job.step = "Waiting for other dubs"
    _save(job)
    threading.Thread(target=_work, args=(job,), daemon=True).start()
