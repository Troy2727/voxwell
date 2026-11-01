import asyncio

import pytest
from fastapi.testclient import TestClient

from voxwell import upload_limits
from voxwell.features.dictation import engine as stt
from voxwell.main import app
from voxwell.upload_limits import UploadLimit

client = TestClient(app, base_url="http://127.0.0.1")


@pytest.fixture
def tiny(monkeypatch):
    """The dictation and OpenAI transcription uploads limited to 10 bytes, with no slack."""
    monkeypatch.setattr(upload_limits, "SLACK", 0)
    monkeypatch.setitem(upload_limits.LIMITS, "/api/dictation/transcribe", 10)
    monkeypatch.setitem(upload_limits.LIMITS, "/v1/audio/transcriptions", 10)
    monkeypatch.setattr(stt, "transcribe", lambda *a, **k: pytest.fail("the route must not run"))


def test_every_limited_path_is_a_real_upload_route():
    # From the OpenAPI schema: this FastAPI keeps included routers nested, not in app.routes.
    posts = {path for path, ops in app.openapi()["paths"].items() if "post" in ops}
    assert set(upload_limits.LIMITS) <= posts


def test_an_oversized_upload_is_refused_before_the_route_runs(tiny):
    r = client.post("/api/dictation/transcribe", files={"file": ("a.wav", b"x" * 1000)})
    assert r.status_code == 413 and r.json() == {"detail": "The upload is too large (0 MB max)."}


def test_the_openai_path_gets_openais_error_shape(tiny):
    r = client.post("/v1/audio/transcriptions", files={"file": ("a.wav", b"x" * 1000)}, data={"model": "whisper-1"})
    assert r.status_code == 413 and r.json()["error"]["param"] == "file"


def test_the_refusal_carries_cors_headers_for_the_website(tiny):
    r = client.post("/api/dictation/transcribe", files={"file": ("a.wav", b"x" * 1000)},
                    headers={"Origin": "https://voxwell.vercel.app"})
    assert r.status_code == 413 and r.headers["access-control-allow-origin"] == "https://voxwell.vercel.app"


def test_a_body_without_content_length_is_cut_off_while_it_arrives():
    chunks = [{"type": "http.request", "body": b"x" * 6, "more_body": True} for _ in range(5)]
    read, sent = [], []

    async def receive():
        return chunks.pop(0)

    async def send(message):
        sent.append(message)

    async def route(scope, receive, send):
        while (message := await receive())["type"] == "http.request":
            read.append(message)
        await send({"type": "http.response.start", "status": 400, "headers": []})  # e.g. "could not parse"

    scope = {"type": "http", "path": "/upload", "headers": []}
    asyncio.run(UploadLimit(route, {"/upload": 10 - upload_limits.SLACK})(scope, receive, send))
    assert len(read) == 1  # stopped on the second chunk (12 bytes > 10)
    assert [m.get("status") for m in sent if m["type"] == "http.response.start"] == [413]  # the route's 400 dropped


def test_other_routes_are_untouched():
    async def route(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})

    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b"x" * 100}

    asyncio.run(UploadLimit(route, {})({"type": "http", "path": "/elsewhere", "headers": []}, receive, send))
    assert sent[0]["status"] == 200
