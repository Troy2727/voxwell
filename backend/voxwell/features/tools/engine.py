"""Tool engines: voice conversion (Chatterbox VC), ffmpeg-based audio tools and Convert video."""

import io
import json
import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path

from voxwell.features.dubbing.ffmpeg import DubbingError, ffmpeg_path, run_ffmpeg
from voxwell.features.voice_cloning import engine as cloning

log = logging.getLogger(__name__)

MIN_TEMPO, MAX_TEMPO = 0.25, 4.0  # beyond this speech stops being intelligible

_vc = None
_lock = threading.Lock()


def _load_vc():
    global _vc
    with _lock:
        if _vc is None:
            from chatterbox.vc import ChatterboxVC

            # Same checkpoint quirk as voice cloning: load to CPU, then move to the device.
            with cloning._torch_load_to_cpu():
                _vc = ChatterboxVC.from_pretrained(device=cloning._pick_device())
        return _vc


def convert(source: Path, target_voice: Path) -> bytes:
    """Re-speak the recording in `source` with the voice of `target_voice`; WAV bytes."""
    model = _load_vc()
    with _lock:
        wav = model.generate(str(source), target_voice_path=str(target_voice))
    return cloning._to_wav(wav, model.sr)


def _atempo_chain(tempo: float) -> str:
    """ffmpeg's atempo takes 0.5..2.0 per filter, so larger changes are chained."""
    parts = []
    while tempo > 2.0:
        parts.append(2.0)
        tempo /= 2.0
    while tempo < 0.5:
        parts.append(0.5)
        tempo /= 0.5
    parts.append(tempo)
    return ",".join(f"atempo={p:.6f}" for p in parts)


def fit(source: Path, current_seconds: float, target_seconds: float, out: Path) -> None:
    """Time-stretch `source` to last `target_seconds` without changing its pitch."""
    tempo = current_seconds / target_seconds
    if not MIN_TEMPO <= tempo <= MAX_TEMPO:
        raise DubbingError(f"That is a {tempo:.2f}x speed change; choose a length between {MIN_TEMPO}x and {MAX_TEMPO}x.")
    run_ffmpeg(["-i", str(source), "-filter:a", _atempo_chain(tempo), "-c:a", "pcm_s16le", str(out)])


def ffprobe_path() -> str:
    """ffprobe ships next to ffmpeg; also look on PATH."""
    beside = Path(ffmpeg_path()).with_name("ffprobe" + (".exe" if os.name == "nt" else ""))
    found = str(beside) if beside.exists() else shutil.which("ffprobe")
    if not found:
        raise DubbingError("ffprobe was not found. It comes with ffmpeg; reinstall ffmpeg.")
    return found


def probe(source: Path) -> dict:
    """Format, duration and streams of a media file, from ffprobe."""
    cmd = [ffprobe_path(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(source)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    except OSError as exc:
        log.exception("Could not run ffprobe")
        raise DubbingError("Could not run ffprobe; see the Voxwell log.") from exc
    if proc.returncode != 0:
        raise DubbingError("This file could not be read as audio or video.")
    data = json.loads(proc.stdout or "{}")
    fmt = data.get("format", {})
    streams = []
    for s in data.get("streams", []):
        kind = s.get("codec_type")
        if kind not in ("audio", "video", "subtitle"):
            continue
        entry = {"type": kind, "codec": s.get("codec_long_name") or s.get("codec_name")}
        if kind == "audio":
            entry.update(sample_rate=int(s.get("sample_rate", 0)) or None, channels=s.get("channels"))
        elif kind == "video":
            entry.update(width=s.get("width"), height=s.get("height"), fps=_fps(s.get("avg_frame_rate")))
        if (lang := s.get("tags", {}).get("language")) and lang != "und":  # "und" = undetermined
            entry["language"] = lang
        streams.append(entry)
    return {
        "format": fmt.get("format_long_name") or fmt.get("format_name"),
        "duration": float(fmt["duration"]) if fmt.get("duration") else None,
        "size": int(fmt.get("size", 0)) or None,
        "bit_rate": int(fmt.get("bit_rate", 0)) or None,
        "streams": streams,
    }


def _fps(rate: str | None) -> float | None:
    try:
        num, den = (rate or "").split("/")
        return round(int(num) / int(den), 2) if int(den) else None
    except ValueError:
        return None


# --- Convert video ------------------------------------------------------------------------------

NOT_A_VIDEO = "Could not read the file as a video. Use MP4, MOV, MKV or WebM."
CONVERT_PIECE_SECONDS = 25.0  # longest stretch handed to the conversion model at once (a guess, not measured)
CUT_SEARCH_SECONDS = 5.0  # a piece ends at the quietest moment in its last few seconds
CUT_FRAME_SECONDS = 0.02
VOICE_GAIN = 1.1  # the new voice sits slightly in front of the background (about +0.8 dB)
MIX_CEILING = 0.98


def video_streams(source: Path) -> tuple[int | None, bool]:
    """(index of the first real picture stream or None, has sound) for an uploaded video; DubbingError
    when it can't be read as one.

    Text is never a video: a playlist or a list of other files is refused before ffprobe reads it,
    so it can't make ffprobe open anything else. ffprobe is also limited to local files.
    """
    with source.open("rb") as f:
        head = f.read(4096)
    if not head or b"\x00" not in head:
        raise DubbingError(NOT_A_VIDEO)
    cmd = [ffprobe_path(), "-v", "error", "-protocol_whitelist", "file", "-print_format", "json", "-show_streams", str(source)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    except OSError as exc:
        log.exception("Could not run ffprobe")
        raise DubbingError("Could not run ffprobe; see the Voxwell log.") from exc
    if proc.returncode != 0:
        raise DubbingError(NOT_A_VIDEO)
    streams = json.loads(proc.stdout or "{}").get("streams", [])
    # An attached picture (an album cover in an audio file) is not a video.
    pictures = [s.get("index") for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")]
    return (pictures[0] if pictures else None), any(s.get("codec_type") == "audio" for s in streams)


def extract_soundtrack(video: Path, out: Path, max_seconds: float) -> None:
    """The video's first sound track as a 44.1 kHz stereo WAV, at most max_seconds long."""
    run_ffmpeg(["-protocol_whitelist", "file", "-i", str(video), "-map", "0:a:0", "-vn", "-ac", "2", "-ar", "44100",
                "-c:a", "pcm_s16le", "-t", str(max_seconds), str(out)])


def piece_bounds(samples, rate: int, longest: float = CONVERT_PIECE_SECONDS) -> list[tuple[int, int]]:
    """(start, end) samples of pieces of at most longest seconds that cover the track exactly.

    Each cut falls on the quietest 20 ms frame in the last CUT_SEARCH_SECONDS of its piece (the latest
    of equally quiet ones), so a word is not cut in half.
    """
    import numpy as np

    limit, search = int(longest * rate), int(CUT_SEARCH_SECONDS * rate)
    frame = max(1, int(CUT_FRAME_SECONDS * rate))
    bounds, start = [], 0
    while len(samples) - start > limit:
        low = start + limit - search
        window = np.asarray(samples[low : start + limit], dtype=np.float64)
        energy = np.square(window[: len(window) // frame * frame]).reshape(-1, frame).sum(axis=1)
        cut = low + int(np.flatnonzero(energy == energy.min())[-1]) * frame
        bounds.append((start, cut))
        start = cut
    bounds.append((start, len(samples)))
    return bounds


def convert_long(source: Path, target_voice: Path, work: Path):
    """convert() for a recording of any length, piece by piece (see piece_bounds); (mono samples, rate)."""
    import numpy as np
    import soundfile as sf

    audio, rate = sf.read(str(source), dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    out, out_rate = [], rate
    for i, (start, end) in enumerate(piece_bounds(mono, rate)):
        piece = work / f"piece-{i}.wav"
        sf.write(str(piece), mono[start:end], rate, subtype="PCM_16")
        converted, out_rate = sf.read(io.BytesIO(convert(piece, target_voice)), dtype="float32")
        out.append(converted.reshape(-1))
        piece.unlink(missing_ok=True)
    return np.concatenate(out), out_rate


def mix_voice(background: Path, voice, voice_rate: int, out: Path) -> None:
    """The new voice (mono, centred) over the background at its own level, as one 16-bit WAV.

    Nothing is turned down to make room: the background keeps its level, and only the samples the sum
    pushes past MIX_CEILING are held there.
    """
    import math

    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly

    bed, rate = sf.read(str(background), dtype="float32", always_2d=True)
    if voice_rate != rate:
        g = math.gcd(rate, voice_rate)
        voice = resample_poly(voice, rate // g, voice_rate // g)
    mix = np.zeros((max(len(bed), len(voice)), bed.shape[1]), dtype=np.float32)
    mix[: len(bed)] += bed
    mix[: len(voice)] += (np.asarray(voice, dtype=np.float32) * VOICE_GAIN)[:, None]
    np.clip(mix, -MIX_CEILING, MIX_CEILING, out=mix)
    sf.write(str(out), mix, rate, subtype="PCM_16")


def rebuild_video(video: Path, track: Path, out: Path, picture: int = 0) -> None:
    """The original picture (stream number picture), copied as is, with track as its only sound (AAC), as an MP4.

    The sound is padded with silence and cut at the end of the picture.
    """
    run_ffmpeg(["-protocol_whitelist", "file", "-i", str(video), "-i", str(track), "-map", f"0:{picture}", "-map", "1:a:0",
                "-c:v", "copy", "-af", "apad", "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(out)])
