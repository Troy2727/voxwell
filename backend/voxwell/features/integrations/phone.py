"""Phone calls (Twilio), opt-in: callers to your Twilio number hear a greeting in a Voxwell voice.

Off by default. When enabled, a separate small server (the "gateway", 127.0.0.1:8766 unless
VOXWELL_PHONE_PORT is set) serves only two endpoints; the user exposes that port (never the
main app) through a tunnel of their choice and points their Twilio number at it:

  POST /twilio/voice                    Twilio's call webhook. Rejected unless it carries a valid
                                        X-Twilio-Signature (HMAC-SHA1 with the user's Auth Token).
  GET  /twilio/greeting/<token>.wav     The greeting audio. <token> is random and changes every
                                        time the greeting is re-rendered.

The Auth Token is stored in data_dir("phone")/config.json and never sent back to the UI.
Only the time and the last two digits of each caller's number are kept, for the recent-calls list.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path
from xml.sax.saxutils import escape

from voxwell.paths import data_dir

GATEWAY_HOST = "127.0.0.1"
MAX_RECENT_CALLS = 20
MAX_WEBHOOK_BYTES = 64 * 1024
_lock = threading.Lock()
_server = None  # the running gateway (uvicorn.Server), if any


def gateway_port() -> int:
    return int(os.environ.get("VOXWELL_PHONE_PORT", "8766"))


def _config_path() -> Path:
    return data_dir("phone") / "config.json"


def greeting_path() -> Path:
    return data_dir("phone") / "greeting.wav"


def load() -> dict:
    defaults = {
        "enabled": False, "public_url": "", "auth_token": "", "greeting_text": "", "voice_id": "",
        "language": "en", "greeting_token": "", "calls": [],
    }
    if _config_path().exists():
        defaults.update(json.loads(_config_path().read_text(encoding="utf-8")))
    return defaults


def save(cfg: dict) -> None:
    path = _config_path()
    path.write_text(json.dumps(cfg), encoding="utf-8")
    try:
        os.chmod(path, 0o600)  # holds the Auth Token; no effect on Windows ACLs, harmless there
    except OSError:
        pass


def new_greeting_token() -> str:
    return secrets.token_hex(16)


# --- Twilio protocol -----------------------------------------------------------------------


def signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    """Twilio's request signature: base64(HMAC-SHA1(token, url + sorted key/value pairs))."""
    payload = url + "".join(k + params[k] for k in sorted(params))
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def is_valid(auth_token: str, url: str, params: dict[str, str], given: str) -> bool:
    if not auth_token or not given:
        return False
    return hmac.compare_digest(signature(auth_token, url, params), given)


def twiml(cfg: dict) -> str:
    """What Twilio should do with a call: play the greeting, then hang up."""
    if cfg["greeting_token"] and greeting_path().exists():
        audio = f"{cfg['public_url'].rstrip('/')}/twilio/greeting/{cfg['greeting_token']}.wav"
        body = f"<Play>{escape(audio)}</Play><Hangup/>"
    else:
        body = "<Hangup/>"
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>'


def record_call(params: dict[str, str]) -> None:
    caller = params.get("From", "")
    entry = {"time": time.time(), "from": f"…{caller[-2:]}" if len(caller) >= 2 else "unknown"}
    with _lock:
        cfg = load()
        cfg["calls"] = ([entry] + cfg["calls"])[:MAX_RECENT_CALLS]
        save(cfg)


# --- the gateway server --------------------------------------------------------------------


def build_gateway():
    """A separate FastAPI app with only the two public endpoints."""
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import FileResponse, Response

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/twilio/voice")
    async def voice(request: Request):
        body = await request.body()
        if len(body) > MAX_WEBHOOK_BYTES:
            raise HTTPException(413)
        form = await request.form()
        params = {k: str(v) for k, v in form.items()}
        cfg = load()
        url = f"{cfg['public_url'].rstrip('/')}/twilio/voice"
        if not cfg["enabled"] or not is_valid(cfg["auth_token"], url, params, request.headers.get("X-Twilio-Signature", "")):
            raise HTTPException(403)
        record_call(params)
        return Response(twiml(cfg), media_type="text/xml")

    @app.get("/twilio/greeting/{token}.wav")
    def greeting(token: str):
        cfg = load()
        if not (cfg["enabled"] and cfg["greeting_token"] and hmac.compare_digest(token, cfg["greeting_token"])):
            raise HTTPException(404)
        if not greeting_path().exists():
            raise HTTPException(404)
        return FileResponse(greeting_path(), media_type="audio/wav")

    return app


def gateway_running() -> bool:
    return _server is not None and _server.started


def start_gateway() -> None:
    global _server
    import uvicorn

    with _lock:
        if _server is not None:
            return
        config = uvicorn.Config(build_gateway(), host=GATEWAY_HOST, port=gateway_port(), log_level="warning")
        _server = uvicorn.Server(config)
        threading.Thread(target=_server.run, daemon=True, name="voxwell-phone-gateway").start()


def stop_gateway() -> None:
    global _server
    with _lock:
        server, _server = _server, None
    if server is not None:
        server.should_exit = True


def sync_gateway() -> None:
    """Run the gateway exactly when phone calls are enabled. Also the server-start hook."""
    if load()["enabled"]:
        start_gateway()
    else:
        stop_gateway()
