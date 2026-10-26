"""Integrations: what other apps need to connect (API address, MCP launch command), and the
opt-in phone-call settings (see phone.py)."""

import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import voxwell
from voxwell.features.audiobook.books import render_text
from voxwell.features.audiobook.chunking import chapter_chunks
from voxwell.features.integrations import phone
from voxwell.features.integrations.openai_api import resolve_voice
from voxwell.features.voice_cloning.engine import LANGUAGES

router = APIRouter(tags=["integrations"])

BACKEND_DIR = Path(voxwell.__file__).resolve().parents[1]  # folder with pyproject.toml
MAX_GREETING = 500
_PUBLIC_URL = re.compile(r"^https://[^\s/?#]+(/[^\s?#]*)?$")


@router.get("/status")
def status():
    return {"ready": True}


@router.get("/info")
def info():
    port = os.environ.get("VOXWELL_PORT", "8765")
    return {
        "api_base": f"http://127.0.0.1:{port}/v1",
        "mcp": {
            "command": "uv",
            "args": ["run", "--directory", str(BACKEND_DIR), "voxwell-mcp"],
            # uv trusts the OS certificate store (TLS-inspecting networks); see app/electron/main.cjs.
            "env": {"UV_SYSTEM_CERTS": "1"},
        },
    }


# --- phone calls (opt-in) ------------------------------------------------------------------


class PhoneSettings(BaseModel):
    enabled: bool
    public_url: str = ""
    auth_token: str | None = None  # None keeps the saved token; "" clears it
    greeting_text: str = ""
    voice_id: str = ""
    language: str = "en"


def _phone_view(cfg: dict) -> dict:
    """Everything the page shows. Never includes the Auth Token itself."""
    public = cfg["public_url"].rstrip("/")
    return {
        "enabled": cfg["enabled"], "public_url": cfg["public_url"], "auth_token_set": bool(cfg["auth_token"]),
        "greeting_text": cfg["greeting_text"], "voice_id": cfg["voice_id"], "language": cfg["language"],
        "greeting_ready": bool(cfg["greeting_token"]) and phone.greeting_path().exists(),
        "gateway": f"http://{phone.GATEWAY_HOST}:{phone.gateway_port()}",
        "gateway_running": phone.gateway_running(),
        "webhook_url": f"{public}/twilio/voice" if public else "",
        "calls": cfg["calls"],
    }


@router.get("/phone")
def get_phone():
    return _phone_view(phone.load())


@router.put("/phone")
def put_phone(req: PhoneSettings):
    cfg = phone.load()
    public_url = req.public_url.strip().rstrip("/")
    if public_url and not _PUBLIC_URL.match(public_url):
        raise HTTPException(422, "The public address must be an https:// address from your tunnel.")
    if req.language not in LANGUAGES:
        raise HTTPException(422, f"Unsupported language '{req.language}'.")
    if req.voice_id:
        try:
            resolve_voice(req.voice_id)
        except KeyError:
            raise HTTPException(422, "Unknown voice.")
    text = req.greeting_text.strip()
    if len(text) > MAX_GREETING:
        raise HTTPException(422, f"The greeting is too long ({MAX_GREETING} characters max).")
    if (text, req.voice_id, req.language) != (cfg["greeting_text"], cfg["voice_id"], cfg["language"]):
        cfg["greeting_token"] = ""  # the recorded greeting no longer matches; render it again
    cfg.update(public_url=public_url, greeting_text=text, voice_id=req.voice_id, language=req.language)
    if req.auth_token is not None:
        cfg["auth_token"] = req.auth_token.strip()
    if req.enabled and not (cfg["public_url"] and cfg["auth_token"]):
        raise HTTPException(422, "Add your tunnel's public address and your Twilio Auth Token first.")
    cfg["enabled"] = req.enabled
    phone.save(cfg)
    phone.sync_gateway()
    return _phone_view(cfg)


@router.post("/phone/greeting")
def render_greeting():
    """Speak the saved greeting text in the saved voice; a new random link is made for it."""
    cfg = phone.load()
    if not cfg["greeting_text"]:
        raise HTTPException(422, "Write a greeting first.")
    try:
        wav = render_text(chapter_chunks(cfg["greeting_text"]), cfg["language"], resolve_voice(cfg["voice_id"]) if cfg["voice_id"] else None)
    except KeyError:
        raise HTTPException(422, "The greeting's voice was deleted. Pick another voice.")
    except Exception as exc:
        raise HTTPException(500, f"Could not record the greeting: {exc}")
    phone.greeting_path().write_bytes(wav)
    cfg["greeting_token"] = phone.new_greeting_token()
    phone.save(cfg)
    return _phone_view(cfg)


@router.get("/phone/greeting.wav")
def greeting_preview():
    """Local preview for the page (the public copy is only on the gateway)."""
    if not phone.greeting_path().exists():
        raise HTTPException(404, "No greeting yet.")
    return FileResponse(phone.greeting_path(), media_type="audio/wav")
