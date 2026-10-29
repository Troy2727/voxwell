"""Audio effects for generated speech: reverb, distance, background noise and stereo pan.

Plain numpy/scipy DSP, no models. Everything is deterministic (fixed noise seeds), so the same
settings always give the same audio. Neutral settings return the input untouched, and the result
is peak-limited so it never goes above 0 dBFS. numpy and scipy are imported inside functions so
the server starts fast.
"""

import io
import math
from typing import Literal

from pydantic import BaseModel, Field

CEILING = 0.98  # peak limit (about -0.18 dBFS), linear
REVERB_SECONDS = 0.9  # decay time of the synthetic room (RT60)
REVERB_WET = 0.7  # wet share at reverb = 1
DISTANCE_CUTOFF_NEAR, DISTANCE_CUTOFF_FAR = 12000.0, 1200.0  # low-pass at distance 0 and 1 (Hz)
DISTANCE_DRY_DB, DISTANCE_WET_DB = -18.0, -6.0  # level drop of the direct and reverberant sound at distance 1
DISTANCE_EXTRA_WET = 0.4  # distance 1 adds this much reverb
NOISE_DB_MIN, NOISE_DB_MAX = -50.0, -10.0  # noise level relative to the speech at noise = 0+ and 1
NOISE_SEED = 20240


class Effects(BaseModel):
    """Effect settings; every field's default is neutral."""

    reverb: float = Field(0.0, ge=0, le=1, description="Room reverb amount.")
    distance: float = Field(0.0, ge=0, le=1, description="0 = close, 1 = far away: duller, quieter, more reverberant.")
    noise: float = Field(0.0, ge=0, le=1, description="Background noise level, from faint to as loud as -10 dB under the voice.")
    noise_color: Literal["pink", "brown"] = "pink"
    pan: float = Field(0.0, ge=-1, le=1, description="-1 = left, 1 = right. The output is stereo when this is not 0.")

    @property
    def is_neutral(self) -> bool:
        return self.reverb == 0 and self.distance == 0 and self.noise == 0 and self.pan == 0


def _impulse_response(rate: int):
    """A decaying-noise room: exponential envelope (-60 dB at REVERB_SECONDS), darker as it decays, unit energy."""
    import numpy as np
    from scipy.signal import lfilter

    n = int(rate * REVERB_SECONDS)
    t = np.arange(n) / rate
    noise = np.random.RandomState(NOISE_SEED).standard_normal(n)
    ir = noise * np.exp(-6.9078 * t / REVERB_SECONDS)
    ir = lfilter([0.35], [1.0, -0.65], ir)  # one-pole low-pass: highs die out in real rooms
    ir[0] = 0.0  # the direct sound is the dry signal
    return ir / math.sqrt(float(np.sum(ir**2)))


def _lowpass(x, rate: int, cutoff: float):
    from scipy.signal import butter, sosfilt

    cutoff = min(cutoff, rate * 0.45)
    return sosfilt(butter(2, cutoff, btype="low", fs=rate, output="sos"), x)


def _colored_noise(n: int, color: str, seed: int):
    """Unit-RMS pink (1/f power) or brown (1/f^2 power) noise of length n."""
    import numpy as np

    white = np.random.RandomState(seed).standard_normal(n)
    spectrum = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n)
    freqs[0] = freqs[1] if n > 1 else 1.0
    spectrum *= freqs ** (-0.5 if color == "pink" else -1.0)
    spectrum[0] = 0.0
    noise = np.fft.irfft(spectrum, n)
    rms = math.sqrt(float(np.mean(noise**2))) or 1.0
    return noise / rms


def _rms(x) -> float:
    import numpy as np

    return math.sqrt(float(np.mean(np.square(x)))) if len(x) else 0.0


def _room(x, rate: int, fx: Effects):
    """Distance filtering/level and reverb on one channel; may be longer than `x` by the reverb tail."""
    import numpy as np
    from scipy.signal import fftconvolve

    wet_amount = min(1.0, fx.reverb + DISTANCE_EXTRA_WET * fx.distance) * REVERB_WET
    if fx.distance:
        x = _lowpass(x, rate, DISTANCE_CUTOFF_NEAR * (DISTANCE_CUTOFF_FAR / DISTANCE_CUTOFF_NEAR) ** fx.distance)
    dry_gain = 10 ** (DISTANCE_DRY_DB * fx.distance / 20)
    if wet_amount == 0:
        return x * dry_gain
    ir = _impulse_response(rate)
    wet = fftconvolve(x, ir)
    wet_gain = 10 ** (DISTANCE_WET_DB * fx.distance / 20)
    out = np.zeros(len(wet))
    out[: len(x)] += x * dry_gain * (1 - wet_amount)
    return out + wet * wet_gain * wet_amount


def process(samples, rate: int, fx: Effects):
    """Apply `fx` to float audio in [-1, 1]: shape (n,) mono or (n, channels).

    Returns the input object itself for neutral settings. Otherwise a float64 array: mono stays
    mono unless pan is not 0, in which case it is (n, 2); the reverb tail makes the result longer.
    """
    import numpy as np

    if fx.is_neutral:
        return samples
    x = np.asarray(samples, dtype=np.float64)
    if fx.pan != 0 and x.ndim == 2:
        x = x.mean(axis=1)
    if fx.reverb or fx.distance:
        x = _room(x, rate, fx) if x.ndim == 1 else np.stack([_room(x[:, c], rate, fx) for c in range(x.shape[1])], axis=1)
    if fx.pan != 0:  # constant power: left^2 + right^2 stays 1 wherever the voice sits
        angle = (fx.pan + 1) * math.pi / 4
        x = np.stack([x * math.cos(angle), x * math.sin(angle)], axis=1)
    if fx.noise:
        level = 10 ** ((NOISE_DB_MIN + (NOISE_DB_MAX - NOISE_DB_MIN) * fx.noise) / 20) * (_rms(x) or 1.0)
        if x.ndim == 1:
            x = x + _colored_noise(len(x), fx.noise_color, NOISE_SEED) * level
        else:  # independent noise per channel sounds like a room around the voice
            x = x + np.stack([_colored_noise(len(x), fx.noise_color, NOISE_SEED + c) for c in range(x.shape[1])], axis=1) * level
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    return x * (CEILING / peak) if peak > CEILING else x


def decode(data: bytes):
    """(samples, rate) from any audio libsndfile reads; ValueError if it is not audio."""
    import soundfile as sf

    try:
        audio, rate = sf.read(io.BytesIO(data), dtype="float64")
    except (RuntimeError, TypeError, ValueError) as exc:  # libsndfile errors are RuntimeErrors
        raise ValueError("undecodable audio") from exc
    if len(audio) == 0:
        raise ValueError("empty audio")
    return audio, rate


def encode_wav(samples, rate: int) -> bytes:
    import soundfile as sf

    buf = io.BytesIO()
    sf.write(buf, samples, rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def apply_to_wav(wav: bytes, fx: Effects) -> bytes:
    """`wav` with `fx` applied, as 16-bit WAV; the same bytes for neutral settings."""
    if fx.is_neutral:
        return wav
    audio, rate = decode(wav)
    return encode_wav(process(audio, rate, fx), rate)
