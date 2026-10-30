import asyncio
import math
import threading
import time
from array import array

import pytest

from voxwell import live_audio
from voxwell.live_audio import TurnDetector, TurnSettings, TurnWorker, settings_from
from voxwell.origins import websocket_origin_allowed

MS = live_audio.SAMPLE_RATE // 1000 * 2  # bytes per millisecond of PCM16


def speech(ms: int, amplitude: float = 0.3) -> bytes:
    n = ms * live_audio.SAMPLE_RATE // 1000
    return array("h", (int(amplitude * 32767 * math.sin(2 * math.pi * 220 * i / 16000)) for i in range(n))).tobytes()


def silence(ms: int) -> bytes:
    return bytes(ms * MS)


def turns(events) -> list[bytes]:
    return [pcm for kind, pcm in events if kind == "turn"]


def test_speech_then_silence_is_one_turn_with_pre_roll():
    d = TurnDetector(TurnSettings(silence_ms=800, pre_roll_ms=300))
    events = d.feed(silence(500) + speech(1000) + silence(1200))
    assert [kind for kind, _ in events] == ["speaking", "turn"]
    # 300 ms pre-roll + the speech + the 800 ms of silence that ended it
    assert len(turns(events)[0]) == (300 + 1000 + 800) * MS
    assert d.flush() == []


def test_short_click_is_not_a_turn():
    d = TurnDetector(TurnSettings(min_voiced_ms=300))
    assert d.feed(silence(200) + speech(60) + silence(2000)) == []
    assert d.feed(speech(60)) == [] and d.flush() == []


def test_min_voiced_counts_voiced_time_not_turn_length():
    # Three 100 ms blips with pauses shorter than the silence window: the turn spans 1.3 s but
    # holds only 300 ms of voice.
    blips = speech(100) + silence(500) + speech(100) + silence(500) + speech(100)
    assert TurnDetector(TurnSettings(min_voiced_ms=400, silence_ms=800)).feed(blips + silence(1000)) == []
    assert len(turns(TurnDetector(TurnSettings(min_voiced_ms=300, silence_ms=800)).feed(blips + silence(1000)))) == 1


def test_long_speech_is_split_at_max_turn_length():
    d = TurnDetector(TurnSettings(max_turn_s=2, silence_ms=500, pre_roll_ms=0))
    events = d.feed(speech(5000) + silence(600))
    lengths = [len(t) // MS for t in turns(events)]
    assert lengths == [2000, 2000, 1500]
    assert [kind for kind, _ in events].count("speaking") == 3


def test_flush_ends_the_turn_in_progress():
    d = TurnDetector()
    assert turns(d.feed(speech(700))) == []
    assert len(turns(d.flush())) == 1


def test_frame_boundaries_do_not_change_the_result():
    stream = silence(300) + speech(900) + silence(1000) + speech(500) + silence(1000)
    whole = TurnDetector().feed(stream)
    pieces = TurnDetector()
    events = []
    for i in range(0, len(stream), 334):  # never aligned with the 20 ms windows
        events += pieces.feed(stream[i : i + 334])
    assert events == whole and len(turns(whole)) == 2


@pytest.mark.parametrize("config", [{"silence_ms": 50}, {"silence_ms": "800"}, {"max_turn_s": 600}, {"threshold": True}])
def test_settings_are_checked(config):
    with pytest.raises(ValueError):
        settings_from(config)


def test_settings_ignore_other_options():
    assert settings_from({"silence_ms": 500, "language": "en"}) == TurnSettings(silence_ms=500)


def _run_worker(process, submit_count, *, cancel_after=None):
    sent = []

    async def send(message):
        sent.append(message)
        return True

    async def main():
        worker = TurnWorker(process, send)
        accepted = [worker.submit(bytes([i])) for i in range(submit_count)]
        if cancel_after is None:
            await worker.finish()
        else:
            await asyncio.sleep(cancel_after)
            worker.cancel()
            await asyncio.sleep(0.2)
        return accepted

    return asyncio.run(main()), sent


def test_worker_keeps_turn_order(monkeypatch):
    monkeypatch.setattr(live_audio, "QUEUE_SIZE", 10)

    def process(pcm, index):
        time.sleep(0.03 if index == 0 else 0)  # the first turn is the slowest
        return {"text": f"turn {pcm[0]}"}

    accepted, sent = _run_worker(process, 3)
    assert accepted == [0, 1, 2]
    assert [(m["index"], m["text"]) for m in sent] == [(0, "turn 0"), (1, "turn 1"), (2, "turn 2")]


def test_worker_drops_turns_when_the_queue_is_full():
    accepted, sent = _run_worker(lambda pcm, index: {"text": str(index)}, live_audio.QUEUE_SIZE + 2)
    assert accepted == list(range(live_audio.QUEUE_SIZE)) + [None, None]
    assert [m["index"] for m in sent] == list(range(live_audio.QUEUE_SIZE))


def test_worker_reports_a_failed_turn_and_continues(monkeypatch):
    def process(pcm, index):
        if index == 0:
            raise ValueError("Could not decode the audio.")
        return {"text": "ok"}

    _, sent = _run_worker(process, 2)
    assert sent == [
        {"type": "error", "index": 0, "message": "Could not decode the audio."},
        {"type": "turn", "index": 1, "text": "ok"},
    ]


def test_cancel_drops_queued_turns(monkeypatch):
    monkeypatch.setattr(live_audio, "QUEUE_SIZE", 10)
    calls = []
    release = threading.Event()

    def process(pcm, index):
        calls.append(index)
        release.wait(0.3)
        return {}

    try:
        _, sent = _run_worker(process, 3, cancel_after=0.05)
    finally:
        release.set()
    assert calls == [0] and sent == []


@pytest.mark.parametrize("origin", [None, "http://localhost:5173", "null", "file://", "https://voxwell.vercel.app"])
def test_app_origins_allowed(origin):
    assert websocket_origin_allowed(origin)


@pytest.mark.parametrize("origin", ["https://evil.example", "http://localhost:5174", "http://127.0.0.1:5173", ""])
def test_other_origins_refused(origin):
    assert not websocket_origin_allowed(origin)
