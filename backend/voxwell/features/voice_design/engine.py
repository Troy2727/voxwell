"""Text-description-conditioned TTS (Parler-TTS Mini v1, Apache-2.0)."""

import io
import threading

MODEL_ID = "parler-tts/parler-tts-mini-v1"

_lock = threading.Lock()
_cache: dict = {}


def _device() -> str:
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _load():
    with _lock:
        if not _cache:
            from parler_tts import ParlerTTSForConditionalGeneration
            from transformers import AutoTokenizer

            device = _device()
            _cache["model"] = ParlerTTSForConditionalGeneration.from_pretrained(MODEL_ID).to(device)
            _cache["tokenizer"] = AutoTokenizer.from_pretrained(MODEL_ID)
            _cache["device"] = device
    return _cache


def design(description: str, sample_text: str) -> bytes:
    """Synthesize sample_text in a voice matching description; returns WAV bytes."""
    import soundfile as sf

    c = _load()
    device, model, tok = c["device"], c["model"], c["tokenizer"]
    input_ids = tok(description, return_tensors="pt").input_ids.to(device)
    prompt_ids = tok(sample_text, return_tensors="pt").input_ids.to(device)
    out = model.generate(input_ids=input_ids, prompt_input_ids=prompt_ids)
    audio = out.cpu().numpy().squeeze()
    buf = io.BytesIO()
    sf.write(buf, audio, model.config.sampling_rate, format="WAV")
    return buf.getvalue()
