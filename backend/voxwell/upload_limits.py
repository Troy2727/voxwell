"""Refuse an oversized upload before it is stored.

FastAPI takes in a whole multipart body (spooling it to disk) before a route can look at it, so a
route's own size check ran only after a huge upload had been stored in full. This middleware
checks Content-Length, and counts the body as it streams in, against the route's limit. Past it,
the client gets a 413 at once, the route is told the body ended (its parser then closes what it
spooled), and the rest of the body is read and thrown away without being stored: closing the
connection with the upload still unread would make browsers show "connection reset" instead of
the 413. The routes keep their own checks.
"""

import logging

from fastapi.responses import JSONResponse

from voxwell.features.audio_effects import router as audio_effects
from voxwell.features.audiobook import router as audiobook
from voxwell.features.dictation import router as dictation
from voxwell.features.integrations import openai_api
from voxwell.features.tools import router as tools
from voxwell.features.translation import router as translation
from voxwell.features.voice_cloning import router as voice_cloning

log = logging.getLogger(__name__)

# Upload route -> where the limit it enforces itself lives (read on each request, so it never
# drifts from the route's own constant).
LIMITS = {
    "/v1/audio/transcriptions": (openai_api, "MAX_TRANSCRIPTION_BYTES"),
    "/api/dictation/transcribe": (dictation, "MAX_UPLOAD"),
    "/api/translation/file": (translation, "MAX_UPLOAD"),
    "/api/tools/convert": (tools, "MAX_UPLOAD"),
    "/api/tools/isolate": (tools, "MAX_UPLOAD"),
    "/api/tools/fit": (tools, "MAX_UPLOAD"),
    "/api/music/generate": (tools, "MAX_UPLOAD"),  # its style reference goes through tools._read_audio
    "/api/audio_effects/apply": (audio_effects, "MAX_UPLOAD"),
    "/api/audiobook/books": (audiobook, "MAX_UPLOAD"),
    "/api/voice_cloning/voices": (voice_cloning, "MAX_UPLOAD"),
}
# Upload routes that take video or long recordings and are deliberately not limited.
UNLIMITED = {
    "/api/dubbing/jobs": "videos",
    "/api/batch/jobs": "videos",
    "/api/transcription/jobs": "long recordings and videos",
    "/api/transcription/align": "long recordings",
    "/api/tools/probe": "reads only the container's header; any media file",
}
# Room for the multipart framing and the form's other fields around the file itself.
SLACK = 1024 * 1024


def limit_for(path: str) -> int | None:
    if path not in LIMITS:
        return None
    module, name = LIMITS[path]
    return getattr(module, name)


class UploadLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        file_limit = limit_for(scope.get("path", "")) if scope["type"] == "http" else None
        if file_limit is None:
            await self.app(scope, receive, send)
            return
        limit = file_limit + SLACK
        declared = dict(scope.get("headers") or []).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > limit:
            await _too_large(scope, receive, send, file_limit)
            await _discard_rest(receive)
            return

        received, refused, body_done = 0, False, False

        async def counted_receive():
            nonlocal received, refused, body_done
            if refused:
                return {"type": "http.request", "body": b"", "more_body": False}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                body_done = not message.get("more_body", False)
                if received > limit:
                    refused = True
                    await _too_large(scope, receive, send, file_limit)
                    # The body "ends" here for the route: its parser fails on the cut-off form
                    # and closes the files it spooled, instead of keeping them for the GC.
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        async def guarded_send(message):
            if not refused:  # once refused, whatever the route answers is dropped
                await send(message)

        try:
            await self.app(scope, counted_receive, guarded_send)
        except Exception:
            if not refused:
                raise
            log.warning("Error after refusing an oversized upload to %s", scope["path"], exc_info=True)
        if refused and not body_done:
            await _discard_rest(receive)


async def _too_large(scope, receive, send, file_limit: int) -> None:
    text = f"The file is too large ({file_limit // (1024 * 1024)} MB max)."
    if scope["path"].startswith("/v1/"):
        response = openai_api._error(413, text, "file")  # the OpenAI-compatible API's error shape
    else:
        response = JSONResponse({"detail": text}, status_code=413)
    await response(scope, receive, send)


async def _discard_rest(receive) -> None:
    """Read the rest of the body and throw it away, so the connection ends cleanly."""
    while True:
        message = await receive()
        if message["type"] != "http.request" or not message.get("more_body", False):
            return
