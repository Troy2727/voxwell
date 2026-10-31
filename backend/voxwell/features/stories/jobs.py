"""Story jobs: speak every line of a script in its speaker's voice and join them into one WAV.

Jobs run on background threads, one at a time, and are polled for progress. Each job keeps
job.json (script, cast, state) and, once done, story.wav in its folder.
"""

import io
import json
import shutil
import threading
import time
import uuid
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

from voxwell import voices
from voxwell.features.audio_effects.dsp import Effects, apply_to_wav
from voxwell.features.stories.script import parse
from voxwell.features.voice_cloning import engine
from voxwell.paths import child_path, data_dir

STATE_FILE = "job.json"
AUDIO_FILE = "story.wav"
PAUSE_SECONDS = 0.4  # silence between lines
DEFAULT_VOICE = "default"
INTERRUPTED = "Interrupted because Voxwell closed. Generate the story again."


@dataclass
class Job:
    id: str
    dir: Path
    title: str
    language: str
    script: str
    cast: dict[str, str]  # speaker -> voice id, or DEFAULT_VOICE
    created: float
    state: str = "queued"  # queued | running | done | error
    step: str = "Waiting for other stories"
    percent: int = 0
    error: str | None = None
    effects: dict | None = None  # Effects settings applied to the finished story


_jobs: dict[str, Job] = {}
_lock = threading.Lock()
_one_at_a_time = threading.Lock()


def _root() -> Path:
    return data_dir("stories")


def _save(job: Job) -> None:
    state = {k: v for k, v in asdict(job).items() if k not in ("id", "dir")}
    (job.dir / STATE_FILE).write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def _load(folder: Path) -> Job | None:
    path = folder / STATE_FILE
    if not path.exists():
        return None
    job = Job(folder.name, folder, **json.loads(path.read_text(encoding="utf-8")))
    if job.state in ("queued", "running"):  # not in memory, so the app closed mid-job
        job.state, job.error = "error", INTERRUPTED
        _save(job)
    return job


def create(title: str, language: str, script: str, cast: dict[str, str], effects: dict | None = None) -> Job:
    job_id = uuid.uuid4().hex[:12]
    folder = _root() / job_id
    folder.mkdir(parents=True)
    job = Job(job_id, folder, title, language, script, cast, time.time(), effects=effects)
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


def audio_path(job: Job) -> Path:
    return job.dir / AUDIO_FILE


def rename(job: Job, title: str) -> None:
    job.title = title
    _save(job)


def delete(job: Job) -> None:
    """Delete a finished or failed story; ValueError while it is still working."""
    if job.state in ("queued", "running"):
        raise ValueError("The story is still being generated.")
    with _lock:
        _jobs.pop(job.id, None)
    shutil.rmtree(job.dir, ignore_errors=True)


def _reference(voice_id: str) -> Path | None:
    if voice_id == DEFAULT_VOICE:
        return None
    try:
        return voices.voice_audio_path(voice_id)
    except KeyError:
        raise ValueError("A voice in the cast was deleted. Pick another voice and try again.")


def _join(clips: list[bytes]) -> bytes:
    """Concatenate 16-bit mono WAV clips (all from one model, so one sample rate) with pauses."""
    frames, rate = [], None
    for clip in clips:
        with wave.open(io.BytesIO(clip)) as w:
            rate = rate or w.getframerate()
            frames.append(w.readframes(w.getnframes()))
    silence = b"\x00\x00" * int(rate * PAUSE_SECONDS)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(silence.join(frames))
    return buf.getvalue()


def _work(job: Job) -> None:
    with _one_at_a_time:
        job.state = "running"
        _save(job)
        try:
            lines = parse(job.script)
            refs = {speaker: _reference(voice) for speaker, voice in job.cast.items()}
            clips = []
            for i, line in enumerate(lines):
                job.step, job.percent = f"Speaking line {i + 1} of {len(lines)}", int(99 * i / len(lines))
                clips.append(engine.synthesize(line.text, job.language, refs.get(line.speaker)))
            story = _join(clips)
            if job.effects:
                story = apply_to_wav(story, Effects(**job.effects))
            audio_path(job).write_bytes(story)
            job.state, job.step, job.percent = "done", "Done", 100
        except ValueError as exc:
            job.state, job.error = "error", str(exc)
        except Exception as exc:  # surface any engine failure as a job error, without a traceback
            job.state, job.error = "error", f"{job.step} failed: {exc}"
        _save(job)


def start(job: Job) -> None:
    _save(job)
    threading.Thread(target=_work, args=(job,), daemon=True).start()
