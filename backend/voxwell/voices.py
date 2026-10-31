"""Shared voice library: reference clips usable by any feature."""

import json
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from voxwell import voice_collections
from voxwell.paths import data_dir

_ID = re.compile(r"^[0-9a-f]{12}$")


@dataclass
class Voice:
    id: str
    name: str
    source: str  # "upload", "design" or "remix"


def save_voice(name: str, wav: bytes, source: str) -> Voice:
    voice = Voice(id=uuid.uuid4().hex[:12], name=name, source=source)
    folder = data_dir("voices")
    (folder / f"{voice.id}.wav").write_bytes(wav)
    (folder / f"{voice.id}.json").write_text(json.dumps(asdict(voice)), encoding="utf-8")
    return voice


def list_voices() -> list[Voice]:
    folder = data_dir("voices")
    return [Voice(**json.loads(p.read_text(encoding="utf-8"))) for p in sorted(folder.glob("*.json"))]


def voice_audio_path(voice_id: str) -> Path:
    """Return the WAV path for a voice id; KeyError if unknown or malformed."""
    if not _ID.match(voice_id):
        raise KeyError(voice_id)
    path = data_dir("voices") / f"{voice_id}.wav"
    if not path.exists():
        raise KeyError(voice_id)
    return path


def get_voice(voice_id: str) -> Voice:
    """KeyError if unknown or malformed."""
    meta = voice_audio_path(voice_id).with_suffix(".json")
    return Voice(**json.loads(meta.read_text(encoding="utf-8")))


def rename_voice(voice_id: str, name: str) -> Voice:
    voice = get_voice(voice_id)
    voice.name = name
    (data_dir("voices") / f"{voice.id}.json").write_text(json.dumps(asdict(voice)), encoding="utf-8")
    return voice


def delete_voice(voice_id: str) -> None:
    audio = voice_audio_path(voice_id)
    audio.with_suffix(".json").unlink(missing_ok=True)
    audio.unlink()
    voice_collections.remove_voice_everywhere(voice_id)
