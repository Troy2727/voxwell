import os
from pathlib import Path

from platformdirs import user_data_dir


def data_dir(*parts: str) -> Path:
    """Return (and create) a folder under the Voxwell data root.

    VOXWELL_DATA_DIR overrides the platform default; tests always set it.
    """
    root = Path(os.environ.get("VOXWELL_DATA_DIR") or user_data_dir("Voxwell", appauthor=False))
    path = root.joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path
