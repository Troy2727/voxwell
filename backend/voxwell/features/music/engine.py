"""Music generation through the local ACE-Step server (see runtime.py).

Requests go to ACE-Step's documented HTTP API: POST /release_task queues a task (multipart, so
reference and source audio are uploaded rather than passed as paths), POST /query_result reports
its progress, and GET /v1/audio returns the finished file.
"""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path

from voxwell.features.music import runtime

log = logging.getLogger(__name__)

POLL_SECONDS = 1.5
TASK_TIMEOUT_SECONDS = 2 * 60 * 60  # a long song on a slow CPU

# Vocal languages offered in the UI (ACE-Step's own codes; it supports more).
LANGUAGES = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian",
    "pt": "Portuguese", "ru": "Russian", "zh": "Chinese", "ja": "Japanese", "ko": "Korean",
}


class GenerationError(Exception):
    """The engine refused or failed the task; the message says why."""


def _request(base: str, key: str, path: str, *, data: bytes | None = None, content_type: str | None = None, timeout: float = 60):
    headers = {"Authorization": f"Bearer {key}"}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(base + path, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        try:
            body = json.loads(detail)
            detail = body.get("error") or body.get("detail") or detail
        except ValueError:
            pass
        log.error("The music engine refused %s: %s", path, detail[:2000])
        raise GenerationError("The music engine refused the request; see the Voxwell log.") from exc
    except urllib.error.URLError as exc:
        log.error("Lost contact with the music engine: %s", exc.reason)
        raise GenerationError("Lost contact with the music engine; see the Voxwell log.") from exc


def _multipart(fields: dict, files: dict[str, Path]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        if value is None:
            continue
        if isinstance(value, bool):
            value = "true" if value else "false"
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for name, path in files.items():
        head = f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{name}.wav"\r\nContent-Type: audio/wav\r\n\r\n'
        parts.append(head.encode() + path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _data(raw: bytes):
    body = json.loads(raw)
    if body.get("code", 200) != 200 or body.get("error"):
        raise GenerationError(f"The music engine reported an error: {body.get('error')}")
    return body["data"]


def generate(fields: dict, files: dict[str, Path], on_progress: Callable[[float, str], None]) -> tuple[bytes, dict]:
    """Run one ACE-Step task; returns (WAV bytes, {"metas": the detected BPM, key, ...}).

    `fields` are /release_task form fields; `files` maps upload fields (src_audio,
    reference_audio) to local files. `on_progress(fraction, stage)` is called while it runs.
    """
    on_progress(0.0, "Starting the music engine")
    try:
        base, key = runtime.ensure_running()
    except runtime.EngineError as exc:
        raise GenerationError(str(exc)) from exc
    body, content_type = _multipart(
        {**fields, "audio_format": "wav", "batch_size": 1, "thinking": False,
         "use_cot_caption": False, "use_cot_language": False},
        files,
    )
    task_id = _data(_request(base, key, "/release_task", data=body, content_type=content_type))["task_id"]

    deadline = time.monotonic() + TASK_TIMEOUT_SECONDS
    query = json.dumps({"task_id_list": [task_id]}).encode()
    while True:
        (item,) = _data(_request(base, key, "/query_result", data=query, content_type="application/json"))
        status = item.get("status")
        if status == 1:
            break
        if status == 2:
            raise GenerationError(_failure_message(item))
        if time.monotonic() > deadline:
            raise GenerationError("The music engine took too long.")
        on_progress(float(item.get("progress") or 0.0), _stage(item))
        time.sleep(POLL_SECONDS)

    results = item.get("result")
    results = json.loads(results) if isinstance(results, str) else results
    if not results:
        raise GenerationError("The music engine finished without a track.")
    first = results[0]
    audio_path = urllib.parse.parse_qs(urllib.parse.urlsplit(first["file"]).query)["path"][0]
    wav = _request(base, key, "/v1/audio?" + urllib.parse.urlencode({"path": audio_path}), timeout=300)
    return wav, {"metas": first.get("metas") or {}}


def _stage(item: dict) -> str:
    stage = str(item.get("stage") or "").replace("_", " ").strip()
    return stage[:1].upper() + stage[1:] if stage else "Generating"


def _failure_message(item: dict) -> str:
    detail = item.get("error") or item.get("progress_text") or ""
    results = item.get("result")
    if not detail and isinstance(results, str):
        try:
            detail = (json.loads(results) or [{}])[0].get("error", "")
        except (ValueError, AttributeError, IndexError):
            pass
    log.error("The music engine failed a task: %s", detail[:2000] or "(no detail)")
    return "Music generation failed; see the Voxwell log."
