"""ffmpeg access. ffmpeg is NOT bundled: it is found on PATH (or via VOXWELL_FFMPEG)."""

import logging
import os
import shutil
import subprocess

log = logging.getLogger(__name__)


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
    """Run ffmpeg with `args`; on failure, log its stderr and raise DubbingError."""
    cmd = [ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    except OSError as exc:
        log.exception("Could not run ffmpeg")
        raise DubbingError("Could not run ffmpeg; see the Voxwell log.") from exc
    if proc.returncode != 0:
        log.error("ffmpeg failed (exit %s): %s", proc.returncode, proc.stderr.strip()[-2000:])
        raise DubbingError("ffmpeg could not process the file; see the Voxwell log.")
