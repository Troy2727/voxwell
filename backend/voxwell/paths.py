import os
import re
from pathlib import Path
from urllib.parse import quote

from platformdirs import user_data_dir


def data_dir(*parts: str) -> Path:
    """Return (and create) a folder under the Voxwell data root.

    VOXWELL_DATA_DIR overrides the platform default; tests always set it.
    """
    root = Path(os.environ.get("VOXWELL_DATA_DIR") or user_data_dir("Voxwell", appauthor=False))
    path = root.joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


_UNSAFE_NAME = re.compile(r'[\/:*?"<>|\x00-\x1f]')


def download_name(title: str, suffix: str, fallback: str) -> str:
    """A file name for a download, from a display title: no path or reserved characters."""
    return (_UNSAFE_NAME.sub("", title).strip()[:80] or fallback) + suffix


def attachment(filename: str) -> dict[str, str]:
    """Content-Disposition for a download, with non-ASCII names encoded as Starlette's FileResponse does."""
    quoted = quote(filename)
    if quoted != filename:
        return {"Content-Disposition": f"attachment; filename*=utf-8''{quoted}"}
    return {"Content-Disposition": f'attachment; filename="{filename}"'}
