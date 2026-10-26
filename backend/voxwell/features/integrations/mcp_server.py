"""Voxwell MCP server: lets AI assistants (Claude Desktop, Claude Code, ...) use Voxwell's voices.

Run by the assistant as `uv run --directory <backend> voxwell-mcp`. It speaks the Model Context
Protocol (JSON-RPC 2.0, one message per line on stdin/stdout) and forwards each tool call to the
running Voxwell app over its local HTTP API, so models are loaded only once, in the app.
Written with the standard library only.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

PROTOCOL_VERSION = "2025-06-18"
API = f"http://127.0.0.1:{os.environ.get('VOXWELL_PORT', '8765')}"

TOOLS = [
    {
        "name": "list_voices",
        "description": "List the voices saved in Voxwell (names can be used with the speak tool).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "speak",
        "description": "Turn text into speech with a Voxwell voice and save it as a WAV file. Returns the file path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "What to say (up to 4096 characters)."},
                "voice": {"type": "string", "description": "A saved voice name or id. Omit for the default voice."},
                "language": {"type": "string", "description": "ISO 639-1 code, e.g. en, es, fr. Default en."},
                "output_path": {"type": "string", "description": "Where to save the WAV. Default: the Voxwell MCP folder."},
            },
            "required": ["text"],
        },
    },
    {
        "name": "transcribe",
        "description": "Transcribe an audio or video file on this computer to text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the audio or video file."},
                "language": {"type": "string", "description": "ISO 639-1 code; omit to detect it."},
            },
            "required": ["file_path"],
        },
    },
]


class ToolError(Exception):
    """Shown to the assistant as a failed tool result."""


def _request(path: str, data: bytes | None = None, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(API + path, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=1800) as res:  # long texts take a while
            return res.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            message = json.loads(body)["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = body or str(exc)
        raise ToolError(message) from exc
    except urllib.error.URLError as exc:
        raise ToolError("Voxwell is not running. Open the Voxwell app, then try again.") from exc


def _default_output() -> Path:
    from voxwell.paths import data_dir

    return data_dir("mcp") / f"speech-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}.wav"


def list_voices(_args: dict) -> str:
    found = json.loads(_request("/api/voices"))
    if not found:
        return "No saved voices yet; speak uses the default voice."
    return "\n".join(f"- {v['name']} (id {v['id']}, {v['source']})" for v in found)


def speak(args: dict) -> str:
    text = str(args.get("text", "")).strip()
    if not text:
        raise ToolError("text is required.")
    body = {"input": text, "voice": args.get("voice") or "default", "language": args.get("language") or "en",
            "response_format": "wav"}
    wav = _request("/v1/audio/speech", json.dumps(body).encode(), {"Content-Type": "application/json"})
    out = Path(args["output_path"]).expanduser() if args.get("output_path") else _default_output()
    if out.suffix.lower() != ".wav":
        out = out.with_suffix(".wav")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(wav)
    return f"Saved the speech to {out}"


def transcribe(args: dict) -> str:
    path = Path(str(args.get("file_path", ""))).expanduser()
    if not path.is_file():
        raise ToolError(f"File not found: {path}")
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio{path.suffix}"\r\n\r\n'.encode(),
             path.read_bytes(), b"\r\n"]
    if args.get("language"):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\n{args["language"]}\r\n'.encode())
    parts.append(f"--{boundary}--\r\n".encode())
    result = _request("/v1/audio/transcriptions", b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return json.loads(result)["text"] or "(no speech found)"


HANDLERS = {"list_voices": list_voices, "speak": speak, "transcribe": transcribe}


def handle(message: dict) -> dict | None:
    """One JSON-RPC message in, the response out (None for notifications)."""
    method, msg_id, params = message.get("method"), message.get("id"), message.get("params") or {}
    if msg_id is None:  # notifications (e.g. notifications/initialized) get no reply
        return None
    if method == "initialize":
        result = {
            "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "voxwell", "version": "0.1.0"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        handler = HANDLERS.get(params.get("name"))
        if handler is None:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32602, "message": f"Unknown tool: {params.get('name')}"}}
        try:
            result = {"content": [{"type": "text", "text": handler(params.get("arguments") or {})}], "isError": False}
        except ToolError as exc:
            result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            reply = handle(message)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
