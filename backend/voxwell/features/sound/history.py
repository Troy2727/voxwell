"""Generated sounds: a JSON record next to each WAV, so the page can list them."""

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from voxwell.paths import child_path, data_dir

_ID = re.compile(r"^[0-9a-f]{32}$")


@dataclass
class Sound:
    id: str
    prompt: str
    duration: float
    seed: int
    steps: int
    created: float


def _paths(sound_id: str) -> tuple[Path, Path]:
    """Return (wav, json) for a sound id; KeyError if unknown or malformed."""
    if not _ID.match(sound_id):
        raise KeyError(sound_id)
    wav = child_path(data_dir("sound"), f"{sound_id}.wav")
    meta = wav.with_suffix(".json")
    if not (wav.exists() and meta.exists()):
        raise KeyError(sound_id)
    return wav, meta


def audio_path(sound_id: str) -> Path:
    return _paths(sound_id)[0]


def save(sound_id: str, wav: bytes, prompt: str, duration: float, seed: int, steps: int) -> Sound:
    sound = Sound(sound_id, prompt, duration, seed, steps, time.time())
    folder = data_dir("sound")
    (folder / f"{sound_id}.wav").write_bytes(wav)
    (folder / f"{sound_id}.json").write_text(json.dumps(asdict(sound)), encoding="utf-8")
    return sound


def list_sounds() -> list[Sound]:
    folder = data_dir("sound")
    sounds = [Sound(**json.loads(p.read_text(encoding="utf-8"))) for p in folder.glob("*.json")]
    return sorted(sounds, key=lambda s: s.created, reverse=True)


def delete(sound_id: str) -> None:
    wav, meta = _paths(sound_id)
    meta.unlink()
    wav.unlink(missing_ok=True)
