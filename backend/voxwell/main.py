import os
import sys
import threading
from contextlib import asynccontextmanager
from dataclasses import asdict

import truststore
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from voxwell import voices
from voxwell.features import FEATURES
from voxwell.features.integrations import openai_api
from voxwell.origins import APP_HOSTS, APP_ORIGINS
from voxwell.paths import data_dir

# Model downloads must work behind TLS-inspecting proxies and antivirus, whose certificates
# live in the OS store, not in Python's bundled one. huggingface_hub does not fall back to the
# local model cache on SSL errors, so without this even downloaded models fail to load there.
truststore.inject_into_ssl()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    for feature in FEATURES:
        if feature.background:
            feature.background()
    yield


app = FastAPI(title="Voxwell", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(APP_ORIGINS),
    # Chrome asks before a public page (the hosted web build) may reach 127.0.0.1.
    allow_private_network=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(APP_HOSTS))


@app.get("/api/health")
def health():
    return {"status": "ok", "features": [f.id for f in FEATURES]}


@app.get("/api/voices")
def get_voices():
    return [asdict(v) for v in voices.list_voices()]


for feature in FEATURES:
    app.include_router(feature.router, prefix=f"/api/{feature.id}")
# OpenAI-compatible audio API, at the path OpenAI clients expect (base URL .../v1).
app.include_router(openai_api.router, prefix="/v1")


def _stop_when_stdin_closes(server) -> None:
    """Stop the server once stdin reaches end-of-file.

    The desktop app keeps our stdin open. Its `uv run` wrapper can be killed without killing
    this process (Windows does not kill child processes with their parent), but the OS closes
    the app's end of the pipe however the app ends, crashes included.
    """

    def watch():
        sys.stdin.buffer.read()
        server.should_exit = True

    threading.Thread(target=watch, daemon=True, name="voxwell-parent-watch").start()


def _log_to_file() -> None:
    """Errors the API reports as "see the Voxwell log" are written to <data folder>/logs/voxwell.log
    (and still to the console). Only the server does this, not tests or CLI calls."""
    import logging
    from logging.handlers import RotatingFileHandler

    handler = RotatingFileHandler(data_dir("logs") / "voxwell.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[handler, logging.StreamHandler()],
    )


def run():
    import uvicorn

    from voxwell.live_audio import MAX_FRAME_BYTES

    _log_to_file()
    port = int(os.environ.get("VOXWELL_PORT", "8765"))
    # Live audio messages are small; the WebSocket layer refuses bigger ones before buffering them.
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, ws_max_size=MAX_FRAME_BYTES))
    # Only when started by the app: a terminal's stdin must not stop a server started by hand.
    if os.environ.get("VOXWELL_EXIT_WITH_PARENT") == "1":
        _stop_when_stdin_closes(server)
    server.run()
