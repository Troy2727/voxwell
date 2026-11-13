"""Speech synthesis engine. Shared contract: dubbing calls synthesize(); keep its signature."""

import contextlib
import gc
import importlib.util
import io
import logging
import re
import threading
import wave
from pathlib import Path

from voxwell.features.audio_effects.dsp import Effects, apply_to_wav
from voxwell.features.pronunciation import store as pronunciation
from voxwell.features.voice_cloning import cues as cue_tags

log = logging.getLogger(__name__)

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

# Chatterbox-Turbo speaks English text that has cue tags ("[laugh]"); see cues.py.
TURBO_REPO = "ResembleAI/chatterbox-turbo"
# The files ChatterboxTurboTTS.from_local reads (the repo also holds an s3gen.safetensors it doesn't).
TURBO_FILES = ["ve.safetensors", "t3_turbo_v1.safetensors", "s3gen_meanflow.safetensors", "conds.pt", "*.json", "*.txt"]
TURBO_MIN_REFERENCE = 5.0  # seconds; Turbo refuses a reference clip that isn't longer than this
_turbo = None
_turbo_state: str | None = None  # "failed": Turbo is not tried again in this process
_turbo_rejected: set[str] = set()  # voices (str of the reference path) Turbo failed to speak with

# On CUDA, a model is loaded next to the other one only with at least this much free GPU memory;
# below it the other model is released first. 0 (never release) until both models' needs are
# measured on a real CUDA machine; meanwhile an out-of-memory load frees Multilingual and retries.
MIN_FREE_GPU_BYTES = 0


class NothingToSay(ValueError):
    """The text had only cue tags, and they were removed."""

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


def _multilingual_from_hub(device: str):
    from chatterbox.models.t3.inference.alignment_stream_analyzer import AlignmentStreamAnalyzer
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    _limit_tail(AlignmentStreamAnalyzer)
    with _torch_load_to_cpu():
        return ChatterboxMultilingualTTS.from_pretrained(device=device)


def _load_model():
    """Load and cache the model for this process."""
    global _model
    with _lock:
        if _model is None:
            device = _pick_device()
            _make_room(device, "turbo")
            _model = _keep_default_voice(_load_or_free(_multilingual_from_hub, device, "turbo"))
        return _model


def _load_or_free(load, device: str, other: str):
    """`load(device)`; if that runs out of memory, release the `other` model and try once more. Hold _lock."""
    try:
        return load(device)
    except Exception as exc:
        if not _out_of_memory(exc):
            raise
        _release(other, device)
        return load(device)


def _keep_default_voice(model):
    """Remember the model's built-in voice: a cloned voice replaces model.conds, and a later call
    without a voice must get the built-in one back, not the last clone."""
    model.voxwell_default_conds = getattr(model, "conds", None)
    return model


def _free_gpu_bytes() -> int:
    import torch

    return torch.cuda.mem_get_info()[0]


def _release(which: str, device: str) -> None:
    """Drop one cached model ("turbo" or "multilingual") so its memory can be reused. Hold _lock."""
    global _model, _turbo
    if which == "turbo":
        _turbo = None
    else:
        _model = None
    gc.collect()
    if device == "cuda":
        import torch

        torch.cuda.empty_cache()


def _make_room(device: str, other: str) -> None:
    """Before loading a model on CUDA: release the `other` one if free GPU memory is short. Hold _lock."""
    loaded = _turbo if other == "turbo" else _model
    if device == "cuda" and loaded is not None and _free_gpu_bytes() < MIN_FREE_GPU_BYTES:
        log.info("Low GPU memory: releasing the %s model to load the other one.", other)
        _release(other, device)


def _out_of_memory(exc: BaseException) -> bool:
    return isinstance(exc, MemoryError) or "out of memory" in str(exc).lower()


def _turbo_download() -> str:
    """Download Turbo's files (or find them cached) without a Hugging Face token; their folder.

    The package's own from_pretrained sends token=True, which fails for anyone without a Hugging
    Face login; the repo is public (MIT), so no token is needed.
    """
    from huggingface_hub import snapshot_download

    return snapshot_download(repo_id=TURBO_REPO, token=False, allow_patterns=TURBO_FILES)


def _turbo_from_folder(folder: str, device: str):
    from chatterbox.tts_turbo import ChatterboxTurboTTS

    with _torch_load_to_cpu():
        return ChatterboxTurboTTS.from_local(folder, device)


def _turbo_failed(exc: Exception) -> None:
    """Stop trying Turbo for this process. Also after running out of memory: on a GPU that fits one
    model, each retry would free Multilingual, fail again and reload it, request after request."""
    global _turbo_state
    _turbo_state = "failed"
    log.warning("Chatterbox-Turbo could not be loaded (%s); cue tags are left out of the speech.", exc)


def _load_turbo():
    """Load and cache Turbo for this process; None when it can't be loaded (cues are then left out)."""
    global _turbo
    if _turbo is not None or _turbo_state == "failed":
        return _turbo
    try:
        folder = _turbo_download()  # outside _lock: a first download takes minutes, and speech goes on meanwhile
    except Exception as exc:
        _turbo_failed(exc)
        return None
    with _lock:
        if _turbo is None and _turbo_state != "failed":
            device = _pick_device()
            _make_room(device, "multilingual")
            try:
                _turbo = _keep_default_voice(_load_or_free(lambda d: _turbo_from_folder(folder, d), device, "multilingual"))
            except Exception as exc:
                _turbo_failed(exc)
        return _turbo


def turbo_available() -> bool:
    """Whether the installed package has Turbo and it hasn't failed to load (no model load here)."""
    spec = importlib.util.find_spec("chatterbox")
    found = spec is not None and any((Path(p) / "tts_turbo.py").exists() for p in spec.submodule_search_locations or [])
    return found and _turbo_state != "failed"


def _long_enough_for_turbo(reference: Path | None) -> bool:
    """Whether Turbo accepts this reference clip (the built-in voice always works)."""
    if reference is None:
        return True
    import soundfile as sf

    try:
        return sf.info(str(reference)).duration > TURBO_MIN_REFERENCE
    except (RuntimeError, TypeError, ValueError):
        return False


def _turbo_accepts(reference: Path | None) -> bool:
    """Whether to try Turbo with this voice: long enough, and Turbo hasn't already failed on it."""
    return str(reference) not in _turbo_rejected and _long_enough_for_turbo(reference)


def cues_ignored(text: str, language: str, reference: Path | None = None) -> bool:
    """Whether `text` has cue tags that synthesize() leaves out instead of voicing."""
    if not cue_tags.find(text):
        return False
    voiced = language in cue_tags.VOICED_LANGUAGES and _turbo_accepts(reference) and _turbo_state is None
    return not voiced


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
    cues: bool = True,
) -> bytes:
    """Return WAV bytes of `text` spoken in the voice of `reference_audio` (a default voice if None).

    `language` is an ISO 639-1 code such as "en". `exaggeration` (0.25-2) sets emotional
    intensity; a lower `cfg_weight` (0-1) gives slower, more deliberate delivery. The defaults
    are Chatterbox's own. The language's pronunciation dictionary is applied to `text` first.
    `[pause]` or `[pause 2.5]` in `text` becomes that many seconds of silence (at most MAX_PAUSE).
    `effects` (speed, pitch, reverb, distance, noise, pan) is applied to the finished audio; without
    it, or with neutral settings, the bytes are exactly the model's.

    Cue tags ("[laugh]", see cues.py) in English text send the call to Chatterbox-Turbo, which then
    speaks the whole call (it ignores `exaggeration` and `cfg_weight`). Elsewhere, with `cues=False`,
    a reference clip too short for Turbo, or Turbo unavailable, they are removed. Raises
    NothingToSay (a ValueError) when nothing but removed cue tags was left to say.
    """
    if language not in LANGUAGES:
        raise ValueError(f"Unsupported language '{language}'.")

    out = None
    if cues and language in cue_tags.VOICED_LANGUAGES and cue_tags.find(text):
        if not _turbo_accepts(reference_audio):
            log.warning("This voice can't be used with cue tags (its clip must be longer than %s seconds); they are left out.", TURBO_MIN_REFERENCE)
        elif (turbo := _load_turbo()) is not None:
            try:
                out = _speak(text, language, reference_audio, turbo, {})
            except Exception:
                # E.g. a clip just over the limit by its header but not after Turbo resamples it.
                log.exception("Chatterbox-Turbo could not speak this; cue tags are left out.")
                _turbo_rejected.add(str(reference_audio))
    if out is None:
        multilingual = {"language_id": language, "exaggeration": exaggeration, "cfg_weight": cfg_weight}
        out = _speak(text, language, reference_audio, None, multilingual)
    return apply_to_wav(out, effects) if effects is not None else out


def _speak(text: str, language: str, reference_audio: Path | None, turbo, kwargs: dict) -> bytes:
    """synthesize() with Turbo (`turbo`, the loaded model) or, when it is None, Multilingual."""
    import numpy as np

    parts = split_pauses(text)
    plan = []
    for part in parts:
        if isinstance(part, str):
            prepared = _prepare(part, language, turbo is not None)
            if prepared != part and not any(c.isalnum() for c in prepared):
                continue  # only cue tags were here
            part = prepared
        plan.append(part)
    if not any(isinstance(p, str) for p in plan) and any(isinstance(p, str) for p in parts):
        raise NothingToSay("Nothing to say after removing cue tags.")

    model = turbo if turbo is not None else _load_model()
    # Turbo has no language, exaggeration or cfg_weight (it warns when they are set).
    if reference_audio is not None:
        kwargs = {**kwargs, "audio_prompt_path": str(reference_audio)}
    audio = []
    for part in plan:
        if isinstance(part, str):
            # Per part, so a dictionary entry can't rewrite a pause tag.
            part = _pronounce(part, language)
            with _lock:
                if reference_audio is None and getattr(model, "voxwell_default_conds", None) is not None:
                    model.conds = model.voxwell_default_conds  # not the voice of an earlier call
                audio.append(_flat(model.generate(part, **kwargs)))
        else:
            audio.append(np.zeros(int(part * model.sr), dtype=np.float32))
    return _to_wav(np.concatenate(audio), model.sr)


SAMPLE_RATE = 24000  # both Chatterbox models' output rate (their .sr); see test_model_api_contracts
SKIPPED_LINE = 0.3  # seconds of silence for a line that had nothing to say


def silent_clip() -> bytes:
    """The WAV a skipped line becomes, at the models' own rate so it joins their clips."""
    import numpy as np

    return _to_wav(np.zeros(int(SKIPPED_LINE * SAMPLE_RATE), dtype=np.float32), SAMPLE_RATE)


def synthesize_line(text: str, language: str, reference_audio: Path | None = None) -> bytes:
    """synthesize() for one line of a longer job (dubbing, stories): a line with nothing left to say
    once its cue tags are removed ("[Music]" in a transcript) becomes a short silence, so the job goes on."""
    try:
        return synthesize(text, language, reference_audio)
    except NothingToSay:
        log.info("Skipped a line with only cue tags: %r", text[:80])
        return silent_clip()


def _prepare(part: str, language: str, turbo: bool) -> str:
    """One spoken piece's cue tags as the chosen model should get them."""
    part = cue_tags.strip_reserved(part)
    if turbo:
        return cue_tags.canonical(part)  # Turbo's tag tokens are lowercase
    if language in cue_tags.VOICED_LANGUAGES or cue_tags.STRIP_OUTSIDE_VOICED:
        return cue_tags.strip_known(part)
    return part


def _pronounce(text: str, language: str) -> str:
    """The pronunciation dictionary applied to the text between cue tags, never to a tag."""
    out, start = [], 0
    for begin, end in cue_tags.spans(text):
        out += [pronunciation.apply(text[start:begin], language), text[begin:end]]
        start = end
    out.append(pronunciation.apply(text[start:], language))
    return "".join(out)
