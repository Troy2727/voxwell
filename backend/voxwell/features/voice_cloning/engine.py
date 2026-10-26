"""Speech synthesis engine. Shared contract: dubbing calls synthesize(); keep its signature."""

import io
import threading
import wave
from pathlib import Path

# Languages supported by Chatterbox Multilingual (ISO 639-1). Japanese is left out: Chatterbox
# needs the GPL-3.0 pykakasi package for it, which pyproject.toml excludes to keep the app MIT.
LANGUAGES = {
    "ar": "Arabic", "da": "Danish", "de": "German", "el": "Greek", "en": "English",
    "es": "Spanish", "fi": "Finnish", "fr": "French", "he": "Hebrew", "hi": "Hindi",
    "it": "Italian", "ko": "Korean", "ms": "Malay", "nl": "Dutch",
    "no": "Norwegian", "pl": "Polish", "pt": "Portuguese", "ru": "Russian",
    "sv": "Swedish", "sw": "Swahili", "tr": "Turkish", "zh": "Chinese",
}

_model = None
_lock = threading.Lock()


def _pick_device() -> str:
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _load_model():
    """Load and cache the model for this process."""
    global _model
    with _lock:
        if _model is None:
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS

            _model = ChatterboxMultilingualTTS.from_pretrained(device=_pick_device())
        return _model


def _to_wav(samples, sample_rate: int) -> bytes:
    import numpy as np

    arr = samples.detach().cpu().numpy() if hasattr(samples, "detach") else np.asarray(samples)
    arr = np.clip(arr.reshape(-1), -1.0, 1.0)
    pcm = (arr * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def synthesize(text: str, language: str, reference_audio: Path | None = None) -> bytes:
    """Return WAV bytes of `text` spoken in the voice of `reference_audio` (a default voice if None).

    `language` is an ISO 639-1 code such as "en".
    """
    if language not in LANGUAGES:
        raise ValueError(f"Unsupported language '{language}'.")
    model = _load_model()
    kwargs = {"language_id": language}
    if reference_audio is not None:
        kwargs["audio_prompt_path"] = str(reference_audio)
    with _lock:
        wav = model.generate(text, **kwargs)
    return _to_wav(wav, model.sr)
