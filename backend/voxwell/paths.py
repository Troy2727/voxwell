import contextlib
import os
import re
import time
from pathlib import Path
from urllib.parse import quote


def data_dir(*parts: str) -> Path:
    """Return (and create) a folder under the Voxwell data root.

    VOXWELL_DATA_DIR overrides the platform default; tests always set it.
    """
    from platformdirs import user_data_dir  # here, so the stdlib-only CLI can import this module

    root = Path(os.environ.get("VOXWELL_DATA_DIR") or user_data_dir("Voxwell", appauthor=False))
    path = root.joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def child_path(folder: Path, name: str) -> Path:
    """`folder / name`, refused (ValueError) unless the result stays directly inside `folder`.

    Callers validate their ids already; this is the containment check itself, in the form static
    analysis (CodeQL) recognises: normalise the path, then check it is still under the folder.
    """
    if "/" in name or "\\" in name:  # either separator, on every OS: the same names everywhere
        raise ValueError(f"Not a file name: {name!r}")
    base = os.path.normpath(folder)
    path = os.path.normpath(os.path.join(base, name))
    if not path.startswith(base + os.sep) or os.sep in path[len(base) + 1:]:
        raise ValueError(f"Not a file name: {name!r}")
    return Path(path)


REPLACE_BUDGET_SECONDS = 5.0
# Windows errors a scanner's brief hold produces: access denied (5), sharing violation (32), lock
# violation (33). Anything else, and any error on macOS or Linux, is not retried.
_TRANSIENT_WINERRORS = {5, 32, 33}
# Seams for tests, so they never patch the os and time modules for the whole process.
_replace = os.replace
_sleep = time.sleep


def replace_file(source: Path, target: Path) -> None:
    """os.replace(source, target), retried briefly while Windows antivirus holds the file.

    Atomic saves and downloads write a temporary file and rename it into place. Real-time
    antivirus can hold that fresh file for a moment, and the rename then fails until the scan is
    done, so it is retried with growing pauses for up to REPLACE_BUDGET_SECONDS. If it still fails
    (or fails for another reason) the temporary file is removed and the original error raised.
    """
    deadline = time.monotonic() + REPLACE_BUDGET_SECONDS
    delay = 0.05
    while True:
        try:
            _replace(source, target)
            return
        except OSError as exc:
            if getattr(exc, "winerror", None) in _TRANSIENT_WINERRORS and time.monotonic() + delay < deadline:
                _sleep(delay)
                delay = min(delay * 2, 0.5)
                continue
            with contextlib.suppress(OSError):  # still held: keep the original error
                Path(source).unlink(missing_ok=True)
            raise


def is_network_path(value: str) -> bool:
    r"""Whether a path names another computer: \\server, \\server\share, //server/share or
    \\?\UNC\server\share. Opening one makes Windows sign in to that server as the user (NTLM).
    Local device paths (\\?\C:\..., \\.\C:\...) are not network paths."""
    path = value.strip().replace("/", "\\")
    if not path.startswith("\\\\"):
        return False
    rest = path[2:]
    if rest.startswith(("?\\", ".\\")):
        return rest[2:].upper().startswith("UNC\\")
    return True


_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def download_name(title: str, suffix: str, fallback: str) -> str:
    """A file name for a download, from a display title: no path or reserved characters."""
    return (_UNSAFE_NAME.sub("", title).strip()[:80] or fallback) + suffix


def attachment(filename: str) -> dict[str, str]:
    """Content-Disposition for a download, with non-ASCII names encoded as Starlette's FileResponse does."""
    quoted = quote(filename)
    if quoted != filename:
        return {"Content-Disposition": f"attachment; filename*=utf-8''{quoted}"}
    return {"Content-Disposition": f'attachment; filename="{filename}"'}
