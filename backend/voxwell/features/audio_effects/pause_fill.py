"""Natural pauses: fill the pauses between speech with the take's own quiet background, not silence.

A take is all the speech whose background a pause should match: one Voice cloning text, a whole story,
a whole audiobook chapter. Its background is the quietest fifth of its 20 ms frames (frames of digital
silence aside): their level, and their spectrum smoothed so no single tone is copied. Each pause gets
fresh noise of that colour and level, seeded so the same input always sounds the same, and blends 30 ms
into the speech on either side so the background never dips at the edges. With nothing to match (too
little speech, no quiet stretch, only digital silence) a pause stays silent.

Plain numpy, no models; numpy is imported inside functions, as in dsp.py.
"""

import io
import wave

from voxwell.features.audio_effects.dsp import CEILING, NOISE_SEED

FRAME_SECONDS = 0.02
SILENT_DBFS = -80.0  # quieter frames are padding or trimming, not background
QUIET_SHARE = 0.2  # the quietest fifth of the frames is the background
MIN_FRAMES = 10  # fewer live frames than this: too little speech to measure
MIN_QUIET_FRAMES = 3
LOUDEST_BACKGROUND_DBFS = -35.0  # a "quiet" stretch louder than this is speech, not background
SMOOTH_BINS = 9
EDGE_SECONDS = 0.03


def _db(value: float) -> float:
    return 10 ** (value / 20)


def background(pieces: list, rate: int):
    """(level, spectrum, frame size) of the take's background, or None when there is nothing to match."""
    import numpy as np

    size = max(int(rate * FRAME_SECONDS), 16)
    frames = [np.asarray(p, dtype=np.float64)[: len(p) // size * size].reshape(-1, size) for p in pieces if len(p) >= size]
    if not frames:
        return None
    frames = np.concatenate(frames)
    rms = np.sqrt(np.mean(frames**2, axis=1))
    live = rms > _db(SILENT_DBFS)
    if live.sum() < MIN_FRAMES:
        return None
    frames, rms = frames[live], rms[live]
    quiet = frames[np.argsort(rms)[: max(MIN_QUIET_FRAMES, int(len(frames) * QUIET_SHARE))]]
    level = float(np.sqrt(np.mean(quiet**2)))
    if level > _db(LOUDEST_BACKGROUND_DBFS):
        return None
    spectrum = np.abs(np.fft.rfft(quiet * np.hanning(size), axis=1)).mean(axis=0)
    spectrum = np.convolve(spectrum, np.ones(SMOOTH_BINS) / SMOOTH_BINS, mode="same")
    return level, spectrum


def _noise(n: int, bg, seed: int):
    import numpy as np

    level, spectrum = bg
    white = np.random.RandomState(seed).standard_normal(n)
    shape = np.interp(np.linspace(0, 1, n // 2 + 1), np.linspace(0, 1, len(spectrum)), spectrum)
    shaped = np.fft.irfft(np.fft.rfft(white) * shape, n)
    rms = np.sqrt(np.mean(shaped**2)) if n else 0
    return shaped * (level / rms) if rms > 0 else np.zeros(n)


def join(items: list, rate: int):
    """Speech (mono float arrays) and pauses (whole samples, ints), in order, as one float32 array.

    It is exactly as long as with silent pauses; touching pauses count as one.
    """
    import numpy as np

    merged = []
    for item in items:
        if isinstance(item, int) and merged and isinstance(merged[-1], int):
            merged[-1] += item
        else:
            merged.append(item)
    parts = [np.zeros(item, dtype=np.float32) if isinstance(item, int) else np.asarray(item, dtype=np.float32) for item in merged]
    out = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
    bg = background([p for p in merged if not isinstance(p, int)], rate)
    if bg is None:
        return out
    edge, pos, gap = int(rate * EDGE_SECONDS), 0, 0
    for index, (item, part) in enumerate(zip(merged, parts)):
        if isinstance(item, int) and item > 0:
            before = min(edge if index > 0 else 0, pos)
            after = min(edge if index < len(merged) - 1 else 0, len(out) - pos - item)
            envelope = np.ones(before + item + after)
            envelope[:before] = np.linspace(0, 1, before, endpoint=False)
            if after:
                envelope[-after:] = np.linspace(1, 0, after, endpoint=False)
            out[pos - before : pos + item + after] += (_noise(len(envelope), bg, NOISE_SEED + gap) * envelope).astype(np.float32)
            gap += 1
        pos += len(part)
    peak = float(np.max(np.abs(out))) if len(out) else 0.0
    return out * (CEILING / peak) if peak > CEILING else out


def join_wavs(parts: list[tuple[bytes, float]]) -> bytes:
    """16-bit mono WAV clips of one rate, each followed by its pause (seconds), as one WAV with natural pauses."""
    import numpy as np

    items, rate = [], None
    for clip, pause in parts:
        with wave.open(io.BytesIO(clip)) as w:
            rate = rate or w.getframerate()
            items.append(np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768)
        if pause > 0:
            items.append(int(rate * pause))
    pcm = (np.clip(join(items, rate), -1, 1) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm.tobytes())
    return buf.getvalue()
