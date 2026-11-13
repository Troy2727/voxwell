"""One agent turn: the local language model, its tool calls and the spoken reply.

The model is the one AI direction loads (Qwen2.5-1.5B-Instruct, Apache-2.0). The enabled tools go
to its chat template as function definitions, the format it was trained on; it calls one with
<tool_call>{"name": ..., "arguments": {...}}</tool_call> and the result comes back as a tool message.
"""

import base64
import io
import json
import logging
import re
import threading
import time
import wave
from collections.abc import Iterator

from voxwell import voices
from voxwell.features.agents import tools
from voxwell.features.agents.sentences import SentenceSplitter
from voxwell.features.agents.store import Agent, AgentError
from voxwell.features.audiobook.books import render_text
from voxwell.features.audiobook.chunking import chapter_chunks
from voxwell.features.voice_cloning import engine as tts
from voxwell.features.voice_cloning.engine import LANGUAGES

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 3  # tool calls per turn; then the model must answer
MAX_HISTORY = 12  # earlier messages (user and assistant) the client may send back
MAX_MESSAGE = 2000
MAX_REPLY_TOKENS = 200
FALLBACK_REPLY = "Sorry, I could not finish that."
SPEAK_WARNING = "Could not speak the reply; see the Voxwell log."


def _chat(messages: list[dict], tools: list[dict] | None = None) -> str:
    """The model's reply to a chat, from the model AI direction loads (one at a time)."""
    import torch

    from voxwell.features.tools import direction

    model, tokenizer = direction._load()
    prompt = tokenizer.apply_chat_template(messages, tools=tools, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    with direction._lock, torch.inference_mode():
        out = model.generate(**inputs, max_new_tokens=MAX_REPLY_TOKENS, do_sample=False, pad_token_id=tokenizer.eos_token_id)
    return tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)


def instructions(agent: Agent, language: str | None = None) -> str:
    # The tools themselves reach the model through its chat template (see respond). Asking here for
    # "short plain sentences" made the model answer sums from memory instead of calling the calculator.
    return (agent.system_prompt.strip() or "You are a helpful assistant.") + (
        f"\n\nYour replies are spoken aloud, so never use markdown, lists or emoji. Answer in {LANGUAGES[language or agent.language]}."
    )


def parse_tool_call(reply: str) -> tuple[dict | None, str | None]:
    """The tool call in a model reply.

    Returns (call, None) for a call, (None, problem) for a call that cannot be read, and
    (None, None) for an ordinary answer. The first JSON object that names a tool counts, with
    any nesting in its arguments and any text around it: the model's own form
    {"name": ..., "arguments": ...} (inside <tool_call> tags) or {"tool": ...}.
    """
    decoder = json.JSONDecoder()
    for brace in re.finditer(r"\{", reply):
        try:
            value, _ = decoder.raw_decode(reply, brace.start())
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        key = "tool" if "tool" in value else "name" if "name" in value and "arguments" in value else None
        if key:
            name, arguments = value[key], value.get("arguments")
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


def respond(agent: Agent, history: list[dict], message: str, language: str | None = None) -> dict:
    """The agent's reply to `message`, using at most MAX_TOOL_ROUNDS tool calls.

    Returns {"reply", "tool_calls"}; each tool call has "tool", "arguments" and "result" or "error".
    """
    messages = _messages(agent, history, message, language)
    offered = tools.schemas(agent.tools)
    calls: list[dict] = []
    for round_ in range(MAX_TOOL_ROUNDS + 1):
        reply = _chat(messages, offered).strip()
        call, problem = parse_tool_call(reply)
        if call is None and problem is None:
            return {"reply": reply or FALLBACK_REPLY, "tool_calls": calls}
        if round_ == MAX_TOOL_ROUNDS:
            break
        _use_tool(agent, call, problem, reply, round_, messages, calls)
    return {"reply": FALLBACK_REPLY, "tool_calls": calls}


def _messages(agent: Agent, history: list[dict], message: str, language: str | None) -> list[dict]:
    return [
        {"role": "system", "content": instructions(agent, language)},
        *clean_history(history),
        {"role": "user", "content": message[:MAX_MESSAGE]},
    ]


def _use_tool(agent: Agent, call: dict | None, problem: str | None, reply: str, round_: int, messages: list, calls: list) -> None:
    """Run a tool call (or report the problem with it), record it in `calls` and feed the result back in `messages`."""
    if problem:
        entry = {"tool": "", "arguments": {}, "error": problem}
    else:
        entry = {"tool": call["tool"], "arguments": call["arguments"]}
        try:
            entry["result"] = tools.run(call["tool"], call["arguments"], agent.tools)
        except tools.ToolError as exc:  # its user_message is written for the user and the model
            entry["error"] = exc.user_message or "The tool failed."
        except Exception:
            log.exception("Agent tool %s failed", call["tool"])
            entry["error"] = "The tool failed."
    calls.append(entry)
    feedback = entry["result"] if "result" in entry else f"Error: {entry['error']}"
    if round_ == MAX_TOOL_ROUNDS - 1:
        feedback += "\nNo more tools now: answer the user."
    messages += [{"role": "assistant", "content": reply}, {"role": "tool", "content": feedback}]


def speak(agent: Agent, text: str, language: str | None = None) -> str:
    """The reply spoken in the agent's voice, as base64 WAV."""
    reference = voices.voice_audio_path(agent.voice) if agent.voice else None
    return base64.b64encode(render_text(chapter_chunks(text), language or agent.language, reference)).decode("ascii")


def reply_and_speak(
    agent: Agent, history: list[dict], message: str, spoken: bool = True, language: str | None = None
) -> dict:
    """respond(), plus "audio" when `spoken`; a failed synthesis keeps the text and adds a warning.

    `language` is the one to answer in (the agent's own by default); the result says which was used.
    """
    language = language or agent.language
    result = {**respond(agent, history, message, language), "language": language}
    if spoken:
        try:
            result["audio"] = speak(agent, result["reply"], language)
        except Exception:
            log.exception("Could not speak an agent reply")
            result["warning"] = SPEAK_WARNING
    return result


# --- Flow replies: a live turn spoken sentence by sentence while the model still writes -----------

TOOL_MARKERS = ("<tool_call", "{", '"tool"')  # text that may start a tool call: the round is held back


def _stream_chat(messages: list[dict], tools: list[dict] | None = None, cancelled=lambda: False) -> Iterator[str]:
    """_chat's reply in pieces, as the model writes it; it stops early once `cancelled()` is true.

    The model runs in its own thread and holds the model lock only while it generates. Stopping the
    iteration early, cancelling or an error stops the generation, and the lock is always released.
    """
    import torch
    from transformers import StoppingCriteria, StoppingCriteriaList, TextIteratorStreamer

    from voxwell.features.tools import direction

    model, tokenizer = direction._load()
    prompt = tokenizer.apply_chat_template(messages, tools=tools, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)
    stop = threading.Event()
    failed: list[Exception] = []

    class Stop(StoppingCriteria):
        def __call__(self, input_ids, scores, **kwargs):
            return stop.is_set() or cancelled()

    def generate():
        try:
            with direction._lock, torch.inference_mode():
                model.generate(
                    **inputs, max_new_tokens=MAX_REPLY_TOKENS, do_sample=False, pad_token_id=tokenizer.eos_token_id,
                    streamer=streamer, stopping_criteria=StoppingCriteriaList([Stop()]),
                )
        except Exception as exc:
            failed.append(exc)
            streamer.end()  # so the reading side is not left waiting

    thread = threading.Thread(target=generate, daemon=True)
    thread.start()
    try:
        yield from streamer
    finally:
        stop.set()
        thread.join()
    if failed:
        raise failed[0]


def _duration_ms(wav: bytes) -> int:
    with wave.open(io.BytesIO(wav)) as w:
        return round(w.getnframes() * 1000 / w.getframerate())


def run_turn(agent: Agent, history: list[dict], message: str, emit, language: str | None = None, started: float | None = None) -> dict:
    """One live turn with Flow replies: each sentence is sent and spoken as soon as the model finishes it.

    `emit` sends a message mid-turn and has `cancelled` (live_audio.Emitter). Tool rounds run first
    and are never spoken: a round's text is held back from the moment it looks like a tool call.
    Sends reply_start, then reply_text and reply_audio per sentence; returns the turn's result.
    """
    language = language or agent.language
    started = time.monotonic() if started is None else started
    reference = voices.voice_audio_path(agent.voice) if agent.voice else None
    messages, offered, calls = _messages(agent, history, message, language), tools.schemas(agent.tools), []
    spoken: list[str] = []
    timing: dict[str, int] = {}
    failed = False

    def ms() -> int:
        return round((time.monotonic() - started) * 1000)

    def say(sentence: str) -> None:
        nonlocal failed
        if emit.cancelled:
            return
        if not spoken:
            timing["first_text_ms"] = ms()
            emit({"type": "reply_start", "transcript": message, "tool_calls": calls})
        seq = len(spoken)
        spoken.append(sentence)
        emit({"type": "reply_text", "seq": seq, "text": sentence})
        if emit.cancelled:
            return
        try:
            wav = tts.synthesize(sentence, language, reference)
            part = {"audio": base64.b64encode(wav).decode("ascii"), "duration_ms": _duration_ms(wav)}
        except Exception:
            log.exception("Could not speak a sentence of an agent reply")
            failed = True
            part = {"audio": None, "error": "Could not speak this sentence."}
        emit({"type": "reply_audio", "seq": seq, **part})
        timing.setdefault("first_audio_ms", ms())

    for round_ in range(MAX_TOOL_ROUNDS + 1):
        splitter, text, fed, held = SentenceSplitter(), "", 0, False
        for piece in _stream_chat(messages, offered, lambda: emit.cancelled):
            text += piece
            held = held or any(marker in text for marker in TOOL_MARKERS)
            if not held:
                fed = len(text)
                for sentence in splitter.feed(piece):
                    say(sentence)
        if emit.cancelled:
            break
        if held:  # it may be a tool call: the held text, or all of it when nothing was spoken yet
            call, problem = parse_tool_call((text[fed:] if spoken else text).strip())
            if call or problem:
                if spoken:  # what came before the call is being said: finish saying it
                    for sentence in splitter.finish():
                        say(sentence)
                if round_ == MAX_TOOL_ROUNDS:
                    break  # out of tool rounds: the fallback below (when nothing was said)
                _use_tool(agent, call, problem, text.strip(), round_, messages, calls)
                continue
        for sentence in [*splitter.feed(text[fed:]), *splitter.finish()]:
            say(sentence)
        break
    if not spoken:
        say(FALLBACK_REPLY)

    timing["total_ms"] = ms()
    log.info("Agent turn timing (ms): %s", timing)
    result = {"reply": " ".join(spoken), "tool_calls": calls, "language": language, "streamed": True, "parts": len(spoken), "timing": timing}
    if failed:
        result["warning"] = SPEAK_WARNING
    return result
