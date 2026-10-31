"""Watch folder: dub every new video that appears in a folder, saving results to <folder>/dubbed/.

A background thread polls the folder. A file is dubbed once its size and modification time stop
changing between two polls (so half-copied files are left alone). Videos already in the folder
when watching starts are skipped. State lives in data_dir("batch")/watch.json.
"""

import json
import logging
import shutil
import threading
import time
from pathlib import Path

from fastapi import HTTPException

from voxwell.features.dubbing import jobs
from voxwell.features.dubbing.router import VIDEO_EXTS, start_dub
from voxwell.paths import data_dir, is_network_path

POLL_SECONDS = 5
OUTPUT_FOLDER = "dubbed"
log = logging.getLogger(__name__)
_lock = threading.Lock()
_started = False


def _path() -> Path:
    return data_dir("batch") / "watch.json"


def load() -> dict:
    if _path().exists():
        return json.loads(_path().read_text(encoding="utf-8"))
    return {"enabled": False, "folder": "", "target": "", "voice": "original", "problem": None, "files": {}}


def _save(cfg: dict) -> None:
    _path().write_text(json.dumps(cfg), encoding="utf-8")


def _videos(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS)


def configure(enabled: bool, folder: str, target: str, voice: str) -> dict:
    """Save settings. Starting to watch (or changing what is watched) skips the current videos."""
    with _lock:
        cfg = load()
        changed = (folder, target, voice) != (cfg["folder"], cfg["target"], cfg["voice"])
        if enabled and (changed or not cfg["enabled"]):
            cfg["files"] = {p.name: {"status": "skipped"} for p in _videos(Path(folder))}
        cfg.update(enabled=enabled, folder=folder, target=target, voice=voice, problem=None)
        _save(cfg)
        return cfg


def _export(job: jobs.Job, folder: Path, stem: str) -> None:
    out = folder / OUTPUT_FOLDER
    out.mkdir(exist_ok=True)
    shutil.copyfile(job.outputs["video"], out / f"{stem}.{job.target}.mp4")
    shutil.copyfile(job.outputs["subtitles"], out / f"{stem}.{job.target}.srt")


def poll_once() -> None:
    with _lock:
        cfg = load()
        if not cfg["enabled"]:
            return
        if is_network_path(cfg["folder"]):  # a config saved before network folders were refused
            cfg["problem"] = "The watched folder is on another computer. Choose a folder on this computer."
            _save(cfg)
            return
        folder = Path(cfg["folder"])
        if not folder.is_dir():
            cfg["problem"] = "The watched folder no longer exists."
            _save(cfg)
            return
        cfg["problem"] = None
        for path in _videos(folder):
            st = path.stat()
            seen = (st.st_size, st.st_mtime)
            rec = cfg["files"].get(path.name)
            if rec is None or (rec["status"] == "new" and (rec["size"], rec["mtime"]) != seen) or st.st_size == 0:
                # First sighting, or still being written: wait for it to settle.
                cfg["files"][path.name] = {"status": "new", "size": seen[0], "mtime": seen[1]}
            elif rec["status"] == "new":
                try:
                    with path.open("rb") as source:
                        job = start_dub(source, path.name, cfg["target"], cfg["voice"])
                    rec.update(status="dubbing", job=job.id)
                except HTTPException as exc:
                    rec.update(status="failed", error=exc.detail)
                except OSError as exc:  # e.g. locked by another program; retry next poll
                    log.warning("Could not read %s: %s", path.name, exc)
        for name, rec in cfg["files"].items():
            if rec["status"] != "dubbing":
                continue
            job = jobs.get(rec["job"])
            if job is None:
                rec.update(status="failed", error="The dub was deleted.")
            elif job.state == "done":
                try:
                    _export(job, folder, Path(name).stem)
                    rec["status"] = "saved"
                except OSError:
                    log.exception("Could not save the dub of %s", name)
                    rec.update(status="failed", error="Could not save the dub; see the Voxwell log.")
            elif job.state == "error":
                rec.update(status="failed", error=job.error)
        _save(cfg)


def _loop() -> None:
    while True:
        try:
            poll_once()
        except Exception:  # never let one bad poll stop watching
            log.exception("Watch folder poll failed")
        time.sleep(POLL_SECONDS)


def start() -> None:
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="voxwell-watch-folder").start()
