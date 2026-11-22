"""Free the GPU: when speech work has been idle a moment, move the speech models to system RAM.

Off by default. With it on, IDLE_SECONDS after the last synthesize() ends, each loaded model leaves
graphics memory for the processor, so other apps can use the card. The next take moves it back
before generating. A failed move never fails a take.
"""

import contextlib
import json
import logging
import tempfile
import threading
from pathlib import Path

from voxwell.paths import data_dir, replace_file

log = logging.getLogger(__name__)

IDLE_SECONDS = 10.0  # long enough that the gaps between lines of a story, book or dub don't trigger a move
CPU = "cpu"

_busy = 0
_state_lock = threading.Lock()
_timer: threading.Timer | None = None


def _config() -> Path:
    # Its own folder: voice_cloning's holds the history, which reads every *.json there.
    return data_dir("free_the_gpu") / "config.json"


def enabled() -> bool:
    """The saved preference; a missing or unreadable file means off."""
    try:
        return json.loads(_config().read_text(encoding="utf-8")).get("enabled") is True
    except (OSError, ValueError, AttributeError):
        return False


def set_enabled(value: bool) -> None:
    target = _config()
    with tempfile.NamedTemporaryFile("w", dir=target.parent, suffix=".tmp", delete=False, encoding="utf-8") as tmp:
        tmp.write(json.dumps({"enabled": value}))
    replace_file(Path(tmp.name), target)


@contextlib.contextmanager
def working():
    """Around speech work: no move while it runs, and the idle countdown starts when the last one ends."""
    global _busy
    with _state_lock:
        _busy += 1
    try:
        yield
    finally:
        with _state_lock:
            _busy -= 1
            idle = _busy == 0
        if idle:
            arm()


def arm() -> None:
    """Start (or restart) the idle countdown; nothing when the preference is off."""
    global _timer
    with _state_lock:
        if _timer is not None:
            _timer.cancel()
            _timer = None
        if not enabled():
            return
        _timer = threading.Timer(IDLE_SECONDS, fire)
        _timer.daemon = True
        _timer.start()


def fire() -> None:
    """The countdown ran out: move the loaded models unless speech work started meanwhile."""
    from voxwell.features.voice_cloning import engine

    if not enabled() or _busy:
        return
    if not engine._lock.acquire(blocking=False):  # a generation holds the models
        return
    try:
        if _busy:
            return
        for model in (engine._model, engine._turbo):
            if model is not None:
                _offload(model)
    finally:
        engine._lock.release()


def _offload(model) -> None:
    device = str(getattr(model, "device", CPU))
    if device == CPU or getattr(model, "voxwell_moved_from", None):
        return
    try:
        _move(model, CPU)
        model.voxwell_moved_from = device
        _empty_cache()
        log.info("Free the GPU: moved the speech model from %s to system RAM.", device)
    except Exception as exc:
        log.warning("Free the GPU: could not move the speech model (%s); it stays on %s.", type(exc).__name__, device)
        with contextlib.suppress(Exception):
            _move(model, device)


def restore_if_needed(model) -> None:
    """Before generating: put a moved model back on its own device. Hold engine._lock.

    If that fails (graphics memory full), the model stays whole on the processor, so the take still
    works, more slowly, and the next take tries again.
    """
    device = getattr(model, "voxwell_moved_from", None)
    if not device:
        return
    try:
        _move(model, device)
        del model.voxwell_moved_from
        log.info("Free the GPU: moved the speech model back to %s.", device)
    except Exception as exc:
        log.warning("Free the GPU: could not move the speech model back to %s (%s); this take runs on the processor.", device, type(exc).__name__)
        _move(model, CPU)
        _empty_cache()


def _move(model, device: str) -> None:
    """Chatterbox's models have no .to() of their own: move their networks and voice conditionals."""
    for name in ("t3", "s3gen", "ve"):
        if (part := getattr(model, name, None)) is not None:
            part.to(device)
    for name in ("conds", "voxwell_default_conds"):
        if (conds := getattr(model, name, None)) is not None:
            conds.to(device)
    model.device = device


def _empty_cache() -> None:
    with contextlib.suppress(Exception):
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            torch.mps.empty_cache()
