"""Pure helpers for fitting synthesized clips into their time slots and writing SRT."""

MAX_TEMPO = 1.5  # never speed speech up by more than 50%


def tempo_for(clip_seconds: float, slot_seconds: float) -> float:
    """Speed factor (>= 1.0) to squeeze a clip into its slot; clips that fit are not slowed."""
    if slot_seconds <= 0 or clip_seconds <= slot_seconds:
        return 1.0
    return min(clip_seconds / slot_seconds, MAX_TEMPO)


def max_seconds(start: float, end: float, next_start: float | None) -> float:
    """Hard limit for a clip: it may spill into the silence before the next segment."""
    slot = max(end - start, 0.1)
    if next_start is None:
        return slot + 1.0
    return max(slot, next_start - start)


def fit_samples(samples: list[int], rate: int, limit_seconds: float) -> list[int]:
    """Trim to the limit with a short fade-out (padding is implicit: the track is silence)."""
    limit = int(limit_seconds * rate)
    if len(samples) <= limit:
        return samples
    out = samples[:limit]
    fade = min(int(0.02 * rate), len(out))
    for i in range(fade):
        out[len(out) - fade + i] = int(out[len(out) - fade + i] * (1 - (i + 1) / fade))
    return out


def srt_time(seconds: float) -> str:
    ms = int(round(max(seconds, 0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def build_srt(entries: list[tuple[float, float, str]]) -> str:
    blocks = [
        f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{text}\n"
        for i, (a, b, text) in enumerate(entries, 1)
    ]
    return "\n".join(blocks)


def reference_window(segments: list[tuple[float, float]]) -> tuple[float, float]:
    """Pick (start, duration) of a clean reference clip: the longest segment, 3-12 s."""
    if not segments:
        return 0.0, 8.0
    start, end = max(segments, key=lambda s: s[1] - s[0])
    return start, min(max(end - start, 3.0), 12.0)
