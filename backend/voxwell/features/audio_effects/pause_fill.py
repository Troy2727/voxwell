"""Natural pauses: fill the pauses between speech with the take's own quiet background, not silence.

A take is all the speech whose background a pause should match: one Voice cloning text, a whole story,
a whole audiobook chapter. Voxwell models that background as filtered noise:

1. Loudness per 20 ms frame, piece by piece. The background floor is a low percentile of the frames that
   aren't digital silence; the background is every frame within a few dB of that floor.
2. Its colour is an all-pole (linear prediction) filter fitted to those frames' autocorrelation, and its
   loudness is their mean frame level. Too little speech, or a floor as loud as speech, means there is
   nothing to match, and the pauses stay silent.
3. Each pause gets new white noise from a generator seeded by the take and the pause's place, run through
   that filter and set to that loudness. It fades in and out over 30 ms reaching into the speech on each
   side, so the background carries straight through.

Plain numpy and scipy, no models, deterministic; imported inside functions, as in dsp.py.
"""

import io
import wave
import zlib

from voxwell.features.audio_effects.dsp import CEILING, NOISE_SEED

FRAME_SECONDS = 0.02
SILENT_DBFS = -80.0  # quieter frames are padding or trimming, not background
FLOOR_PERCENTILE = 10  # the background floor: this percentile of the live frames' levels
FLOOR_SPAN_DB = 6.0  # frames up to this much above the floor count as background
MIN_FRAMES = 10  # fewer live frames than this: too little speech to measure
LOUDEST_BACKGROUND_DBFS = -35.0  # a floor louder than this is speech, not background
FILTER_ORDER = 12
MAX_FIT_FRAMES = 2000  # enough to fit the filter; a long chapter's frames are sampled evenly down to this
EDGE_SECONDS = 0.03


def _frame_levels(piece, size: int):
    """RMS level of each whole frame of one piece (float32, one piece at a time to keep memory small)."""
    import numpy as np

    frames = np.asarray(piece, dtype=np.float32)[: len(piece) // size * size].reshape(-1, size)
    return np.sqrt(np.einsum("ij,ij->i", frames, frames) / size)


def _all_pole(r):
    """Prediction filter coefficients [1, a1..ap] for autocorrelation r (Levinson recursion)."""
    import numpy as np

    a, err = np.array([1.0]), r[0]
    for i in range(1, len(r)):
        if err <= 0:
            break
        k = -(r[i] + np.dot(a[1:], r[i - 1 : 0 : -1])) / err
        a = np.concatenate([a, [0.0]])
        a = a + k * a[::-1]
        err *= 1 - k * k
    return a


def background(pieces: list, rate: int):
    """(filter, level, seed) describing the take's background, or None when there is nothing to match."""
    import numpy as np

    size = max(int(rate * FRAME_SECONDS), 16)
    levels = [_frame_levels(p, size) for p in pieces]
    live = np.concatenate([lv[lv > 10 ** (SILENT_DBFS / 20)] for lv in levels]) if levels else np.zeros(0)
    if len(live) < MIN_FRAMES:
        return None
    floor = np.percentile(live, FLOOR_PERCENTILE)
    if floor > 10 ** (LOUDEST_BACKGROUND_DBFS / 20):
        return None
    limit = floor * 10 ** (FLOOR_SPAN_DB / 20)
    quiet = [np.flatnonzero((lv > 10 ** (SILENT_DBFS / 20)) & (lv <= limit)) for lv in levels]
    every = max(1, sum(len(q) for q in quiet) // MAX_FIT_FRAMES)
    r, used, total = np.zeros(FILTER_ORDER + 1), 0, 0.0
    for piece, lv, picked in zip(pieces, levels, quiet):
        for start in picked[::every] * size:
            frame = np.asarray(piece[start : start + size], dtype=np.float64)
            r += [np.dot(frame[: size - lag], frame[lag:]) for lag in range(FILTER_ORDER + 1)]
        used += len(picked)
        total += float(lv[picked].sum())
    if not used or r[0] <= 0:
        return None
    r[0] *= 1.001  # a little white floor keeps the filter well behaved
    seed = zlib.crc32(np.asarray(pieces[0], dtype=np.float32).tobytes()) ^ NOISE_SEED
    return _all_pole(r), total / used, seed


def _noise(n: int, bg, index: int):
    import numpy as np
    from scipy.signal import lfilter

    a, level, seed = bg
    shaped = lfilter([1.0], a, np.random.default_rng([seed, index]).standard_normal(n))
    loudness = float(np.sqrt(np.mean(shaped**2))) if n else 0.0
    return shaped * (level / loudness) if loudness > 0 else np.zeros(n)


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
    speech = [p for item, p in zip(merged, parts) if not isinstance(item, int)]
    bg = background(speech, rate) if speech else None
    if bg is None:
        return out
    loudest = max(float(np.max(np.abs(p))) for p in speech if len(p)) if any(len(p) for p in speech) else 0.0
    edge, starts = int(rate * EDGE_SECONDS), np.cumsum([0] + [len(p) for p in parts])
    for index, item in enumerate(merged):
        if not isinstance(item, int) or item <= 0:
            continue
        # Reach into the speech on each side, never past that piece (into another pause's fade).
        before = min(edge, len(parts[index - 1])) if index > 0 else 0
        after = min(edge, len(parts[index + 1])) if index + 1 < len(parts) else 0
        start, n = starts[index] - before, before + item + after
        steps = np.arange(n, dtype=np.float64)
        fade = np.minimum(1.0, np.minimum((steps + 1) / (before + 1), (n - steps) / (after + 1)))
        out[start : start + n] += (_noise(n, bg, index) * fade).astype(np.float32)
    # The noise may only push peaks up to the ceiling, or to the speech's own peak if that is higher.
    return np.clip(out, -max(CEILING, loudest), max(CEILING, loudest))


def join_wavs(parts: list[tuple[bytes, float]]) -> bytes:
    """16-bit mono WAV clips of one rate, each followed by its pause (seconds), as one WAV with natural pauses."""
    import numpy as np

    if not parts:
        raise ValueError("Nothing to join.")
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
