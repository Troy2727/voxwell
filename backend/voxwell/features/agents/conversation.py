"""One agent turn: the local language model, a JSON tool-call protocol and the spoken reply.

The model is the one AI direction loads (Qwen2.5-1.5B-Instruct, Apache-2.0). To use a tool it
replies with only {"tool": "<name>", "arguments": {...}}; the result comes back as the next message.
"""

import base64
import json
import logging
import re

from voxwell import voices
from voxwell.features.agents import tools
from voxwell.features.agents.store import Agent, AgentError
from voxwell.features.audiobook.books import render_text
from voxwell.features.audiobook.chunking import chapter_chunks
from voxwell.features.voice_cloning.engine import LANGUAGES

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 3  # tool calls per turn; then the model must answer
MAX_HISTORY = 12  # earlier messages (user and assistant) the client may send back
MAX_MESSAGE = 2000
MAX_REPLY_TOKENS = 200
FALLBACK_REPLY = "Sorry, I could not finish that."


def _chat(messages: list[dict]) -> str:
    """The model's reply to a chat, from the model AI direction loads (one at a time)."""
    import torch

    from voxwell.features.tools import direction

    model, tokenizer = direction._load()
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    with direction._lock, torch.inference_mode():
        out = model.generate(**inputs, max_new_tokens=MAX_REPLY_TOKENS, do_sample=False, pad_token_id=tokenizer.eos_token_id)
    return tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)


def instructions(agent: Agent) -> str:
    text = (agent.system_prompt.strip() or "You are a helpful assistant.") + (
        f"\n\nYour replies are spoken aloud: answer in {LANGUAGES[agent.language]}, in short plain sentences, "
        "without markdown, lists or emoji."
    )
    enabled = [tools.TOOLS[name] for name in agent.tools if name in tools.TOOLS]
    if enabled:
        listed = "\n".join(f"- {t.name}: {t.description} Arguments: {t.arguments}" for t in enabled)
        text += (
            f"\n\nYou can use these tools:\n{listed}\n"
            'To use one, reply with only a JSON object such as {"tool": "calculator", "arguments": {"expression": "2 + 2"}}. '
            "The result comes back in the next message. Otherwise just answer."
        )
    return text


def parse_tool_call(reply: str) -> tuple[dict | None, str | None]:
    """The tool call in a model reply.

    Returns (call, None) for a call, (None, problem) for a call that cannot be read, and
    (None, None) for an ordinary answer. The first JSON object with a "tool" key counts, with
    any nesting in its arguments and any text around it.
    """
    decoder = json.JSONDecoder()
    for brace in re.finditer(r"\{", reply):
        try:
            value, _ = decoder.raw_decode(reply, brace.start())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "tool" in value:
            name, arguments = value["tool"], value.get("arguments")
            if not isinstance(name, str):
                return None, '"tool" must be the name of a tool.'
            return {"tool": name, "arguments": {} if arguments is None else arguments}, None
    if re.search(r'"tool"\s*:', reply):
        return None, 'That tool call was not valid JSON. Reply with only {"tool": "<name>", "arguments": {...}}.'
    return None, None


def clean_history(history) -> list[dict]:
    """The last MAX_HISTORY user/assistant messages the client sent, each cut to MAX_MESSAGE characters."""
    if not isinstance(history, list):
        raise AgentError("history must be a list of messages.")
    out = []
    for m in history[-MAX_HISTORY:]:
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant") or not isinstance(m.get("content"), str):
            raise AgentError('Each history message needs a "role" (user or assistant) and a "content" string.')
        out.append({"role": m["role"], "content": m["content"][:MAX_MESSAGE]})
    return out


def respond(agent: Agent, history: list[dict], message: str) -> dict:
    """The agent's reply to `message`, using at most MAX_TOOL_ROUNDS tool calls.

    Returns {"reply", "tool_calls"}; each tool call has "tool", "arguments" and "result" or "error".
    """
    messages = [
        {"role": "system", "content": instructions(agent)},
        *clean_history(history),
        {"role": "user", "content": message[:MAX_MESSAGE]},
    ]
    calls: list[dict] = []
    for round_ in range(MAX_TOOL_ROUNDS + 1):
        reply = _chat(messages).strip()
        call, problem = parse_tool_call(reply)
        if call is None and problem is None:
            return {"reply": reply or FALLBACK_REPLY, "tool_calls": calls}
        if round_ == MAX_TOOL_ROUNDS:
            break
        if problem:
            entry = {"tool": "", "arguments": {}, "error": problem}
        else:
            entry = {"tool": call["tool"], "arguments": call["arguments"]}
            try:
                entry["result"] = tools.run(call["tool"], call["arguments"], agent.tools)
            except tools.ToolError as exc:  # its message is written for the user and the model
                entry["error"] = str(exc) or "The tool failed."
            except Exception:
                log.exception("Agent tool %s failed", call["tool"])
                entry["error"] = "The tool failed."
        calls.append(entry)
        feedback = f"Result of {entry['tool']}: {entry['result']}" if "result" in entry else f"Error: {entry['error']}"
        if round_ == MAX_TOOL_ROUNDS - 1:
            feedback += "\nNo more tools now: answer the user."
        messages += [{"role": "assistant", "content": reply}, {"role": "user", "content": f"[tool] {feedback}"}]
    return {"reply": FALLBACK_REPLY, "tool_calls": calls}


def speak(agent: Agent, text: str) -> str:
    """The reply spoken in the agent's voice, as base64 WAV."""
    reference = voices.voice_audio_path(agent.voice) if agent.voice else None
    return base64.b64encode(render_text(chapter_chunks(text), agent.language, reference)).decode("ascii")


def reply_and_speak(agent: Agent, history: list[dict], message: str, spoken: bool = True) -> dict:
    """respond(), plus "audio" when `spoken`; a failed synthesis keeps the text and adds a warning."""
    result = respond(agent, history, message)
    if spoken:
        try:
            result["audio"] = speak(agent, result["reply"])
        except Exception:
            log.exception("Could not speak an agent reply")
            result["warning"] = "Could not speak the reply; see the Voxwell log."
    return result
