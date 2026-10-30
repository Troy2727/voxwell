"""Voice agents: saved agents you talk to (live or push-to-talk) or chat with in text."""

import importlib.util
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, WebSocket
from pydantic import BaseModel, Field

from voxwell import live_audio
from voxwell.features.agents import conversation, store, tools
from voxwell.features.voice_cloning.engine import LANGUAGES

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


@router.post("/agents/{agent_id}/chat")
def chat(agent_id: str, req: ChatRequest):
    """One text turn: the reply, the tool calls it made and (with speak) the spoken reply as base64 WAV."""
    agent = _get(agent_id)
    message = req.message.strip()
    if not message:
        raise HTTPException(422, "The message is empty.")
    try:
        return conversation.reply_and_speak(agent, req.history, message, req.speak)
    except store.AgentError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"The agent failed: {exc}")


@router.websocket("/agents/{agent_id}/live")
async def live(ws: WebSocket, agent_id: str):
    """Talk to an agent (see voxwell.live_audio). Config: history, the earlier messages kept by the client.

    Each turn's result has the transcript, the reply, its tool calls and the spoken reply. The
    session adds every exchange to its history, so later turns remember earlier ones.
    """

    def open_session(config: dict):
        try:
            agent = store.get(agent_id)
        except KeyError:
            raise ValueError("Unknown agent.")
        history = conversation.clean_history(config.get("history", []))

        def process(pcm: bytes, index: int) -> dict:
            heard = live_audio.transcribe_turn(pcm, agent.language)
            if not heard.text:
                return {"transcript": ""}
            result = conversation.reply_and_speak(agent, history, heard.text)
            history.extend([{"role": "user", "content": heard.text}, {"role": "assistant", "content": result["reply"]}])
            del history[: -conversation.MAX_HISTORY]
            return {"transcript": heard.text, **result}

        return process

    await live_audio.run_session(ws, open_session)
