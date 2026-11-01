import asyncio

import pytest
from fastapi.testclient import TestClient

from voxwell import upload_limits
from voxwell.features.dictation import engine as stt
from voxwell.features.dictation import router as dictation
from voxwell.features.integrations import openai_api
from voxwell.main import app
from voxwell.upload_limits import UploadLimit

client = TestClient(app, base_url="http://127.0.0.1")


@pytest.fixture
def tiny(monkeypatch):
    """The dictation and OpenAI transcription uploads limited to 10 bytes, with no slack."""
    monkeypatch.setattr(upload_limits, "SLACK", 0)
    monkeypatch.setattr(dictation, "MAX_UPLOAD", 10)
    monkeypatch.setattr(openai_api, "MAX_TRANSCRIPTION_BYTES", 10)
    monkeypatch.setattr(stt, "transcribe", lambda *a, **k: pytest.fail("the route must not run"))


def _upload_routes():
    """POST routes that take a multipart body (from the OpenAPI schema: this FastAPI keeps
    included routers nested, so app.routes does not list them)."""
    return {path for path, ops in app.openapi()["paths"].items()
            if "multipart/form-data" in ops.get("post", {}).get("requestBody", {}).get("content", {})}


def test_every_upload_route_is_limited_or_listed_as_unlimited():
    routes = _upload_routes()
    assert set(upload_limits.LIMITS) | set(upload_limits.UNLIMITED) == routes
    assert not set(upload_limits.LIMITS) & set(upload_limits.UNLIMITED)


def test_limits_are_read_from_the_routes_own_constants(monkeypatch):
    monkeypatch.setattr(dictation, "MAX_UPLOAD", 123)
    assert upload_limits.limit_for("/api/dictation/transcribe") == 123
    assert upload_limits.limit_for("/api/dubbing/jobs") is None


def test_an_oversized_upload_is_refused_before_the_route_runs(tiny):
    r = client.post("/api/dictation/transcribe", files={"file": ("a.wav", b"x" * 1000)})
    assert r.status_code == 413 and r.json() == {"detail": "The file is too large (0 MB max)."}


def test_the_openai_path_gets_openais_error_shape(tiny):
    r = client.post("/v1/audio/transcriptions", files={"file": ("a.wav", b"x" * 1000)}, data={"model": "whisper-1"})
    assert r.status_code == 413 and r.json()["error"]["param"] == "file"


def test_the_refusal_carries_cors_headers_for_the_website(tiny):
    r = client.post("/api/dictation/transcribe", files={"file": ("a.wav", b"x" * 1000)},
                    headers={"Origin": "https://voxwell.vercel.app"})
    assert r.status_code == 413 and r.headers["access-control-allow-origin"] == "https://voxwell.vercel.app"


def _run(middleware, path, chunks):
    """Drive the middleware with `chunks` of body (no Content-Length); return what the route read,
    what the client was sent, and how many chunks were left unread."""
    queue = [{"type": "http.request", "body": c, "more_body": i < len(chunks) - 1} for i, c in enumerate(chunks)]
    route_read, sent = [], []

    async def receive():
        return queue.pop(0) if queue else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    async def route(scope, receive, send):
        while (message := await receive())["type"] == "http.request":
            route_read.append(message)
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 400, "headers": []})  # e.g. "could not parse"
        await send({"type": "http.response.body", "body": b""})

    asyncio.run(middleware(route)({"type": "http", "path": path, "headers": []}, receive, send))
    return route_read, sent, len(queue)


def test_a_body_without_content_length_is_cut_off_and_the_rest_discarded(monkeypatch):
    monkeypatch.setattr(upload_limits, "SLACK", 0)
    monkeypatch.setattr(dictation, "MAX_UPLOAD", 10)
    route_read, sent, unread = _run(UploadLimit, "/api/dictation/transcribe", [b"x" * 6] * 5)
    # The route got the first chunk, then an empty final one (the cut-off), never the rest.
    assert [len(m["body"]) for m in route_read] == [6, 0] and route_read[-1]["more_body"] is False
    assert [m.get("status") for m in sent if m["type"] == "http.response.start"] == [413]  # the route's 400 dropped
    assert unread == 0  # the remaining body was read and thrown away: the connection can end cleanly


def test_other_routes_are_untouched():
    route_read, sent, _ = _run(UploadLimit, "/api/dubbing/jobs", [b"x" * 100] * 3)
    assert len(route_read) == 3 and sent[0]["status"] == 400
