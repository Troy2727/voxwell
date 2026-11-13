"""Voice agents: saved agents you talk to (live or push-to-talk) or chat with in text."""

import importlib.util
import logging
import threading
import time
from dataclasses import asdict, dataclass, field

from fastapi import APIRouter, HTTPException, WebSocket
from pydantic import BaseModel, Field

from voxwell import live_audio
from voxwell.features.agents import conversation, language, mood, store, tools
from voxwell.features.voice_cloning.engine import LANGUAGES

log = logging.getLogger(__name__)

router = APIRouter(tags=["agents"])


@router.get("/status")
def status():
    return {
        "ready": importlib.util.find_spec("transformers") is not None,
        "tools": [{"name": t.name, "description": t.description} for t in tools.TOOLS.values()],
        "languages": sorted(LANGUAGES),
    }


class AgentSettings(BaseModel):
    name: str
    system_prompt: str = ""
    voice: str = ""
    language: str = "en"
    tools: list[str] = Field(default_factory=list)
    follow_languages: list[str] = Field(default_factory=list)
    mood_match: bool = False


def _get(agent_id: str) -> store.Agent:
    try:
        return store.get(agent_id)
    except KeyError:
        raise HTTPException(404, "Unknown agent.")


@router.get("/agents")
def list_agents():
    return [asdict(a) for a in store.list_agents()]


@router.post("/agents")
def create_agent(settings: AgentSettings):
    try:
        return asdict(store.create(**settings.model_dump()))
    except store.AgentError as exc:
        raise HTTPException(422, str(exc))


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str):
    return asdict(_get(agent_id))


@router.put("/agents/{agent_id}")
def update_agent(agent_id: str, settings: AgentSettings):
    _get(agent_id)
    try:
        return asdict(store.save(store.Agent(id=agent_id, **settings.model_dump())))
    except store.AgentError as exc:
        raise HTTPException(422, str(exc))


@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: str):
    _get(agent_id)
    store.delete(agent_id)
    return {"deleted": agent_id}


class ChatRequest(BaseModel):
    message: str
    history: list = Field(default_factory=list)  # earlier messages, kept by the client; the last few are used
    speak: bool = True
    language: str | None = None  # one of the agent's allowed languages; its own language by default


@router.post("/agents/{agent_id}/chat")
def chat(agent_id: str, req: ChatRequest):
    """One text turn: the reply, the tool calls it made and (with speak) the spoken reply as base64 WAV."""
    agent = _get(agent_id)
    message = req.message.strip()
    if not message:
        raise HTTPException(422, "The message is empty.")
    allowed = language.allowed(agent)
    if req.language is not None and req.language not in allowed:
        raise HTTPException(422, f"This agent answers in: {', '.join(allowed)}.")
    try:
        return conversation.reply_and_speak(agent, req.history, message, req.speak, req.language)
    except store.AgentError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        log.exception("Voice agent %s failed", agent_id)
        raise HTTPException(500, "The agent failed; see the Voxwell log.") from exc


@router.websocket("/agents/{agent_id}/live")
async def live(ws: WebSocket, agent_id: str):
    """Talk to an agent (see voxwell.live_audio). Config: history, the earlier messages kept by the
    client, and optionally language, the one the last turn used (push-to-talk opens a session per press).

    Each turn's result has the transcript, the reply, its tool calls, the spoken reply and the language
    it answered in. The session adds every exchange to its history, so later turns remember earlier ones.
    An agent with follow_languages detects the language of each turn and follows the user (see language).

    With stream_reply true in the config (Flow replies), a turn's reply is sent sentence by sentence
    while it is written: reply_start, then reply_text and reply_audio per sentence, then the turn
    without "audio" (see conversation.run_turn).

    Cut-in: {"type": "cut", "index": n, "heard_seq": s, "heard_ms": ms} says the user spoke over turn
    n after hearing its sentences up to seq s (null: none). A running turn stops and ends with a turn
    marked "cut"; a finished one gets {"type": "cut_ack", "index": n, "reply": heard}. Either way the
    session history keeps only the heard sentences.
    """

    def open_session(config: dict):
        try:
            agent = store.get(agent_id)
        except KeyError:
            raise ValueError("Unknown agent.")
        history = conversation.clean_history(config.get("history", []))
        allowed = language.allowed(agent)
        current = config.get("language") if config.get("language") in allowed else agent.language
        stream = config.get("stream_reply", False)
        if not isinstance(stream, bool):
            raise ValueError("stream_reply must be true or false.")
        if agent.mood_match:  # streamed or not, its first tempo change shouldn't wait for the library
            mood.warm_up()
        guard = threading.Lock()  # history and turns: held only briefly, never during model work
        turns: dict[int, _Turn] = {}

        def stream_turn(index: int, text: str, emit, started: float) -> dict:
            turn = _Turn()
            with guard:
                turns[index] = turn
                for old in [i for i in turns if i < index - KEEP_TURNS]:
                    del turns[old]
                earlier = list(history)
            chosen = mood.choose_mood(text) if agent.mood_match else None  # once, before the first sentence
            delivery = mood.delivery_for(chosen) if chosen else None
            result = conversation.run_turn(agent, earlier, text, _TurnEmit(emit, turn.cut), current, started, delivery)
            if chosen and not turn.cut.is_set():  # a reply the user cut off shows no mood
                result["mood"] = chosen
            sentences = result.pop("sentences")
            with guard:
                turn.sentences = sentences
                if turn.cut.is_set():
                    result.update(reply=_heard(sentences, turn.heard_seq), cut=True)
                history.append({"role": "user", "content": text})
                if result["reply"]:
                    turn.entry = {"role": "assistant", "content": result["reply"]}
                    history.append(turn.entry)
                del history[: -conversation.MAX_HISTORY]
            return result

        def control(message: dict) -> dict | None:
            if message["type"] != "cut":
                raise ValueError(f"Unknown message type '{message['type']}'.")
            index, heard_seq, heard_ms = _cut_fields(message)
            with guard:
                turn = turns.get(index)
                if turn is None or turn.cut.is_set():
                    return None  # not a streamed turn of this session, or already cut
                log.info("Cut-in on turn %s after %s ms (sentence %s)", index, heard_ms, heard_seq)
                turn.heard_seq = heard_seq
                turn.cut.set()
                if turn.sentences is None:
                    return None  # still running: it stops and reports the cut in its own turn message
                heard = _heard(turn.sentences, heard_seq)
                at = next((i for i, entry in enumerate(history) if entry is turn.entry), None)
                if at is not None:  # still in the history (not trimmed away)
                    if heard:
                        history[at]["content"] = heard
                    else:
                        del history[at]
                return {"type": "cut_ack", "index": index, "reply": heard}

        def process(pcm: bytes, index: int, emit) -> dict:
            nonlocal current
            started = time.monotonic()
            if len(allowed) == 1:
                heard = live_audio.transcribe_turn(pcm, agent.language)
            else:
                heard = live_audio.transcribe_turn(pcm, None)
                seconds = len(pcm) / 2 / live_audio.SAMPLE_RATE
                chosen = language.choose(allowed, current, heard.language, heard.language_probability, seconds, heard.text)
                if heard.text and chosen != heard.language:  # Whisper's text was a guess in the wrong language
                    retry = live_audio.transcribe_turn(pcm, chosen)
                    heard = retry if retry.text else heard  # an empty retry keeps the first text, not drop the turn
                if heard.text:
                    current = chosen
            if not heard.text:
                return {"transcript": ""}
            if stream:
                stt_ms = round((time.monotonic() - started) * 1000)
                result = stream_turn(index, heard.text, emit, started)
                result["timing"] = {"stt_ms": stt_ms, **result["timing"]}
                return {"transcript": heard.text, **result}
            result = conversation.reply_and_speak(agent, history, heard.text, language=current)
            history.extend([{"role": "user", "content": heard.text}, {"role": "assistant", "content": result["reply"]}])
            del history[: -conversation.MAX_HISTORY]
            return {"transcript": heard.text, **result}

        return live_audio.Session(process, control)

    await live_audio.run_session(ws, open_session)


KEEP_TURNS = 4  # streamed turns a session remembers for cut-in


@dataclass
class _Turn:
    """A streamed turn, for cut-in: what was sent, and what the user heard of it."""

    cut: threading.Event = field(default_factory=threading.Event)
    heard_seq: int | None = None
    sentences: list[str] | None = None  # set when the turn has ended
    entry: dict | None = None  # its assistant message in the session history


class _TurnEmit:
    """A turn's Emitter that goes quiet, and reads as cancelled, once the user cuts in on the turn."""

    def __init__(self, emit, cut: threading.Event):
        self._emit, self._cut = emit, cut

    def __call__(self, message: dict) -> bool:
        return False if self._cut.is_set() else self._emit(message)

    @property
    def cancelled(self) -> bool:
        return self._cut.is_set() or self._emit.cancelled


def _heard(sentences: list[str], heard_seq: int | None) -> str:
    return "" if heard_seq is None else " ".join(sentences[: heard_seq + 1])


def _whole(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _cut_fields(message: dict) -> tuple[int, int | None, float]:
    """A cut message's index, heard_seq and heard_ms; ValueError when one is missing or wrong."""
    index, heard_seq, heard_ms = message.get("index"), message.get("heard_seq"), message.get("heard_ms")
    if not _whole(index):
        raise ValueError("A cut needs index: the number of the turn.")
    if "heard_seq" not in message or not (heard_seq is None or _whole(heard_seq)):
        raise ValueError("A cut needs heard_seq: a whole number of at least 0, or null.")
    if isinstance(heard_ms, bool) or not isinstance(heard_ms, (int, float)) or heard_ms < 0:
        raise ValueError("A cut needs heard_ms: a number of at least 0.")
    return index, heard_seq, heard_ms
