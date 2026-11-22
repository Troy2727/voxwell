"""Kept results: a JSON record next to a feature's output files, so Projects can list them.

Tools, Audio effects and Translation each write their outputs into one folder. An output that a
record names is kept until it is deleted from Projects. Any other output (a comparison, an AI
direction try) is scratch and is removed a day after it was made.
"""

import json
import re
import threading
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from voxwell.paths import child_path, data_dir, replace_file

FEATURES = ("tools", "audio_effects", "translation")
SCRATCH_TTL_SECONDS = 24 * 60 * 60
TITLE_LENGTH = 60
_ID = re.compile(r"^[0-9a-f]{32}$")
_lock = threading.Lock()


@dataclass
class Result:
    id: str
    feature: str
    kind: str
    title: str
    files: dict[str, str]  # label -> file name in the feature's folder, e.g. {"Audio": "<id>.wav"}
    created: float = 0.0
    voice: str = ""  # a saved voice id, or "" for none or the default voice
    language: str = ""
    text: str = ""


def title_from(text: str, fallback: str) -> str:
    """A short display title: the text on one line, cut to TITLE_LENGTH."""
    text = " ".join(text.split())
    if not text:
        return fallback
    return text if len(text) <= TITLE_LENGTH else text[: TITLE_LENGTH - 1].rstrip() + "…"


def _meta(feature: str, result_id: str) -> Path:
    if feature not in FEATURES or not _ID.match(result_id):
        raise KeyError(result_id)
    return child_path(data_dir(feature), f"{result_id}.json")


def _read(path: Path) -> Result:
    known = {f.name for f in fields(Result)}
    data = json.loads(path.read_text(encoding="utf-8"))
    return Result(**{k: v for k, v in data.items() if k in known})


def _write(result: Result) -> None:
    path = _meta(result.feature, result.id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(result)), encoding="utf-8")
    replace_file(tmp, path)


def keep(feature: str, result_id: str, kind: str, title: str, files: dict[str, str], **details) -> Result:
    result = Result(result_id, feature, kind, title, files, time.time(), **details)
    with _lock:
        _write(result)
    return result


def list_results() -> list[Result]:
    found = []
    with _lock:
        for feature in FEATURES:
            for path in data_dir(feature).glob("*.json"):
                try:
                    found.append(_read(path))
                except (ValueError, TypeError):  # an unreadable record must not hide all the others
                    continue
    return found


def get(feature: str, result_id: str) -> Result:
    with _lock:
        path = _meta(feature, result_id)
        if not path.exists():
            raise KeyError(result_id)
        return _read(path)


def rename(feature: str, result_id: str, title: str) -> Result:
    with _lock:
        path = _meta(feature, result_id)
        if not path.exists():
            raise KeyError(result_id)
        result = _read(path)
        result.title = title
        _write(result)
        return result


def delete(feature: str, result_id: str) -> None:
    with _lock:
        path = _meta(feature, result_id)
        if not path.exists():
            raise KeyError(result_id)
        result = _read(path)
        path.unlink()
        for name in result.files.values():
            child_path(data_dir(feature), name).unlink(missing_ok=True)


def prune(feature: str) -> None:
    """Remove scratch outputs (WAV and MP4 files no record names) older than a day."""
    folder = data_dir(feature)
    kept: set[str] = set()
    with _lock:
        for path in folder.glob("*.json"):
            try:
                kept.update(_read(path).files.values())
            except (ValueError, TypeError):
                continue
    cutoff = time.time() - SCRATCH_TTL_SECONDS
    for old in [*folder.glob("*.wav"), *folder.glob("*.mp4")]:
        if old.name not in kept and old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)
