"""Text-to-sound engine: Stable Audio Open through diffusers' StableAudioPipeline."""

import io
import threading

MODEL_ID = "stabilityai/stable-audio-open-1.0"
MODEL_URL = f"https://huggingface.co/{MODEL_ID}"
NEGATIVE_PROMPT = "Low quality."

_pipeline = None
_load_lock = threading.Lock()
_generate_lock = threading.Lock()


class AccessError(Exception):
    """The model is gated and the token is missing, wrong, or has not accepted the terms."""


class Busy(Exception):
    """Another sound is being generated."""


ACCESS_MESSAGE = (
    f"Stable Audio Open is a gated model. Accept its terms at {MODEL_URL} while signed in to Hugging Face, "
    "then save a Hugging Face access token (read permission) here or set the HF_TOKEN environment variable."
)


def _pick_device() -> str:
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def is_installed() -> bool:
    """True when the model is already in the local Hugging Face cache (no network)."""
    try:
        from huggingface_hub import try_to_load_from_cache
    except ImportError:
        return False
    return isinstance(try_to_load_from_cache(MODEL_ID, "model_index.json"), str)


def _is_access_error(exc: Exception) -> bool:
    from huggingface_hub.errors import GatedRepoError, HfHubHTTPError, RepositoryNotFoundError

    if isinstance(exc, (GatedRepoError, RepositoryNotFoundError)):
        return True
    if isinstance(exc, HfHubHTTPError) and getattr(exc.response, "status_code", None) in (401, 403):
        return True
    text = str(exc).lower()
    return "gated repo" in text or "401 client error" in text or "403 client error" in text


def _load(token: str | None):
    """Load and cache the pipeline for this process."""
    global _pipeline
    with _load_lock:
        if _pipeline is None:
            import torch
            from diffusers import StableAudioPipeline

            device = _pick_device()
            dtype = torch.float16 if device == "cuda" else torch.float32
            try:
                pipe = StableAudioPipeline.from_pretrained(MODEL_ID, torch_dtype=dtype, token=token)
            except Exception as exc:
                if _is_access_error(exc):
                    raise AccessError(ACCESS_MESSAGE) from None
                raise
            _pipeline = pipe.to(device)
        return _pipeline


def _to_wav(audio, sample_rate: int, seconds: float) -> bytes:
    """`audio` is (channels, samples) floats; trim to `seconds` and encode 16-bit WAV."""
    import numpy as np
    import soundfile as sf

    arr = audio.detach().cpu().float().numpy() if hasattr(audio, "detach") else np.asarray(audio, dtype="float32")
    arr = np.clip(arr[:, : int(sample_rate * seconds)].T, -1.0, 1.0)
    buf = io.BytesIO()
    sf.write(buf, arr, sample_rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def generate(prompt: str, duration: float, steps: int, seed: int, token: str | None) -> bytes:
    """Return WAV bytes (stereo, 44.1 kHz) of `duration` seconds for `prompt`. One at a time."""
    if not _generate_lock.acquire(blocking=False):
        raise Busy()
    try:
        import torch

        pipe = _load(token)
        generator = torch.Generator("cpu").manual_seed(seed)
        result = pipe(
            prompt,
            negative_prompt=NEGATIVE_PROMPT,
            num_inference_steps=steps,
            audio_end_in_s=duration,
            num_waveforms_per_prompt=1,
            generator=generator,
        )
        return _to_wav(result.audios[0], pipe.vae.sampling_rate, duration)
    finally:
        _generate_lock.release()
