"""Saved agents: one JSON file per agent under data_dir("agents")."""

import json
import re
import uuid
from dataclasses import asdict, dataclass, field

from voxwell import voices
from voxwell.features.agents.tools import TOOLS
from voxwell.features.voice_cloning.engine import LANGUAGES
from voxwell.paths import child_path, data_dir

_ID = re.compile(r"^[0-9a-f]{12}$")
MAX_NAME = 80
MAX_PROMPT = 4000


class AgentError(ValueError):
    """Invalid agent settings; the message is for the user."""


@dataclass
class Agent:
    id: str
    name: str
    system_prompt: str
    voice: str = ""  # a saved voice id; "" for the default voice
    language: str = "en"  # what it listens and speaks in
    tools: list[str] = field(default_factory=list)


def _path(agent_id: str):
    if not _ID.match(agent_id):
        raise KeyError(agent_id)
    return child_path(data_dir("agents"), f"{agent_id}.json")


def validate(name: str, system_prompt: str, voice: str, language: str, tools: list[str]) -> None:
    if not name.strip() or len(name) > MAX_NAME:
        raise AgentError(f"Give the agent a name of 1 to {MAX_NAME} characters.")
    if len(system_prompt) > MAX_PROMPT:
        raise AgentError(f"The instructions are too long ({MAX_PROMPT} characters max).")
    if language not in LANGUAGES:
        raise AgentError(f"Unsupported language '{language}'.")
    if voice:
        try:
            voices.voice_audio_path(voice)
        except KeyError:
            raise AgentError(f"Unknown voice '{voice}'.")
    unknown = [t for t in tools if t not in TOOLS]
    if unknown:
        raise AgentError(f"Unknown tool '{unknown[0]}'. Tools: {', '.join(TOOLS)}.")


def save(agent: Agent) -> Agent:
    agent.name = agent.name.strip()
    validate(agent.name, agent.system_prompt, agent.voice, agent.language, agent.tools)
    agent.tools = [t for t in TOOLS if t in agent.tools]  # allowlist order, no duplicates
    _path(agent.id).write_text(json.dumps(asdict(agent)), encoding="utf-8")
    return agent


def create(**settings) -> Agent:
    return save(Agent(id=uuid.uuid4().hex[:12], **settings))


def get(agent_id: str) -> Agent:
    """KeyError if unknown or malformed."""
    path = _path(agent_id)
    if not path.exists():
        raise KeyError(agent_id)
    return Agent(**json.loads(path.read_text(encoding="utf-8")))


def list_agents() -> list[Agent]:
    agents = [Agent(**json.loads(p.read_text(encoding="utf-8"))) for p in data_dir("agents").glob("*.json")]
    return sorted(agents, key=lambda a: a.name.lower())


def delete(agent_id: str) -> None:
    path = _path(agent_id)
    if not path.exists():
        raise KeyError(agent_id)
    path.unlink()
