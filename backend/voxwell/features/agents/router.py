"""Voice agents: saved agents you talk to (live or push-to-talk) or chat with in text."""

import importlib.util
import logging
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, WebSocket
from pydantic import BaseModel, Field

from voxwell import live_audio
from voxwell.features.agents import conversation, language, store, tools
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
    """

    def open_session(config: dict):
        try:
            agent = store.get(agent_id)
        except KeyError:
            raise ValueError("Unknown agent.")
        history = conversation.clean_history(config.get("history", []))
        allowed = language.allowed(agent)
        current = config.get("language") if config.get("language") in allowed else agent.language

        def process(pcm: bytes, index: int) -> dict:
            nonlocal current
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
            result = conversation.reply_and_speak(agent, history, heard.text, language=current)
            history.extend([{"role": "user", "content": heard.text}, {"role": "assistant", "content": result["reply"]}])
            del history[: -conversation.MAX_HISTORY]
            return {"transcript": heard.text, **result}

        return process

    await live_audio.run_session(ws, open_session)
