"""Generated speech clips: a JSON record next to each WAV, so Projects can list them."""

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from voxwell.paths import child_path, data_dir

_ID = re.compile(r"^[0-9a-f]{32}$")
TITLE_LENGTH = 60


@dataclass
class Clip:
    id: str
    title: str
    text: str
    language: str
    voice: str  # display name at generation time
    created: float


def _paths(clip_id: str) -> tuple[Path, Path]:
    """Return (wav, json) for a clip id; KeyError if unknown or malformed."""
    if not _ID.match(clip_id):
        raise KeyError(clip_id)
    wav = child_path(data_dir("voice_cloning"), f"{clip_id}.wav")
    meta = wav.with_suffix(".json")
    if not (wav.exists() and meta.exists()):
        raise KeyError(clip_id)
    return wav, meta


def record(clip_id: str, text: str, language: str, voice: str) -> Clip:
    title = text if len(text) <= TITLE_LENGTH else text[: TITLE_LENGTH - 1].rstrip() + "…"
    clip = Clip(clip_id, title, text, language, voice, time.time())
    (data_dir("voice_cloning") / f"{clip_id}.json").write_text(json.dumps(asdict(clip)), encoding="utf-8")
    return clip


def list_clips() -> list[Clip]:
    folder = data_dir("voice_cloning")
    return [Clip(**json.loads(p.read_text(encoding="utf-8"))) for p in folder.glob("*.json")]


def rename(clip_id: str, title: str) -> Clip:
    _, meta = _paths(clip_id)
    clip = Clip(**json.loads(meta.read_text(encoding="utf-8")))
    clip.title = title
    meta.write_text(json.dumps(asdict(clip)), encoding="utf-8")
    return clip


def delete(clip_id: str) -> None:
    wav, meta = _paths(clip_id)
    meta.unlink()
    wav.unlink(missing_ok=True)
