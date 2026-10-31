"""ffmpeg access. ffmpeg is NOT bundled: it is found on PATH (or via VOXWELL_FFMPEG)."""

import os
import shutil
import subprocess


class DubbingError(Exception):
    """A pipeline failure with a user-readable message."""


NOT_FOUND = (
    "ffmpeg was not found. Install ffmpeg (https://ffmpeg.org/download.html) "
    "and make sure it is on your PATH, or set VOXWELL_FFMPEG to its location."
)


def ffmpeg_path() -> str:
    found = os.environ.get("VOXWELL_FFMPEG") or shutil.which("ffmpeg")
    if not found:
        raise DubbingError(NOT_FOUND)
    return found


def run_ffmpeg(args: list[str]) -> None:
    """Run ffmpeg with `args`; raise DubbingError with the tail of stderr on failure."""
    cmd = [ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    except OSError as exc:
        raise DubbingError(f"Could not run ffmpeg: {exc}") from exc
    if proc.returncode != 0:
        tail = proc.stderr.strip().splitlines()[-3:]
        raise DubbingError("ffmpeg failed: " + " | ".join(tail))
