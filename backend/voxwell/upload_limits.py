"""Refuse an upload as soon as it passes its route's limit, while it is still arriving.

FastAPI receives a whole multipart body (spooling it to disk) before a route can look at it, so a
route's own size check runs only after a huge upload has been taken in full. This middleware
counts the body as it streams in (and checks Content-Length first) and answers 413 at once. The
routes keep their own checks; this only makes the refusal early.
"""

import json

from voxwell.features.audio_effects import router as audio_effects
from voxwell.features.audiobook import router as audiobook
from voxwell.features.dictation import router as dictation
from voxwell.features.integrations import openai_api
from voxwell.features.tools import router as tools
from voxwell.features.translation import router as translation
from voxwell.features.voice_cloning import router as voice_cloning

# Route -> the upload limit that route enforces itself. Video uploads (dubbing, transcription,
# batch) are deliberately not limited.
LIMITS = {
    "/v1/audio/transcriptions": openai_api.MAX_TRANSCRIPTION_BYTES,
    "/api/dictation/transcribe": dictation.MAX_UPLOAD,
    "/api/translation/file": translation.MAX_UPLOAD,
    "/api/tools/convert": tools.MAX_UPLOAD,
    "/api/tools/isolate": tools.MAX_UPLOAD,
    "/api/tools/fit": tools.MAX_UPLOAD,
    "/api/music/generate": tools.MAX_UPLOAD,  # its style reference goes through tools._read_audio
    "/api/audio_effects/apply": audio_effects.MAX_UPLOAD,
    "/api/audiobook/books": audiobook.MAX_UPLOAD,
    "/api/voice_cloning/voices": voice_cloning.MAX_UPLOAD,
}
# Room for the multipart framing and the form's other fields around the file itself.
SLACK = 1024 * 1024


class UploadLimit:
    def __init__(self, app, limits: dict[str, int] | None = None):
        self.app = app
        self.limits = LIMITS if limits is None else limits

    async def __call__(self, scope, receive, send):
        file_limit = self.limits.get(scope.get("path", "")) if scope["type"] == "http" else None
        if file_limit is None:
            await self.app(scope, receive, send)
            return
        limit = file_limit + SLACK
        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length", b"")
        if declared.isdigit() and int(declared) > limit:
            await _too_large(scope, send, file_limit)
            return

        received, refused = 0, False

        async def counted_receive():
            nonlocal received, refused
            if refused:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    refused = True
                    await _too_large(scope, send, file_limit)
                    return {"type": "http.disconnect"}  # the route stops reading
            return message

        async def guarded_send(message):
            if not refused:  # once refused, whatever the route answers is dropped
                await send(message)

        try:
            await self.app(scope, counted_receive, guarded_send)
        except Exception:
            if not refused:
                raise


async def _too_large(scope, send, file_limit: int) -> None:
    text = f"The upload is too large ({file_limit // (1024 * 1024)} MB max)."
    if scope["path"].startswith("/v1/"):  # the OpenAI-compatible API's error shape
        body = {"error": {"message": text, "type": "invalid_request_error", "param": "file"}}
    else:
        body = {"detail": text}
    payload = json.dumps(body).encode()
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode()),
                            (b"connection", b"close")]})
    await send({"type": "http.response.body", "body": payload})
