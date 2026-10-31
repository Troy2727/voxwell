"""Tracks: a JSON record next to each WAV. A record exists from the moment a track is queued, so
the page can show its progress; `status` is queued, generating, done or failed."""

import json
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from voxwell.paths import child_path, data_dir

_ID = re.compile(r"^[0-9a-f]{32}$")
_lock = threading.Lock()  # one writer thread and many API readers share these files
PARTS = ("mix", "vocals", "instrumental")


@dataclass
class Track:
    id: str
    title: str
    prompt: str
    lyrics: str
    instrumental: bool
    language: str
    duration: float
    bpm: int | None
    key: str
    seed: int
    steps: int
    created: float
    status: str = "queued"
    progress: float = 0.0
    stage: str = "Waiting"
    error: str = ""
    parent_id: str | None = None  # set on a track made by editing a section of another
    edit_start: float | None = None
    edit_end: float | None = None
    has_reference: bool = False
    stems: bool = False


def _folder() -> Path:
    return data_dir("music", "tracks")


def _meta(track_id: str) -> Path:
    if not _ID.match(track_id):
        raise KeyError(track_id)
    return child_path(_folder(), f"{track_id}.json")


def part_path(track_id: str, part: str = "mix") -> Path:
    """Where a track's audio part (mix, vocals or instrumental) is stored; KeyError if malformed."""
    if part not in PARTS:
        raise KeyError(part)
    suffix = ".wav" if part == "mix" else f".{part}.wav"
    return child_path(_folder(), f"{_meta(track_id).stem}{suffix}")


def audio_path(track_id: str, part: str = "mix") -> Path:
    """Path of a track's existing audio part; KeyError if unknown or not there."""
    path = part_path(track_id, part)
    if not _meta(track_id).exists() or not path.exists():
        raise KeyError(track_id)
    return path


def scratch_path(track_id: str, name: str) -> Path:
    """A working file for a queued track (an uploaded reference), deleted with the track."""
    return child_path(_folder(), f"{_meta(track_id).stem}.{name}.wav")


def _write(track: Track) -> None:
    """Write via a temporary file and rename, so a crash mid-write never leaves a broken record."""
    path = _meta(track.id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(track)), encoding="utf-8")
    os.replace(tmp, path)


def _read(path: Path) -> Track:
    known = {f.name for f in fields(Track)}
    data = json.loads(path.read_text(encoding="utf-8"))
    return Track(**{k: v for k, v in data.items() if k in known})


def create(track: Track) -> Track:
    track.created = time.time()
    with _lock:
        _write(track)
    return track


def get(track_id: str) -> Track:
    with _lock:
        path = _meta(track_id)
        if not path.exists():
            raise KeyError(track_id)
        return _read(path)


def update(track_id: str, **changes) -> Track:
    with _lock:
        path = _meta(track_id)
        if not path.exists():  # deleted while it was generating
            raise KeyError(track_id)
        track = _read(path)
        for name, value in changes.items():
            setattr(track, name, value)
        _write(track)
        return track


def save_audio(track_id: str, wav: bytes) -> None:
    """Store a track's generated mix; KeyError (nothing written) if the track was deleted meanwhile."""
    with _lock:
        if not _meta(track_id).exists():
            raise KeyError(track_id)
        part_path(track_id).write_bytes(wav)


def list_tracks() -> list[Track]:
    with _lock:
        tracks = []
        for path in _folder().glob("*.json"):
            try:
                tracks.append(_read(path))
            except (ValueError, TypeError):  # an unreadable record must not hide all the others
                continue
    return sorted(tracks, key=lambda t: t.created, reverse=True)


def delete(track_id: str) -> None:
    with _lock:
        meta = _meta(track_id)
        if not meta.exists():
            raise KeyError(track_id)
        meta.unlink()
        for path in _folder().glob(f"{track_id}.*"):
            path.unlink(missing_ok=True)
