"""Live audio over a WebSocket: the shared path behind the live features.

The browser streams microphone audio; this module cuts it into turns (one stretch of speech up
to a pause) and hands each turn to the feature's `process` function, one turn at a time.

Client -> server:
  {"type": "start", "config": {...}}  first message: TurnSettings fields plus the feature's options
  binary messages                     16 kHz mono PCM16 little-endian, at most MAX_FRAME_BYTES each
  {"type": "end"}                     finish: the last turn counts and every queued turn is answered
Server -> client:
  {"type": "ready"}                   set up; audio may follow
  {"type": "speaking"}                the current turn has enough voiced audio to count
  {"type": "turn_end", "index": n}    the speaker paused (or hit max_turn_s); n is null if skipped
  {"type": "turn", "index": n, ...}   turn n's result; results always arrive in turn order
  {"type": "warning", "message": m}   e.g. a turn skipped because the model is still busy
  {"type": "error", "message": m}     with "index": that turn failed; without: the session is over
  {"type": "done"}                    after "end", once every turn is answered; then the socket closes

Closing the socket without "end" drops the turns still waiting.
"""

import asyncio
import io
import json
import logging
import math
import os
import sys
import tempfile
import wave
from array import array
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, fields
from pathlib import Path

from fastapi import WebSocket

from voxwell.origins import websocket_origin_allowed
from voxwell.paths import data_dir

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
WINDOW_MS = 20  # voice activity is decided per 20 ms window
WINDOW_BYTES = SAMPLE_RATE * WINDOW_MS // 1000 * 2
MAX_FRAME_BYTES = 64 * 1024  # 2 s of audio in one message
MAX_CONTROL_BYTES = 8 * 1024
# Turns allowed to wait behind the one being processed. A model that falls further behind skips
# new turns with a warning instead of letting them pile up.
QUEUE_SIZE = 2

# A finished turn's result fields, from its PCM and index. Runs in a worker thread.
Process = Callable[[bytes, int], dict]


@dataclass(frozen=True)
class TurnSettings:
    silence_ms: int = 800  # trailing silence that ends a turn
    min_voiced_ms: int = 300  # voiced audio a turn needs, so coughs and clicks are not turns
    max_turn_s: float = 20.0  # a longer turn is cut here; the speech after it is the next turn
    pre_roll_ms: int = 300  # audio kept from just before the speech started
    threshold: float = 0.015  # RMS level (full scale 1.0) at which a window counts as speech


_LIMITS = {
    "silence_ms": (200, 3000),
    "min_voiced_ms": (40, 3000),
    "max_turn_s": (2, 30),
    "pre_roll_ms": (0, 1000),
    "threshold": (0.001, 0.5),
}


def settings_from(config: dict) -> TurnSettings:
    """The TurnSettings fields present in a start message's config; ValueError names a bad one."""
    values = {}
    for f in fields(TurnSettings):
        if f.name in config:
            value = config[f.name]
            low, high = _LIMITS[f.name]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
                raise ValueError(f"{f.name} must be a number from {low} to {high}.")
            values[f.name] = value
    return TurnSettings(**values)


def _rms(window: bytes) -> float:
    samples = array("h", window)
    if sys.byteorder == "big":
        samples.byteswap()
    return math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768


class TurnDetector:
    """Energy-based voice activity detection that cuts a PCM16 stream into turns."""

    def __init__(self, settings: TurnSettings = TurnSettings()):
        self.threshold = settings.threshold
        self._silence = max(1, settings.silence_ms // WINDOW_MS)
        self._min_voiced = max(1, math.ceil(settings.min_voiced_ms / WINDOW_MS))
        self._max = int(settings.max_turn_s * 1000) // WINDOW_MS
        self._pre: deque[bytes] = deque(maxlen=settings.pre_roll_ms // WINDOW_MS)
        self._rest = b""
        self._turn: list[bytes] | None = None
        self._voiced = 0  # voiced windows in the current turn (not its length, which includes pauses)
        self._quiet = 0  # silent windows since the last voiced one
        self._announced = False

    def feed(self, pcm: bytes) -> list[tuple[str, bytes]]:
        """Add audio. Returns what happened, in order: ("speaking", b"") and ("turn", pcm)."""
        data = self._rest + pcm
        cut = len(data) - len(data) % WINDOW_BYTES
        self._rest = data[cut:]
        events: list[tuple[str, bytes]] = []
        for i in range(0, cut, WINDOW_BYTES):
            self._window(data[i : i + WINDOW_BYTES], events)
        return events

    def flush(self) -> list[tuple[str, bytes]]:
        """End of the stream: the turn in progress counts if it has enough voiced audio."""
        events: list[tuple[str, bytes]] = []
        if self._turn is not None:
            self._turn.append(self._rest)
            self._finish(events)
        self._rest = b""
        return events

    def _window(self, window: bytes, events: list) -> None:
        voiced = _rms(window) >= self.threshold
        if self._turn is None:
            if not voiced:
                self._pre.append(window)
                return
            self._turn = list(self._pre)
            self._pre.clear()
        self._turn.append(window)
        if voiced:
            self._voiced += 1
            self._quiet = 0
        else:
            self._quiet += 1
        if not self._announced and self._voiced >= self._min_voiced:
            self._announced = True
            events.append(("speaking", b""))
        if self._quiet >= self._silence:
            self._finish(events)
        elif len(self._turn) >= self._max:
            self._finish(events)
            self._turn = []  # still speaking: the next turn starts right here

    def _finish(self, events: list) -> None:
        if self._voiced >= self._min_voiced:
            events.append(("turn", b"".join(self._turn)))
        self._turn = None
        self._voiced = self._quiet = 0
        self._announced = False


TURN_FAILED = "This turn could not be processed; see the Voxwell log."


def turn_error_message(exc: Exception) -> str:
    """What the client sees for a failed turn. Voxwell's own errors (AudioError, TranslationError,
    AgentError, ...) carry a message written for the user; anything from Python or a library may
    hold paths or internals, so it is logged and replaced by a fixed message."""
    if type(exc).__module__.startswith("voxwell.") and str(exc):
        return str(exc)
    log.error("A live turn could not be processed", exc_info=exc)
    return TURN_FAILED


class TurnWorker:
    """Processes turns one at a time, so results come out in turn order, with a bounded backlog."""

    def __init__(self, process: Process, send: Callable[[dict], Awaitable[bool]]):
        self._process = process
        self._send = send
        self._queue: asyncio.Queue = asyncio.Queue()  # bounded by submit()
        self._next = 0
        self._task = asyncio.create_task(self._run())

    def submit(self, pcm: bytes) -> int | None:
        """Queue a turn; its index, or None when QUEUE_SIZE turns already wait (it is dropped)."""
        if self._queue.qsize() >= QUEUE_SIZE:
            return None
        index = self._next
        self._next += 1
        self._queue.put_nowait((index, pcm))
        return index

    async def finish(self) -> None:
        """Answer every queued turn, then stop."""
        self._queue.put_nowait(None)
        await self._task

    def cancel(self) -> None:
        """Stop now; queued turns are dropped (a turn already in a model call is left to finish unseen)."""
        self._task.cancel()

    async def _run(self) -> None:
        while (item := await self._queue.get()) is not None:
            index, pcm = item
            try:
                result = await asyncio.to_thread(self._process, pcm, index)
                message = {**result, "type": "turn", "index": index}
            except Exception as exc:
                message = {"type": "error", "index": index, "message": turn_error_message(exc)}
            if not await self._send(message):
                return  # the client is gone


def pcm_to_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def transcribe_turn(pcm: bytes, language: str | None):
    """Transcribe one turn with the dictation engine, which reads files: the turn goes through a temporary WAV."""
    from voxwell.features.dictation import engine  # lazy: the features package imports this module

    fd, name = tempfile.mkstemp(suffix=".wav", dir=data_dir("live"))
    path = Path(name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(pcm_to_wav(pcm))
        return engine.transcribe(path, language)
    finally:
        path.unlink(missing_ok=True)


async def _read(ws: WebSocket) -> bytes | dict | None:
    """The next message: audio bytes, a control object, or None once the client disconnected."""
    msg = await ws.receive()
    if msg["type"] == "websocket.disconnect":
        return None
    if msg.get("bytes") is not None:
        data = msg["bytes"]
        if len(data) > MAX_FRAME_BYTES or len(data) % 2:
            raise ValueError(f"Audio messages must be whole 16-bit samples, at most {MAX_FRAME_BYTES} bytes.")
        return data
    text = msg.get("text") or ""
    if len(text) > MAX_CONTROL_BYTES:
        raise ValueError("Control message too long.")
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("type"), str):
        raise ValueError('Control messages must be JSON objects with a "type".')
    return data


async def _close(ws: WebSocket) -> None:
    try:
        await ws.close()
    except Exception:  # already closed by the client
        pass


async def run_session(ws: WebSocket, open_session: Callable[[dict], Process]) -> None:
    """Serve one live session on `ws`.

    `open_session(config)` gets the start message's config, checks the feature's own options
    (ValueError with a message for the user) and returns the `process` function for each turn.
    """
    if not websocket_origin_allowed(ws.headers.get("origin")):
        await ws.close(code=1008)  # before accept(): the handshake is refused with HTTP 403
        return
    await ws.accept()
    lock = asyncio.Lock()
    connected = True

    async def send(message: dict) -> bool:
        nonlocal connected
        if connected:
            try:
                async with lock:
                    await ws.send_text(json.dumps(message))
            except Exception:  # the client went away mid-send
                connected = False
        return connected

    async def fail(message: str) -> None:
        await send({"type": "error", "message": message})
        await _close(ws)

    try:
        first = await _read(ws)
        if first is None:
            return
        if not isinstance(first, dict) or first["type"] != "start":
            raise ValueError('The first message must be {"type": "start"}.')
        config = first.get("config", {})
        if not isinstance(config, dict):
            raise ValueError("config must be an object.")
        detector = TurnDetector(settings_from(config))
        process = open_session(config)
    except ValueError as exc:
        await fail(str(exc))
        return

    worker = TurnWorker(process, send)

    async def handle(events: list[tuple[str, bytes]]) -> None:
        for kind, pcm in events:
            if kind == "speaking":
                await send({"type": "speaking"})
                continue
            index = worker.submit(pcm)
            await send({"type": "turn_end", "index": index})
            if index is None:
                await send({"type": "warning", "message": "Still working on earlier speech, so a turn was skipped."})

    try:
        await send({"type": "ready"})
        while True:
            try:
                item = await _read(ws)
            except ValueError as exc:
                await fail(str(exc))
                return
            if item is None:
                return  # disconnected without "end": the waiting turns are dropped below
            if isinstance(item, bytes):
                await handle(detector.feed(item))
            elif item["type"] == "end":
                await handle(detector.flush())
                await worker.finish()
                await send({"type": "done"})
                await _close(ws)
                return
            else:
                await fail(f"Unknown message type '{item['type']}'.")
                return
    finally:
        worker.cancel()
