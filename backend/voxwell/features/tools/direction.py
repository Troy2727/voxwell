"""AI direction (a Tools tab): a small local language model turns a director's note ("whisper it, sad and
slow") into speech settings. The model (Qwen2.5 Instruct, Apache-2.0) is downloaded on first use."""

import json
import os
import re
import threading
from dataclasses import dataclass

DEFAULT_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"
PACES = ("slow", "normal", "fast")

SYSTEM_PROMPT = """You are a voice director. Turn the user's note about how a line should be spoken into settings.
Reply with one JSON object and nothing else, in this order:
{"summary": "<3 to 6 words describing the delivery>", "energy": "low" | "medium" | "high", "pace": "slow" | "normal" | "fast"}

energy is vocal energy and loudness, not how sad or serious the feeling is:
"low" = quiet, soft, gentle, flat, bored, tired, sleepy or whispered (also quiet sadness);
"medium" = ordinary speaking volume: calm, plain, dry, sarcastic, nervous, serious or dramatic but not loud;
"high" = clearly loud or energetic: shouting, excited, cheering, furious, screaming.
Use "medium" unless the note clearly asks for a quiet or a loud delivery.
pace is speaking speed: "slow", "normal" or "fast".

Examples:
note: softly, like telling a secret -> {"summary": "soft and secretive", "energy": "low", "pace": "slow"}
note: hurry, we are late -> {"summary": "urgent and hurried", "energy": "medium", "pace": "fast"}
note: furious, yelling at someone -> {"summary": "furious yelling", "energy": "high", "pace": "normal"}
note: like a friendly teacher -> {"summary": "warm and friendly", "energy": "medium", "pace": "normal"}"""

# Small models pick a category far more reliably than they calibrate a number (measured on real
# notes: 9/14 with a 0-1 number), so the model chooses a level and the code maps it.
ENERGY = {"low": 0.2, "medium": 0.5, "high": 0.85}

# Words that state the pace or a quiet voice outright. They win over the model's guess, because
# a director's explicit instruction should not be second-guessed.
_FAST = re.compile(r"\b(fast|faster|quick|quickly|rapid|rapidly|hurr(y|ied|iedly)|rush(ed|ing)?|brisk)\b", re.I)
_SLOW = re.compile(r"\b(slow|slowly|slower|unhurried|leisurely|drawn[- ]out)\b", re.I)
_QUIET = re.compile(r"\b(whisper(ed|ing)?|softly|quiet(ly)?|hushed|murmur(ed|ing)?)\b", re.I)
QUIET_MAX_INTENSITY = 0.3

_model = None
_tokenizer = None
_lock = threading.Lock()


@dataclass
class Settings:
    intensity: float  # 0..1
    pace: str  # one of PACES
    summary: str


class DirectionError(ValueError):
    """The model's answer could not be used; the message says why."""


def _device() -> str:
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _load():
    global _model, _tokenizer
    with _lock:
        if _model is None:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            name = os.environ.get("VOXWELL_LLM_MODEL", DEFAULT_MODEL)
            device = _device()
            _tokenizer = AutoTokenizer.from_pretrained(name)
            dtype = torch.float16 if device == "cuda" else torch.float32
            _model = AutoModelForCausalLM.from_pretrained(name, torch_dtype=dtype).to(device).eval()
        return _model, _tokenizer


def complete(system: str, user: str, max_new_tokens: int = 80) -> str:
    """One greedy chat completion from the local model (also used for transcript editing)."""
    import torch

    model, tokenizer = _load()
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    with _lock, torch.inference_mode():
        out = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False, pad_token_id=tokenizer.eos_token_id)
    return tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)


def _ask(note: str) -> str:
    return complete(SYSTEM_PROMPT, note)


def parse_reply(reply: str) -> Settings:
    """Pull the settings out of the model's reply, clamping anything out of range."""
    match = re.search(r"\{.*\}", reply, re.S)
    try:
        data = json.loads(match.group(0)) if match else None
        intensity = ENERGY[str(data["energy"]).lower()]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise DirectionError("The AI's answer could not be read. Try wording the direction differently.")
    pace = str(data.get("pace", "normal")).lower()
    summary = " ".join(str(data.get("summary", "")).split())[:80]
    return Settings(min(max(intensity, 0.0), 1.0), pace if pace in PACES else "normal", summary)


def apply_explicit_words(note: str, settings: Settings) -> Settings:
    """Explicit pace and quiet-voice words in the note override the model."""
    fast, slow = bool(_FAST.search(note)), bool(_SLOW.search(note))
    if fast != slow:  # both or neither: leave it to the model
        settings.pace = "fast" if fast else "slow"
    if _QUIET.search(note):
        settings.intensity = min(settings.intensity, QUIET_MAX_INTENSITY)
    return settings


def interpret(note: str) -> Settings:
    return apply_explicit_words(note, parse_reply(_ask(note)))
