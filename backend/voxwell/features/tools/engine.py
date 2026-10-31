"""Tool engines: voice conversion (Chatterbox VC) and ffmpeg-based audio tools."""

import json
import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path

from voxwell.features.dubbing.ffmpeg import DubbingError, ffmpeg_path, run_ffmpeg
from voxwell.features.voice_cloning import engine as cloning

log = logging.getLogger(__name__)

MIN_TEMPO, MAX_TEMPO = 0.25, 4.0  # beyond this speech stops being intelligible

_vc = None
_lock = threading.Lock()


def _load_vc():
    global _vc
    with _lock:
        if _vc is None:
            from chatterbox.vc import ChatterboxVC

            # Same checkpoint quirk as voice cloning: load to CPU, then move to the device.
            with cloning._torch_load_to_cpu():
                _vc = ChatterboxVC.from_pretrained(device=cloning._pick_device())
        return _vc


def convert(source: Path, target_voice: Path) -> bytes:
    """Re-speak the recording in `source` with the voice of `target_voice`; WAV bytes."""
    model = _load_vc()
    with _lock:
        wav = model.generate(str(source), target_voice_path=str(target_voice))
    return cloning._to_wav(wav, model.sr)


def _atempo_chain(tempo: float) -> str:
    """ffmpeg's atempo takes 0.5..2.0 per filter, so larger changes are chained."""
    parts = []
    while tempo > 2.0:
        parts.append(2.0)
        tempo /= 2.0
    while tempo < 0.5:
        parts.append(0.5)
        tempo /= 0.5
    parts.append(tempo)
    return ",".join(f"atempo={p:.6f}" for p in parts)


def fit(source: Path, current_seconds: float, target_seconds: float, out: Path) -> None:
    """Time-stretch `source` to last `target_seconds` without changing its pitch."""
    tempo = current_seconds / target_seconds
    if not MIN_TEMPO <= tempo <= MAX_TEMPO:
        raise DubbingError(f"That is a {tempo:.2f}x speed change; choose a length between {MIN_TEMPO}x and {MAX_TEMPO}x.")
    run_ffmpeg(["-i", str(source), "-filter:a", _atempo_chain(tempo), "-c:a", "pcm_s16le", str(out)])


def ffprobe_path() -> str:
    """ffprobe ships next to ffmpeg; also look on PATH."""
    beside = Path(ffmpeg_path()).with_name("ffprobe" + (".exe" if os.name == "nt" else ""))
    found = str(beside) if beside.exists() else shutil.which("ffprobe")
    if not found:
        raise DubbingError("ffprobe was not found. It comes with ffmpeg; reinstall ffmpeg.")
    return found


def probe(source: Path) -> dict:
    """Format, duration and streams of a media file, from ffprobe."""
    cmd = [ffprobe_path(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(source)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    except OSError as exc:
        log.exception("Could not run ffprobe")
        raise DubbingError("Could not run ffprobe; see the Voxwell log.") from exc
    if proc.returncode != 0:
        raise DubbingError("This file could not be read as audio or video.")
    data = json.loads(proc.stdout or "{}")
    fmt = data.get("format", {})
    streams = []
    for s in data.get("streams", []):
        kind = s.get("codec_type")
        if kind not in ("audio", "video", "subtitle"):
            continue
        entry = {"type": kind, "codec": s.get("codec_long_name") or s.get("codec_name")}
        if kind == "audio":
            entry.update(sample_rate=int(s.get("sample_rate", 0)) or None, channels=s.get("channels"))
        elif kind == "video":
            entry.update(width=s.get("width"), height=s.get("height"), fps=_fps(s.get("avg_frame_rate")))
        if (lang := s.get("tags", {}).get("language")) and lang != "und":  # "und" = undetermined
            entry["language"] = lang
        streams.append(entry)
    return {
        "format": fmt.get("format_long_name") or fmt.get("format_name"),
        "duration": float(fmt["duration"]) if fmt.get("duration") else None,
        "size": int(fmt.get("size", 0)) or None,
        "bit_rate": int(fmt.get("bit_rate", 0)) or None,
        "streams": streams,
    }


def _fps(rate: str | None) -> float | None:
    try:
        num, den = (rate or "").split("/")
        return round(int(num) / int(den), 2) if int(den) else None
    except ValueError:
        return None
