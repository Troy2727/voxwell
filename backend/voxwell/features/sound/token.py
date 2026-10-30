"""The Hugging Face access token for the gated Stable Audio model.

Read from a file in the data folder that only the current user can read, else from the HF_TOKEN
environment variable. The token is never logged and never returned by the API.
"""

import os
import re

from voxwell.paths import data_dir

_VALID = re.compile(r"^\S{1,512}$")


def _file():
    return data_dir("sound") / ".hf_token"


def get_token() -> str | None:
    """The saved token, else HF_TOKEN from the environment, else None."""
    try:
        saved = _file().read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        saved = ""
    return saved or os.environ.get("HF_TOKEN", "").strip() or None


def token_set() -> bool:
    return get_token() is not None


def save_token(token: str) -> None:
    """Store the token with owner-only permissions (best effort on Windows, where mode bits are limited)."""
    token = token.strip()
    if not _VALID.match(token):
        raise ValueError("The token must be one word of at most 512 characters.")
    path = _file()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token)
    os.chmod(path, 0o600)


def clear_token() -> None:
    _file().unlink(missing_ok=True)
