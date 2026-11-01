"""The music engine's runtime: ACE-Step 1.5 (MIT code and weights) in its own Python environment.

ACE-Step needs newer transformers and diffusers than Voxwell's speech models allow (chatterbox-tts
pins older releases), so it cannot share Voxwell's environment. Voxwell installs it once into the
data folder: the source at a pinned commit, its packages with `uv sync --frozen` from ACE-Step's own
lock file, and the weights at a pinned revision. It then runs ACE-Step's HTTP API on a free local
port with a random key. That server watches Voxwell's process and exits when it ends, crashes
included, so it never outlives the app.
"""

import logging
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

from voxwell.paths import data_dir, replace_file

log = logging.getLogger(__name__)

COMMIT = "ca1e85fe9430179831e6bc6be790c332190a3866"
SOURCE_URL = f"https://codeload.github.com/ACE-Step/ACE-Step-1.5/zip/{COMMIT}"
WEIGHTS_REPO = "ACE-Step/Ace-Step1.5"
WEIGHTS_REVISION = "19671f406d603126926c1b7e2adc169acbcade22"
# The turbo DiT with its VAE and text encoder. The repo's 5 Hz planning LM (3.7 GB) is left out and
# never loaded (ACESTEP_INIT_LLM=false): the DiT alone turns a description and lyrics into a song.
WEIGHTS = ["config.json", "acestep-v15-turbo/*", "vae/*", "Qwen3-Embedding-0.6B/*"]
START_TIMEOUT_SECONDS = 15 * 60  # loading the models from disk takes minutes on a slow CPU

# Runs inside ACE-Step's environment with -I, so nothing from Voxwell's folders is importable there.
# It exits when the Voxwell process (argv[2]) does. Watching the process, not a stdin pipe: on
# Windows a thread blocked reading a pipe stalls every other call on that handle, and libraries
# that check whether stdin is a terminal would then hang the server's startup.
_HOST = """
import os, sys, threading, time

def _watch(pid):
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if handle:
            kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
    else:
        while True:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(2)
    os._exit(0)

port, parent = sys.argv[1], int(sys.argv[2])
threading.Thread(target=_watch, args=(parent,), daemon=True).start()
sys.argv = ["acestep-api", "--host", "127.0.0.1", "--port", port]
from acestep.api_server import main
main()
"""


class EngineError(Exception):
    """A problem the user can fix or retry, with a message to show them."""


@dataclass
class InstallState:
    state: str = "idle"  # idle | installing | failed
    step: str = ""
    percent: float = 0.0
    detail: str = ""
    error: str = ""


_install = InstallState()
_install_lock = threading.Lock()
_server: dict = {}
_server_lock = threading.Lock()


def _root() -> Path:
    return data_dir("music", "engine")


def source_dir() -> Path:
    return _root() / f"ace-step-{COMMIT[:12]}"


def _marker() -> Path:
    return source_dir() / ".voxwell-installed"


def is_installed() -> bool:
    return _marker().exists()


def _python() -> Path:
    venv = source_dir() / ".venv"
    return venv / "Scripts" / "python.exe" if os.name == "nt" else venv / "bin" / "python"


def install_state() -> dict:
    return asdict(_install)


def engine_state() -> str:
    """stopped | starting | ready"""
    server = _server.get("current")
    if not server or server["proc"].poll() is not None:
        return "stopped"
    return "ready" if server["ready"] else "starting"


# ---------------------------------------------------------------- install

def start_install() -> bool:
    """Start installing in the background; False if an install is already running."""
    with _install_lock:
        if _install.state == "installing":
            return False
        _set(state="installing", step="Starting", percent=0, detail="", error="")
    threading.Thread(target=_install_worker, daemon=True, name="music-install").start()
    return True


def _set(**fields) -> None:
    for key, value in fields.items():
        setattr(_install, key, value)


def _install_worker() -> None:
    try:
        if not source_dir().joinpath("pyproject.toml").exists():
            _download_source()
        _sync_packages()
        _download_weights()
        _marker().write_text(COMMIT, encoding="utf-8")
        _set(state="idle", step="Installed", percent=100, detail="")
    except EngineError as exc:
        _set(state="failed", error=str(exc))
    except Exception:  # report, never crash the server
        log.exception("Installing the music engine failed")
        _set(state="failed", error="Installing the music engine failed; see the Voxwell log.")


def _download_source() -> None:
    _set(step="Downloading ACE-Step", percent=1)
    archive = _root() / f"{COMMIT[:12]}.zip.part"
    try:
        with urllib.request.urlopen(SOURCE_URL, timeout=60) as response, archive.open("wb") as out:
            shutil.copyfileobj(response, out)
    except OSError as exc:
        archive.unlink(missing_ok=True)
        log.exception("Downloading ACE-Step failed")
        raise EngineError("Could not download ACE-Step. Check the internet connection and try again.") from exc
    # Extract beside the final folder and rename it into place only when complete, so an
    # interrupted extraction never leaves a source_dir() that later installs would trust.
    target = source_dir()
    partial = target.with_name(target.name + ".part")
    shutil.rmtree(partial, ignore_errors=True)
    shutil.rmtree(target, ignore_errors=True)
    try:
        with zipfile.ZipFile(archive) as zf:
            _extract_without_top_folder(zf, partial)
    except zipfile.BadZipFile:
        raise EngineError("The ACE-Step download is corrupted. Try again.")
    finally:
        archive.unlink(missing_ok=True)
    replace_file(partial, target)


def _extract_without_top_folder(zf: zipfile.ZipFile, target: Path) -> None:
    """Extract GitHub's archive into `target`, dropping its long "ACE-Step-1.5-<commit>/" prefix,
    which would push deep paths past Windows' 260-character limit. Members that would land
    outside `target` are refused."""
    root = target.resolve()
    for member in zf.infolist():
        parts = Path(member.filename).parts[1:]
        if not parts or member.is_dir():
            continue
        dest = root.joinpath(*parts).resolve()
        if not dest.is_relative_to(root):
            raise EngineError("The ACE-Step download contains an unsafe path.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, dest.open("wb") as out:
            shutil.copyfileobj(src, out)


def _sync_packages() -> None:
    uv = shutil.which("uv")
    if not uv:
        raise EngineError("Installing the music engine needs uv on your PATH (https://docs.astral.sh/uv/).")
    _set(step="Installing packages (about 6 GB)", percent=5)
    env = {
        **os.environ,
        "UV_SYSTEM_CERTS": os.environ.get("UV_SYSTEM_CERTS", "1"),
        # Voxwell's own environment must not be the one synced: uv prefers UV_PROJECT_ENVIRONMENT
        # (set by some Voxwell setups) over the project's .venv, which is where _python() runs from.
        "UV_PROJECT_ENVIRONMENT": str(source_dir() / ".venv"),
    }
    env.pop("VIRTUAL_ENV", None)
    proc = subprocess.Popen(
        [uv, "sync", "--frozen", "--no-progress"],
        cwd=source_dir(),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    tail: list[str] = []
    for line in proc.stdout:
        line = line.strip()
        if line:
            tail = (tail + [line])[-20:]
            _set(detail=line[:200])
    if proc.wait() != 0:
        log.error("uv sync failed:\n%s", "\n".join(tail))
        raise EngineError("Installing the music engine's packages failed; see the Voxwell log.")


def _dir_bytes(path: Path) -> int:
    """Bytes under `path`, skipping files huggingface_hub renames or removes mid-count."""
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def _download_weights() -> None:
    from huggingface_hub import HfApi, snapshot_download
    from huggingface_hub.utils import filter_repo_objects

    checkpoints = source_dir() / "checkpoints"
    info = HfApi().model_info(WEIGHTS_REPO, revision=WEIGHTS_REVISION, files_metadata=True)
    wanted = set(filter_repo_objects([s.rfilename for s in info.siblings], allow_patterns=WEIGHTS))
    total = sum(s.size or 0 for s in info.siblings if s.rfilename in wanted) or 1
    _set(step=f"Downloading the model ({total / 1e9:.1f} GB)", percent=50, detail="")

    done = threading.Event()

    def report():
        while not done.wait(1.0):
            have = _dir_bytes(checkpoints) if checkpoints.exists() else 0
            _set(percent=50 + 50 * min(have / total, 1.0), detail=f"{have / 1e9:.2f} of {total / 1e9:.2f} GB")

    threading.Thread(target=report, daemon=True).start()
    try:
        snapshot_download(WEIGHTS_REPO, revision=WEIGHTS_REVISION, local_dir=checkpoints, allow_patterns=WEIGHTS)
    except Exception as exc:
        log.exception("Downloading the music model failed")
        raise EngineError("Could not download the music model. Check the internet connection and try again.") from exc
    finally:
        done.set()


# ---------------------------------------------------------------- server

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _log_path() -> Path:
    return data_dir("music") / "engine.log"


def log_tail(lines: int = 12) -> str:
    try:
        text = _log_path().read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    return "\n".join(text.strip().splitlines()[-lines:])


def _healthy(base: str) -> bool:
    try:
        with urllib.request.urlopen(base + "/health", timeout=5) as res:
            return res.status == 200
    except (OSError, urllib.error.URLError):
        return False


def ensure_running() -> tuple[str, str]:
    """Start the ACE-Step server if needed and wait until it serves; returns (base URL, API key)."""
    if not is_installed():
        raise EngineError("Install the music engine first.")
    with _server_lock:
        server = _server.get("current")
        if server and server["proc"].poll() is None and server["ready"]:
            return server["base"], server["key"]
        if not server or server["proc"].poll() is not None:
            server = _start()
            _server["current"] = server
        deadline = time.monotonic() + START_TIMEOUT_SECONDS
        while not _healthy(server["base"]):
            if server["proc"].poll() is not None:
                log.error("The music engine stopped while starting:\n%s", log_tail())
                raise EngineError("The music engine stopped while starting; see the Voxwell log.")
            if time.monotonic() > deadline:
                stop()
                log.error("The music engine took too long to start:\n%s", log_tail())
                raise EngineError("The music engine took too long to start; see the Voxwell log.")
            time.sleep(1.0)
        server["ready"] = True
        return server["base"], server["key"]


def _start() -> dict:
    port, key = _free_port(), secrets.token_urlsafe(32)
    env = {
        **os.environ,
        "ACESTEP_API_KEY": key,
        "ACESTEP_INIT_LLM": "false",
        "ACESTEP_TMPDIR": str(data_dir("music", "engine-tmp")),
        "HF_HUB_OFFLINE": "1",  # the weights are already in place; never download at start
    }
    log = _log_path().open("w", encoding="utf-8", errors="replace")
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        [str(_python()), "-I", "-u", "-X", "utf8", "-c", _HOST, str(port), str(os.getpid())],  # -u: the log shows progress live
        cwd=source_dir(),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    log.close()  # the child holds its own handle
    return {"proc": proc, "base": f"http://127.0.0.1:{port}", "key": key, "ready": False}


def stop() -> None:
    server = _server.pop("current", None)
    if server and server["proc"].poll() is None:
        server["proc"].kill()
        server["proc"].wait(timeout=30)
