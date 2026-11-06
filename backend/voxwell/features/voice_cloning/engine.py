"""Speech synthesis engine. Shared contract: dubbing calls synthesize(); keep its signature."""

import contextlib
import io
import re
import threading
import wave
from pathlib import Path

from voxwell.features.audio_effects.dsp import Effects, apply_to_wav
from voxwell.features.pronunciation import store as pronunciation

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

# Chatterbox sometimes keeps talking after the text ends: made-up words, up to seconds of them
# (3 of 21 test clips). Its own end checks miss this, so generation is also stopped this many
# frames (25 per second) after its attention reaches the end of the text. Checked on 21 clips
# (short, long, slow, Spanish), transcribed back: 15 left no extra words and cut no last word;
# 25 still let 1-2 stray syllables through in 2 of them.
TAIL_FRAMES = 15

# "[pause]" or "[pause 2.5]" in the text becomes silence instead of being read out.
_PAUSE = re.compile(r"\[pause(?:\s+(\d+(?:\.\d+)?))?\]", re.IGNORECASE)
DEFAULT_PAUSE = 0.75  # seconds
MAX_PAUSE = 10.0  # seconds


def _pick_device() -> str:
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


@contextlib.contextmanager
def _torch_load_to_cpu():
    """Make torch.load default to map_location="cpu" for the duration.

    chatterbox-tts 0.1.6 calls torch.load() without map_location on checkpoints saved from
    CUDA, which fails on CPU-only and Apple machines. Loading to CPU is always safe: the
    library moves each module to the chosen device right after loading it.
    """
    import torch

    original = torch.load

    def load(*args, **kwargs):
        kwargs.setdefault("map_location", "cpu")
        return original(*args, **kwargs)

    torch.load = load
    try:
        yield
    finally:
        torch.load = original


def _finish_short_text_step(self, logits, next_token):
    """The rest of Chatterbox 0.1.6's AlignmentStreamAnalyzer.step after its repetition check."""
    import torch

    if next_token is not None:
        token = next_token.view(-1)[0].item() if isinstance(next_token, torch.Tensor) else next_token
        self.generated_tokens = (self.generated_tokens + [token])[-8:]
    long_tail = self.complete and self.alignment[self.completed_at:, -3:].sum(dim=0).max() >= 5
    token_repetition = len(self.generated_tokens) >= 3 and len(set(self.generated_tokens[-2:])) == 1
    if long_tail or token_repetition:
        logits = logits.new_full(logits.shape, -(2**15))
        logits[..., self.eos_idx] = 2**15
    self.curr_frame_pos += 1
    return logits


def _limit_tail(analyzer_cls) -> None:
    """Make the analyzer force the end-of-speech token TAIL_FRAMES frames after the text ends.

    Chatterbox creates a new AlignmentStreamAnalyzer per generation and calls step() once per
    frame; forcing the stop token is what its own checks do too.
    """
    original = analyzer_cls.step
    if getattr(original, "voxwell_tail_limit", False):
        return

    def step(self, logits, next_token=None):
        try:
            logits = original(self, logits, next_token)
        except IndexError:
            # Chatterbox's repetition check looks at the text tokens before the last 5. A text of
            # 5 tokens or fewer ("Two.") has none, and max() over that empty slice raises. The
            # check can't fire then, so finish the step the way Chatterbox would without it.
            if self.alignment.shape[1] > 5:
                raise
            logits = _finish_short_text_step(self, logits, next_token)
        if self.completed_at is not None and self.curr_frame_pos - self.completed_at > TAIL_FRAMES:
            logits = logits.new_full(logits.shape, -(2**15))
            logits[..., self.eos_idx] = 2**15
        return logits

    step.voxwell_tail_limit = True
    analyzer_cls.step = step


def _load_model():
    """Load and cache the model for this process."""
    global _model
    with _lock:
        if _model is None:
            from chatterbox.models.t3.inference.alignment_stream_analyzer import AlignmentStreamAnalyzer
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS

            _limit_tail(AlignmentStreamAnalyzer)
            with _torch_load_to_cpu():
                _model = ChatterboxMultilingualTTS.from_pretrained(device=_pick_device())
        return _model


def split_pauses(text: str) -> list[str | float]:
    """`text` as its spoken parts (str) and the pauses between them (seconds), in order."""
    parts: list[str | float] = []

    def spoken(chunk: str) -> None:
        chunk = chunk.strip()
        if any(c.isalnum() for c in chunk):  # lone punctuation between two tags isn't speech
            parts.append(chunk)

    start = 0
    for match in _PAUSE.finditer(text):
        spoken(text[start : match.start()])
        parts.append(min(float(match[1]), MAX_PAUSE) if match[1] else DEFAULT_PAUSE)
        start = match.end()
    spoken(text[start:])
    return parts or [text]


def _flat(samples):
    """Model output (a tensor) as a flat numpy array."""
    import numpy as np

    arr = samples.detach().cpu().numpy() if hasattr(samples, "detach") else np.asarray(samples)
    return arr.reshape(-1)


def _to_wav(samples, sample_rate: int) -> bytes:
    import numpy as np

    arr = np.clip(_flat(samples), -1.0, 1.0)
    pcm = (arr * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def synthesize(
    text: str,
    language: str,
    reference_audio: Path | None = None,
    *,
    exaggeration: float = 0.5,
    cfg_weight: float = 0.5,
    effects: Effects | None = None,
) -> bytes:
    """Return WAV bytes of `text` spoken in the voice of `reference_audio` (a default voice if None).

    `language` is an ISO 639-1 code such as "en". `exaggeration` (0.25-2) sets emotional
    intensity; a lower `cfg_weight` (0-1) gives slower, more deliberate delivery. The defaults
    are Chatterbox's own. The language's pronunciation dictionary is applied to `text` first.
    `[pause]` or `[pause 2.5]` in `text` becomes that many seconds of silence (at most MAX_PAUSE).
    `effects` (speed, pitch, reverb, distance, noise, pan) is applied to the finished audio; without
    it, or with neutral settings, the bytes are exactly the model's.
    """
    if language not in LANGUAGES:
        raise ValueError(f"Unsupported language '{language}'.")
    import numpy as np

    model = _load_model()
    kwargs = {"language_id": language, "exaggeration": exaggeration, "cfg_weight": cfg_weight}
    if reference_audio is not None:
        kwargs["audio_prompt_path"] = str(reference_audio)
    audio = []
    for part in split_pauses(text):
        if isinstance(part, str):
            # Per part, so a dictionary entry can't rewrite a pause tag.
            part = pronunciation.apply(part, language)
            with _lock:
                audio.append(_flat(model.generate(part, **kwargs)))
        else:
            audio.append(np.zeros(int(part * model.sr), dtype=np.float32))
    out = _to_wav(np.concatenate(audio), model.sr)
    return apply_to_wav(out, effects) if effects is not None else out
