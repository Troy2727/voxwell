"""The dubbing pipeline: extract -> transcribe -> translate -> synthesize -> assemble -> mux."""

import array
import sys
import wave
from pathlib import Path
from typing import Callable

from voxwell import voices
from voxwell.features.dictation import engine as dictation_engine
from voxwell.features.dubbing import ffmpeg, fitting
from voxwell.features.dubbing import translate as translator
from voxwell.features.transcription import diarization
from voxwell.features.voice_cloning import engine as cloning_engine

RATE = 24000
Progress = Callable[[str, int], None]


def _read_wav(path: Path) -> list[int]:
    with wave.open(str(path), "rb") as w:
        data = array.array("h")
        data.frombytes(w.readframes(w.getnframes()))
    if sys.byteorder == "big":
        data.byteswap()
    return data.tolist()


def _write_wav(path: Path, samples: list[int]) -> None:
    data = array.array("h", samples)
    if sys.byteorder == "big":
        data.byteswap()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(data.tobytes())


def _normalize(src: Path, dst: Path, tempo: float = 1.0) -> list[int]:
    """Convert to mono 16-bit RATE Hz (optionally speeding up) and return the samples."""
    args = ["-i", str(src)]
    if tempo > 1.0:
        args += ["-filter:a", f"atempo={tempo:.4f}"]
    ffmpeg.run_ffmpeg([*args, "-ar", str(RATE), "-ac", "1", "-c:a", "pcm_s16le", str(dst)])
    return _read_wav(dst)


def _original_reference(job_dir: Path, audio: Path, spans: list[tuple[float, float]], name: str) -> Path:
    """A clean clip of the original speech to clone, cut from the longest of `spans`."""
    start, dur = fitting.reference_window(spans)
    reference = job_dir / name
    ffmpeg.run_ffmpeg(["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(audio), str(reference)])
    return reference


def run(job_dir: Path, video: Path, target: str, voice: str, progress: Progress, *, speakers: bool = False, num_speakers: int = 0) -> dict:
    """Run the full pipeline; returns {"video": Path, "subtitles": Path}.

    With `speakers`, each segment is labelled with who says it ("Speaker 1", ...). Cloning the original
    voice then uses a reference clip of each speaker's own voice, and the subtitles name the speaker.
    A saved voice speaks every line, whoever said it.
    """
    progress("Extracting audio", 2)
    audio = job_dir / "source.wav"
    ffmpeg.run_ffmpeg(["-i", str(video), "-vn", "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le", str(audio)])

    progress("Transcribing", 8)
    transcript = dictation_engine.transcribe(audio)
    segments = [s for s in transcript.segments if s.text.strip()]
    if not segments:
        raise ffmpeg.DubbingError("No speech was found in the video.")

    labels: list[str | None] = [None] * len(segments)
    if speakers:
        progress("Identifying speakers", 20)
        try:
            turns = diarization.diarize(audio, num_speakers)
        except diarization.DiarizationError as exc:
            raise ffmpeg.DubbingError(str(exc))
        labels = diarization.assign_speakers([(s.start, s.end) for s in segments], turns)

    progress("Translating", 30)
    texts = translator.translate([s.text.strip() for s in segments], transcript.language, target)

    progress("Preparing voice", 42)
    references: dict[str | None, Path] = {}  # speaker label (None: no labels) -> voice to clone
    if voice != "original":
        references[None] = voices.voice_audio_path(voice)
    else:
        for n, label in enumerate(dict.fromkeys(labels)):  # in order of first appearance
            spans = [(s.start, s.end) for s, who in zip(segments, labels) if who == label]
            references[label] = _original_reference(job_dir, audio, spans, f"reference{n or ''}.wav")

    track: list[int] = []
    for i, (seg, text) in enumerate(zip(segments, texts)):
        progress(f"Synthesizing speech ({i + 1}/{len(segments)})", 45 + int(45 * i / len(segments)))
        raw = job_dir / f"clip{i}.raw.wav"
        reference = references.get(labels[i], references.get(None))
        raw.write_bytes(cloning_engine.synthesize(text, target, reference))
        norm = job_dir / f"clip{i}.wav"
        samples = _normalize(raw, norm)
        tempo = fitting.tempo_for(len(samples) / RATE, seg.end - seg.start)
        if tempo > 1.0:
            samples = _normalize(norm, job_dir / f"clip{i}.fast.wav", tempo)
        nxt = segments[i + 1].start if i + 1 < len(segments) else None
        samples = fitting.fit_samples(samples, RATE, fitting.max_seconds(seg.start, seg.end, nxt))
        # Pad with silence up to the segment start; if a previous clip overran, just append.
        offset = int(seg.start * RATE)
        if len(track) < offset:
            track.extend([0] * (offset - len(track)))
        track.extend(samples)

    progress("Assembling video", 92)
    track_path = job_dir / "dubbed.wav"
    _write_wav(track_path, track)
    srt_path = job_dir / "subtitles.srt"
    srt = fitting.build_srt([(s.start, s.end, f"{who}: {t}" if who else t) for s, t, who in zip(segments, texts, labels)])
    srt_path.write_bytes(srt.encode("utf-8"))  # bytes: no CRLF translation on Windows
    out = job_dir / "dubbed.mp4"
    mux(video, track_path, out)
    return {"video": out, "subtitles": srt_path}


def mux(video: Path, track: Path, out: Path) -> None:
    """Put the dubbed track on the original picture. The track ends after the last line, so it is
    padded with silence (apad) and -shortest stops at the end of the video, never earlier."""
    ffmpeg.run_ffmpeg([
        "-i", str(video), "-i", str(track), "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-af", "apad", "-c:a", "aac", "-shortest", str(out),
    ])
