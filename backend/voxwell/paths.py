import os
import re
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
