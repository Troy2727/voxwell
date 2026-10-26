import os
from contextlib import asynccontextmanager
from dataclasses import asdict

import truststore
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from voxwell import voices
from voxwell.features import FEATURES
from voxwell.features.integrations import openai_api

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
# The renderer runs on the Vite dev server or from file:// (origin "null").
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "null"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


def run():
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("VOXWELL_PORT", "8765")))
