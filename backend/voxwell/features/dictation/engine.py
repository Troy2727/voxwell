"""Speech recognition engine. Shared contract: dubbing calls transcribe(); keep its signature."""

import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Segment:
    start: float  # seconds
    end: float
    text: str


@dataclass
class Transcript:
    text: str
    language: str  # ISO 639-1 code
    segments: list[Segment]


class AudioError(ValueError):
    """The audio is empty or cannot be decoded."""


DEFAULT_MODEL = "small"
_model = None
_lock = threading.Lock()


def _load_model():
    """Load faster-whisper once per process: CUDA (float16) if available, else CPU int8.

    CTranslate2 has no Apple MPS backend, so macOS uses CPU int8.
    """
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel
            import ctranslate2

            size = os.environ.get("VOXWELL_WHISPER_MODEL", DEFAULT_MODEL)
            if ctranslate2.get_cuda_device_count() > 0:
                _model = WhisperModel(size, device="cuda", compute_type="float16")
            else:
                _model = WhisperModel(size, device="cpu", compute_type="int8")
        return _model


def transcribe(
    audio_path: Path, language: str | None = None, on_progress: Callable[[float], None] | None = None
) -> Transcript:
    """Transcribe an audio file; detect the language when `language` is None.

    `on_progress`, if given, receives the fraction of the audio done (0..1) after each segment.
    """
    model = _load_model()
    try:
        segments, info = model.transcribe(str(audio_path), language=language or None)
        parts = []
        for s in segments:  # a generator: decoding happens as it is consumed
            parts.append(Segment(start=s.start, end=s.end, text=s.text.strip()))
            if on_progress and info.duration:
                on_progress(min(s.end / info.duration, 1.0))
    except Exception as exc:
        # PyAV (the decoder) raises its own error types for unreadable audio.
        if type(exc).__module__.split(".")[0] == "av":
            raise AudioError("Could not decode the audio.") from exc
        raise
    text = " ".join(p.text for p in parts if p.text).strip()
    return Transcript(text=text, language=info.language, segments=parts)


@dataclass
class Word:
    start: float  # seconds
    end: float
    text: str


@dataclass
class WordTimings:
    language: str  # ISO 639-1 code
    words: list[Word]


def transcribe_words(
    audio_path: Path, language: str | None = None, on_progress: Callable[[float], None] | None = None
) -> WordTimings:
    """Recognize an audio file with a timestamp for every word (used to align a known script).

    A sibling of transcribe() that asks faster-whisper for word timestamps; `on_progress` works as there.
    """
    model = _load_model()
    try:
        segments, info = model.transcribe(str(audio_path), language=language or None, word_timestamps=True)
        words = []
        for s in segments:
            words.extend(Word(w.start, w.end, w.word.strip()) for w in s.words or [] if w.word.strip())
            if on_progress and info.duration:
                on_progress(min(s.end / info.duration, 1.0))
    except Exception as exc:
        if type(exc).__module__.split(".")[0] == "av":
            raise AudioError("Could not decode the audio.") from exc
        raise
    return WordTimings(language=info.language, words=words)
