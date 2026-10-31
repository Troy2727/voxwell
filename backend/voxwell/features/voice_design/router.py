import importlib.util
import re
import time
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from voxwell import voices
from voxwell.features.voice_design import engine
from voxwell.paths import child_path, data_dir

router = APIRouter(tags=["voice_design"])

DEFAULT_SAMPLE_TEXT = "Hello! This is a preview of the voice you described. How does it sound?"
MAX_DESCRIPTION = 500
MAX_SAMPLE_TEXT = 500
_PREVIEW_ID = re.compile(r"^[0-9a-f]{32}$")
PREVIEW_TTL_SECONDS = 24 * 60 * 60


class PreviewRequest(BaseModel):
    description: str
    sample_text: str | None = None


class SaveRequest(BaseModel):
    preview_id: str
    name: str


def _delete_old_previews(folder) -> None:
    """Previews are scratch files: saving one copies it into the voice library."""
    cutoff = time.time() - PREVIEW_TTL_SECONDS
    for path in folder.glob("*.wav"):
        if path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)


def _preview_path(preview_id: str):
    if not _PREVIEW_ID.match(preview_id):
        raise HTTPException(404, "Preview not found.")
    path = child_path(data_dir("voice_design"), f"{preview_id}.wav")
    if not path.exists():
        raise HTTPException(404, "Preview not found.")
    return path


@router.get("/status")
def status():
    return {"ready": importlib.util.find_spec("parler_tts") is not None}


@router.post("/preview")
def preview(req: PreviewRequest):
    description = req.description.strip()
    sample = (req.sample_text or "").strip() or DEFAULT_SAMPLE_TEXT
    if not description:
        raise HTTPException(422, "Describe the voice first.")
    if len(description) > MAX_DESCRIPTION:
        raise HTTPException(422, f"Description is too long (max {MAX_DESCRIPTION} characters).")
    if len(sample) > MAX_SAMPLE_TEXT:
        raise HTTPException(422, f"Sample text is too long (max {MAX_SAMPLE_TEXT} characters).")
    try:
        wav = engine.design(description, sample)
    except Exception as exc:
        raise HTTPException(500, f"Voice generation failed: {exc}") from exc
    folder = data_dir("voice_design")
    _delete_old_previews(folder)
    preview_id = uuid.uuid4().hex
    (folder / f"{preview_id}.wav").write_bytes(wav)
    return {"preview_id": preview_id, "url": f"/api/voice_design/audio/{preview_id}"}


@router.get("/audio/{preview_id}")
def audio(preview_id: str):
    return FileResponse(_preview_path(preview_id), media_type="audio/wav")


@router.post("/save")
def save(req: SaveRequest):
    name = req.name.strip()
    if not name:
        raise HTTPException(422, "Give the voice a name.")
    path = _preview_path(req.preview_id)
    voice = voices.save_voice(name, path.read_bytes(), "design")
    return {"id": voice.id, "name": voice.name, "source": voice.source}
