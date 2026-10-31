"""Voice isolation: split a recording into the voice and everything else (music, noise, effects).

Runs Voxwell's HTDemucs network (htdemucs.py) with Meta's published weights, downloaded once on
first use and checked against a pinned SHA-256 before loading.
"""

import hashlib
import shutil
import threading
import urllib.request
from pathlib import Path

from voxwell.features.tools import htdemucs
from voxwell.paths import data_dir, replace_file

WEIGHTS_URL = "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/955717e8-8726e21a.th"
WEIGHTS_SHA256 = "8726e21a993978c7ba086d3872e7608d7d5bfca646ca4aca459ffda844faa8b4"
OVERLAP = 0.25  # windows overlap by a quarter and are cross-faded

_model = None
_lock = threading.Lock()


class IsolationError(Exception):
    """A problem the user can fix or retry, with a message to show them."""


def _pick_device() -> str:
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def weights_path() -> Path:
    """The verified weights file, downloading it (84 MB) the first time."""
    path = data_dir("models", "isolation") / "htdemucs-955717e8.th"
    if path.exists():
        return path
    part = path.with_suffix(".part")
    try:
        with urllib.request.urlopen(WEIGHTS_URL, timeout=60) as response, part.open("wb") as out:
            shutil.copyfileobj(response, out)
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise IsolationError(f"Could not download the voice isolation model: {exc}")
    if _sha256(part) != WEIGHTS_SHA256:
        part.unlink(missing_ok=True)
        raise IsolationError("The downloaded voice isolation model is corrupted. Try again.")
    replace_file(part, path)
    return path


def load_state(path: Path) -> dict:
    """The checkpoint's tensors, loaded without running any code from the file.

    weights_only=True only rebuilds tensors and plain values. The checkpoint also names Meta's
    own model class (we build ours instead), so that name is mapped to an inert placeholder.
    """
    import fractions

    import numpy as np
    import torch

    class _MetaModelClass:
        pass

    allowed = [(_MetaModelClass, "demucs.htdemucs.HTDemucs"), fractions.Fraction, np.core.multiarray.scalar, np.dtype]
    allowed += [type(np.dtype(name)) for name in ("float32", "float64", "int64")]
    with torch.serialization.safe_globals(allowed):
        package = torch.load(path, map_location="cpu", weights_only=True)
    if list(package["kwargs"]["sources"]) != list(htdemucs.SOURCES):
        raise IsolationError("The voice isolation model file is not the expected one.")
    return {k: v.float() for k, v in package["state"].items()}


def _load_model():
    global _model
    with _lock:
        if _model is None:
            model = htdemucs.HTDemucs()
            model.load_state_dict(load_state(weights_path()))
            _model = model.to(_pick_device()).eval()
        return _model


def separate(mix, model=None):
    """(2, samples) stereo 44.1 kHz tensor -> (4, 2, samples), one track per htdemucs.SOURCES.

    The network takes fixed 7.8 s windows. Each window is centered on its slice of the track,
    filled with the real audio around it, and neighbouring windows are cross-faded with
    triangular weights so no seams are audible.
    """
    import torch

    model = model or _load_model()
    device = next(model.parameters()).device
    segment = htdemucs.SEGMENT
    stride = int((1 - OVERLAP) * segment)
    length = mix.shape[-1]

    ref = mix.mean(0)
    scale = ref.std() + 1e-8
    mix = (mix - ref.mean()) / scale

    half = segment // 2
    weight = torch.cat([torch.arange(1, half + 1), torch.arange(segment - half, 0, -1)]).float()
    weight /= weight.max()

    out = torch.zeros(len(htdemucs.SOURCES), 2, length)
    total = torch.zeros(length)
    for offset in range(0, length, stride):
        size = min(segment, length - offset)
        start = offset - (segment - size) // 2
        lo, hi = max(start, 0), min(start + segment, length)
        window = torch.nn.functional.pad(mix[:, lo:hi], (lo - start, start + segment - hi))
        with torch.no_grad():
            estimate = model(window[None].to(device))[0].cpu()
        trim = (segment - size) // 2
        out[..., offset : offset + size] += weight[:size] * estimate[..., trim : trim + size]
        total[offset : offset + size] += weight[:size]
    return out / total * scale + ref.mean()


def isolate(source: Path, voice_out: Path, background_out: Path) -> float:
    """Write the voice and the background (all other stems) as WAV files with the source's
    channel count, at 44.1 kHz. Returns the duration in seconds."""
    import soundfile as sf
    import torch
    import torchaudio

    try:
        audio, rate = sf.read(str(source), dtype="float32", always_2d=True)
    except (RuntimeError, TypeError, ValueError):
        raise IsolationError("Could not read the file as audio. Use WAV, MP3, FLAC or OGG.")
    if len(audio) == 0:
        raise IsolationError("The audio is empty.")
    channels = audio.shape[1]
    wav = torch.from_numpy(audio.T.copy())
    wav = wav[:2] if channels >= 2 else wav.expand(2, -1)
    if rate != htdemucs.SAMPLE_RATE:
        wav = torchaudio.functional.resample(wav, rate, htdemucs.SAMPLE_RATE)

    stems = separate(wav)
    vocals = htdemucs.SOURCES.index("vocals")
    voice = stems[vocals]
    background = stems.sum(0) - voice
    for track, path in ((voice, voice_out), (background, background_out)):
        if channels == 1:
            track = track.mean(0, keepdim=True)
        sf.write(str(path), track.clamp(-1, 1).T.numpy(), htdemucs.SAMPLE_RATE, subtype="PCM_16")
    return wav.shape[-1] / htdemucs.SAMPLE_RATE
