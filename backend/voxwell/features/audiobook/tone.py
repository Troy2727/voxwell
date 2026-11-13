"""Tone memory: a steady narration across a chapter.

The local model AI direction uses reads each paragraph with the end of the one before it, the start
of the one after it and the delivery chosen so far, and picks an energy level and a pace. smooth()
then keeps neighbouring paragraphs close unless the text clearly shifts (a change that the next
paragraph confirms). Everything here but the model call is plain logic.
"""

import statistics
from dataclasses import dataclass

from voxwell.features.tools import direction

PARAGRAPH_CHARS = 600  # of the paragraph itself, from its start
CONTEXT_CHARS = 300  # of each neighbour
MAX_STEP = 0.15  # most the energy moves from one paragraph to the next...
SHIFT_MIN = 0.3  # ...unless it changes at least this much
CONFIRM_BAND = 0.1  # and the next paragraph agrees to within this


@dataclass(frozen=True)
class Delivery:
    intensity: float  # 0..1, as in AI direction
    pace: str  # one of direction.PACES


NEUTRAL = Delivery(direction.ENERGY["medium"], "normal")


def engine_args(delivery: Delivery) -> dict:
    """The speech engine's settings for a delivery."""
    return {"exaggeration": direction.exaggeration_for(delivery.intensity), "cfg_weight": direction.PACE_CFG[delivery.pace]}


def context_tail(text: str, limit: int = CONTEXT_CHARS) -> str:
    """The end of `text`, at most `limit` characters, starting on a whole word."""
    if len(text) <= limit:
        return text
    cut = text[-limit:]
    return cut.split(" ", 1)[1] if " " in cut else cut


def context_head(text: str, limit: int = CONTEXT_CHARS) -> str:
    """The start of `text`, at most `limit` characters, ending on a whole word."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    return cut.rsplit(" ", 1)[0] if " " in cut else cut


# Where a smoothed intensity stops being described as the level below or above medium: halfway, with a
# tie going to medium, so one damped step either way still reads as medium.
_LOW_BELOW = (direction.ENERGY["low"] + direction.ENERGY["medium"]) / 2 - 1e-6
_HIGH_ABOVE = (direction.ENERGY["medium"] + direction.ENERGY["high"]) / 2 + 1e-6


def describe(delivery: Delivery | None) -> str:
    """A delivery in the words the model answers in."""
    if delivery is None:
        return "none"
    i = delivery.intensity
    energy = "low" if i < _LOW_BELOW else "high" if i > _HIGH_ABOVE else "medium"
    return f'energy "{energy}", pace "{delivery.pace}"'


def build_request(paragraph: str, previous: str, following: str, held: Delivery | None) -> str:
    """The model's input for one paragraph; the book text goes in only as quoted data."""
    # Book text can't close the quotes early: its own triple quotes become single ones (same length).
    paragraph, previous, following = (t.replace('"""', "'''") for t in (paragraph, previous, following))
    parts = [f"Delivery so far: {describe(held)}"]
    if previous:
        parts.append(f'Text just before (context only):\n"""{context_tail(previous)}"""')
    parts.append(f'Paragraph to read:\n"""{paragraph[:PARAGRAPH_CHARS]}"""')
    if following:
        parts.append(f'Text just after (context only):\n"""{context_head(following)}"""')
    return "\n\n".join(parts)


def smooth(raw: list[Delivery]) -> list[Delivery]:
    """The deliveries to use: each one close to the one before unless the next paragraph confirms a shift."""
    out: list[Delivery] = []
    for i, r in enumerate(raw):
        if not out:
            out.append(r)
            continue
        held, following = out[-1], raw[i + 1] if i + 1 < len(raw) else None
        change = r.intensity - held.intensity
        if abs(change) >= SHIFT_MIN and following and abs(following.intensity - r.intensity) <= CONFIRM_BAND:
            intensity = r.intensity
        else:
            intensity = held.intensity + max(-MAX_STEP, min(MAX_STEP, change))
        pace = r.pace if r.pace != held.pace and following and following.pace == r.pace else held.pace
        out.append(Delivery(round(min(max(intensity, 0.0), 1.0), 6), pace))
    return out


def stats(plan: list[Delivery]) -> dict:
    """How much a plan moves: spread of exaggeration, energy jumps above MAX_STEP, pace changes."""
    values = [engine_args(d)["exaggeration"] for d in plan]
    pairs = list(zip(plan, plan[1:]))
    return {
        "exaggeration_stdev": round(statistics.pstdev(values), 4) if values else 0.0,
        "jumps": sum(abs(b.intensity - a.intensity) > MAX_STEP + 1e-9 for a, b in pairs),
        "pace_changes": sum(a.pace != b.pace for a, b in pairs),
    }


def plan_chapter(paragraphs: list[list[str]], ask=None, count: int | None = None) -> tuple[list[Delivery], list[Delivery]]:
    """(smoothed, raw) deliveries for the first `count` paragraphs (all by default).

    The model is asked about one paragraph more than `count` when there is one, because smoothing
    a paragraph looks one ahead; so a preview plans its paragraphs exactly as the full render does.
    """
    ask = ask or direction.narrate
    texts = [" ".join(p) for p in paragraphs]
    count = len(texts) if count is None else count
    raw: list[Delivery] = []
    for i in range(min(count + 1, len(texts))):
        held = smooth(raw)[-1] if raw else None
        request = build_request(texts[i], texts[i - 1] if i else "", texts[i + 1] if i + 1 < len(texts) else "", held)
        try:
            settings = direction.parse_reply(ask(request))
            raw.append(Delivery(settings.intensity, settings.pace))
        except direction.DirectionError:  # an unreadable answer keeps the previous delivery
            raw.append(raw[-1] if raw else NEUTRAL)
    return smooth(raw)[:count], raw[:count]
