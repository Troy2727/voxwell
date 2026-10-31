"""Batch dubbing: queue several uploads at once, or watch a folder for new videos.

Every dub is an ordinary dubbing job (see dubbing.jobs), so it runs in the shared one-at-a-time
queue and shows up in Projects.
"""

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from voxwell.features.batch import watch
from voxwell.features.dubbing import jobs
from voxwell.features.dubbing.router import check_settings, start_dub
from voxwell.paths import is_network_path

router = APIRouter(tags=["batch"])

MAX_FILES = 100


class WatchSettings(BaseModel):
    enabled: bool
    folder: str = ""
    target_language: str = ""
    voice: str = "original"


@router.get("/status")
def status():
    return {"ready": True}


@router.post("/jobs")
def create_jobs(
    files: list[UploadFile] = File(...),
    target_language: str = Form(...),
    voice: str = Form("original"),
):
    if len(files) > MAX_FILES:
        raise HTTPException(422, f"Too many files ({MAX_FILES} max per batch).")
    check_settings(target_language, voice)  # fail the whole batch early on bad settings
    started, failed = [], []
    for f in files:
        name = f.filename or ""
        try:
            started.append({"name": name, "id": start_dub(f.file, name, target_language, voice).id})
        except HTTPException as exc:
            failed.append({"name": name, "error": exc.detail})
    return {"jobs": started, "errors": failed}


def _watch_view(cfg: dict) -> dict:
    files = []
    for name, rec in sorted(cfg["files"].items()):
        if rec["status"] == "skipped":
            continue
        entry = {"name": name, "status": rec["status"], "error": rec.get("error")}
        job = jobs.get(rec["job"]) if rec["status"] == "dubbing" else None
        if job:
            entry.update(step=job.step, percent=job.percent)
        files.append(entry)
    return {
        "enabled": cfg["enabled"], "folder": cfg["folder"], "target_language": cfg["target"],
        "voice": cfg["voice"], "problem": cfg["problem"], "output_folder": watch.OUTPUT_FOLDER,
        "skipped": sum(1 for r in cfg["files"].values() if r["status"] == "skipped"), "files": files,
    }


@router.get("/watch")
def get_watch():
    return _watch_view(watch.load())


@router.put("/watch")
def put_watch(req: WatchSettings):
    folder, target = req.folder.strip(), req.target_language
    if req.enabled:
        # Opening a network path would make Windows sign in to that server as the user.
        if is_network_path(folder):
            raise HTTPException(422, "Choose a folder on this computer, not a network folder.")
        if not folder or not Path(folder).is_dir():
            raise HTTPException(422, "Choose a folder that exists.")
        target = check_settings(req.target_language, req.voice)
    return _watch_view(watch.configure(req.enabled, folder, target, req.voice))
