"""One background worker generates queued tracks in order (the engine runs one task at a time)."""

import queue
import threading
from pathlib import Path

from voxwell.features.music import engine, history

_queue: queue.Queue = queue.Queue()
_active: set[str] = set()  # queued or generating in this process
_worker: threading.Thread | None = None
_start_lock = threading.Lock()


def claim(track_id: str) -> None:
    """Mark a track as this run's before its record is written (see router._settle)."""
    _active.add(track_id)


def submit(track_id: str, fields: dict, files: dict[str, Path], cleanup: list[Path]) -> None:
    """Queue a track whose record already exists; `cleanup` files are deleted once it finishes."""
    global _worker
    _active.add(track_id)
    _queue.put((track_id, fields, files, cleanup))
    with _start_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, daemon=True, name="music-worker")
            _worker.start()


def is_active(track_id: str) -> bool:
    return track_id in _active


def _work() -> None:
    while True:
        _run(*_queue.get())


def _run(track_id: str, fields: dict, files: dict[str, Path], cleanup: list[Path]) -> None:
    def progress(fraction: float, stage: str) -> None:
        history.update(track_id, status="generating", progress=max(0.0, min(fraction, 1.0)), stage=stage)

    try:
        history.update(track_id, status="generating", stage="Starting", error="")
        wav, info = engine.generate(fields, files, progress)
        history.save_audio(track_id, wav)
        metas = info["metas"]
        changes = {"status": "done", "progress": 1.0, "stage": "Done"}
        if isinstance(metas.get("bpm"), int):
            changes["bpm"] = metas["bpm"]
        if metas.get("keyscale") and metas["keyscale"] != "N/A":  # ACE-Step's "not detected"
            changes["key"] = str(metas["keyscale"])
        history.update(track_id, **changes)
    except KeyError:
        pass  # the track was deleted while it was generating
    except engine.GenerationError as exc:
        _fail(track_id, str(exc))
    except Exception as exc:  # report it on the track, never kill the worker
        _fail(track_id, f"Music generation failed: {type(exc).__name__}: {exc}")
    finally:
        _active.discard(track_id)
        for path in cleanup:
            path.unlink(missing_ok=True)


def _fail(track_id: str, message: str) -> None:
    try:
        history.update(track_id, status="failed", stage="Failed", error=message)
    except KeyError:
        pass
