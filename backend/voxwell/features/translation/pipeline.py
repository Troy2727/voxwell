"""Speech translation: transcribe, translate with M2M100, speak in the target language.

Used turn by turn by the live page and once per request by the CLI's `translate`.
"""

import base64
from pathlib import Path

from voxwell import live_audio, voices
from voxwell.features.audiobook.books import render_text
from voxwell.features.audiobook.chunking import chapter_chunks, chunks
from voxwell.features.dubbing import translate
from voxwell.features.voice_cloning.engine import LANGUAGES as SPEECH_LANGUAGES

# Languages Whisper (dictation's speech recognition) can transcribe; checked against the installed
# faster-whisper in test_model_api_contracts.py.
WHISPER_LANGUAGES = frozenset(
    "af am ar as az ba be bg bn bo br bs ca cs cy da de el en es et eu fa fi fo fr gl gu ha haw he hi "
    "hr ht hu hy id is it ja jw ka kk km kn ko la lb ln lo lt lv mg mi mk ml mn mr ms mt my ne nl nn no "
    "oc pa pl ps pt ro ru sa sd si sk sl sn so sq sr su sv sw ta te tg th tk tl tr tt uk ur uz vi yi yo "
    "yue zh".split()
)
# Spoken input must be recognized and translated; the output must be translated and spoken.
SOURCE_LANGUAGES = WHISPER_LANGUAGES & translate.LANGUAGES
TARGET_LANGUAGES = translate.LANGUAGES & SPEECH_LANGUAGES.keys()


class TranslationError(ValueError):
    """A request the pipeline cannot serve; the message is for the user."""


def check(source: str | None, target: str, voice: str | None) -> Path | None:
    """Validate the settings; returns the voice's reference clip (None for the default voice).

    `source` None means detect the spoken language.
    """
    if source is not None and source not in SOURCE_LANGUAGES:
        raise TranslationError(f"Unsupported source language '{source}'.")
    if target not in TARGET_LANGUAGES:
        raise TranslationError(f"Unsupported target language '{target}'. Choose one of: {', '.join(sorted(TARGET_LANGUAGES))}.")
    if not voice:
        return None
    try:
        return voices.voice_audio_path(voice)
    except KeyError:
        raise TranslationError(f"Unknown voice '{voice}'.")


def translate_text(text: str, source: str, target: str) -> str:
    """Translate sentence-sized pieces (M2M100 output is capped per call), keeping paragraphs."""
    if source not in translate.LANGUAGES:
        raise TranslationError(f"Translation does not support the language '{source}'.")
    paragraphs = [c for c in (chunks(p) for p in text.split("\n\n")) if c]
    return "\n\n".join(" ".join(translate.translate(pieces, source, target)) for pieces in paragraphs)


def speak(text: str, target: str, reference: Path | None) -> bytes:
    return render_text(chapter_chunks(text), target, reference)


def translate_turn(pcm: bytes, source: str | None, target: str, reference: Path | None) -> dict:
    """One live turn: transcript, translation and, when speech synthesis works, base64 WAV audio.

    A failed synthesis keeps the texts and adds a warning; a failed transcription or translation raises.
    """
    heard = live_audio.transcribe_turn(pcm, source)
    result = {"transcript": heard.text, "source": heard.language, "translation": ""}
    if not heard.text:
        return result
    result["translation"] = translate_text(heard.text, heard.language, target)
    if not result["translation"].strip():
        return result
    try:
        result["audio"] = base64.b64encode(speak(result["translation"], target, reference)).decode("ascii")
    except Exception as exc:
        result["warning"] = f"Could not speak the translation: {exc}"
    return result
