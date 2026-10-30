"""Voxwell MCP server: lets AI assistants (Claude Desktop, Cursor, Claude Code, ...) use Voxwell.

Run by the assistant as `uv run --directory <backend> voxwell-mcp`. It speaks the Model Context
Protocol (JSON-RPC 2.0, one message per line on stdin/stdout). Each tool runs the matching
`voxwell` CLI command (voxwell/cli.py), which forwards it to the running Voxwell app over its
local HTTP API, so models are loaded only once, in the app. Written with the standard library only.
"""

import argparse
import json
import sys

from voxwell import cli

PROTOCOL_VERSION = "2025-06-18"


def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required}


_FILE = {"type": "string", "description": "Path to the file on this computer."}
_VOICE = {"type": "string", "description": "A saved voice name or id (see list_voices)."}
_LANGUAGE = {"type": "string", "description": "ISO 639-1 code, e.g. en, es, fr."}

TOOLS = [
    {
        "name": "list_voices",
        "description": "List the voices saved in Voxwell. Their names work in speak, convert_voice and dub_video.",
        "inputSchema": _schema({}, []),
    },
    {
        "name": "voice_collections",
        "description": "Organize saved voices into collections (folders). Deleting a collection never deletes its voices.",
        "inputSchema": _schema({
            "action": {"type": "string", "enum": ["list", "show", "create", "rename", "delete", "add", "remove"],
                       "description": "list collections; show a collection's voices; create, rename or delete one; add or remove voices."},
            "name": {"type": "string", "description": "Collection name or id (not needed for list)."},
            "new_name": {"type": "string", "description": "The new name, for rename."},
            "voices": {"type": "array", "items": {"type": "string"}, "description": "Saved voice names or ids, for add and remove."},
        }, ["action"]),
    },
    {
        "name": "speak",
        "description": "Turn text into speech with a Voxwell voice and save it as a WAV file. Returns the file path.",
        "inputSchema": _schema({
            "text": {"type": "string", "description": "What to say (up to 4096 characters)."},
            "voice": {**_VOICE, "description": "A saved voice name or id. Omit for the built-in voice."},
            "language": {**_LANGUAGE, "description": "ISO 639-1 code, e.g. en, es, fr. Default en."},
            "output_path": {"type": "string", "description": "Where to save the WAV. Default: the Voxwell MCP folder."},
        }, ["text"]),
    },
    {
        "name": "generate_sound",
        "description": "Generate a sound effect or ambience from a text description (Stable Audio Open; needs a Hugging Face "
        "token and accepted model terms, see the Sound page). Takes a while on CPU. Saves a WAV and returns its path and seed.",
        "inputSchema": _schema({
            "prompt": {"type": "string", "description": "What the sound is, e.g. 'rain on a tin roof, distant thunder'."},
            "duration": {"type": "number", "description": "Seconds, 1 to 30. Default 10."},
            "seed": {"type": "integer", "description": "Reuse a previous seed to repeat a result."},
            "output_path": {"type": "string", "description": "Where to save the WAV. Default: the Voxwell MCP folder."},
        }, ["prompt"]),
    },
    {
        "name": "transcribe",
        "description": "Transcribe an audio or video file on this computer to text.",
        "inputSchema": _schema({"file_path": _FILE, "language": {**_LANGUAGE, "description": "ISO 639-1 code; omit to detect it."}}, ["file_path"]),
    },
    {
        "name": "edit_transcript",
        "description": "Clean up a transcript with Voxwell's local AI model, following a short instruction. Give the "
        "text or a text file, and a preset or your own instruction. Returns the edited text.",
        "inputSchema": _schema({
            "text": {"type": "string", "description": "The transcript text. Alternative to file_path."},
            "file_path": {**_FILE, "description": "Path to a text file with the transcript. Alternative to text."},
            "preset": {"type": "string", "description": "filler (remove filler words), punctuation, formal or concise."},
            "instruction": {"type": "string", "description": "Your own instruction, e.g. 'remove filler words'. Alternative to preset."},
        }, []),
    },
    {
        "name": "isolate_voice",
        "description": "Split a recording (up to 10 minutes) into the voice alone and the background (music, noise, "
        "effects). Saves <name>.voice.wav and <name>.background.wav and returns their paths.",
        "inputSchema": _schema({
            "file_path": _FILE,
            "output_folder": {"type": "string", "description": "Folder for the two WAVs. Default: next to the input."},
        }, ["file_path"]),
    },
    {
        "name": "clone_voice",
        "description": "Save a new voice from a few seconds of clean speech, so speak and the other tools can use it.",
        "inputSchema": _schema({"name": {"type": "string", "description": "Name for the new voice."}, "file_path": _FILE}, ["name", "file_path"]),
    },
    {
        "name": "design_voice",
        "description": "Create a new voice from a description (e.g. 'warm, low female voice, slight British accent') and save it.",
        "inputSchema": _schema({
            "description": {"type": "string", "description": "How the voice should sound."},
            "name": {"type": "string", "description": "Name for the new voice."},
            "sample_text": {"type": "string", "description": "Text the preview says (optional)."},
        }, ["description", "name"]),
    },
    {
        "name": "convert_voice",
        "description": "Re-speak a recording in a saved voice, keeping the words and timing. Returns the WAV path.",
        "inputSchema": _schema({
            "file_path": _FILE,
            "voice": _VOICE,
            "output_path": {"type": "string", "description": "Where to save the WAV. Default: the Voxwell MCP folder."},
        }, ["file_path", "voice"]),
    },
    {
        "name": "apply_effects",
        "description": "Add reverb, distance, background noise or stereo pan to a recording. Saves a WAV (stereo when pan is "
        "not 0; reverb adds a short tail) and returns its path. Leave an effect out to leave it off.",
        "inputSchema": _schema({
            "file_path": _FILE,
            "reverb": {"type": "number", "description": "0 to 1."},
            "distance": {"type": "number", "description": "0 (close) to 1 (far away): duller, quieter, more reverberant."},
            "noise": {"type": "number", "description": "Background noise level, 0 to 1."},
            "noise_color": {"type": "string", "enum": ["pink", "brown"], "description": "Default pink."},
            "pan": {"type": "number", "description": "-1 (left) to 1 (right)."},
            "output_path": {"type": "string", "description": "Where to save the WAV. Default: the Voxwell MCP folder."},
        }, ["file_path"]),
    },
    {
        "name": "manage_pronunciations",
        "description": "List, add or remove how a word is pronounced. Every voice then says the word as respelled "
        "(e.g. Nguyen -> win). Adding a word that already has an entry replaces it.",
        "inputSchema": _schema({
            "action": {"type": "string", "enum": ["list", "add", "remove"]},
            "word": {"type": "string", "description": "The word as written (add, remove)."},
            "respelling": {"type": "string", "description": "How to write it so it is spoken right (add)."},
            "language": {**_LANGUAGE, "description": "ISO 639-1 code. Default en."},
            "case_sensitive": {"type": "boolean", "description": "Match only this capitalization (add). Default false."},
            "whole_word": {"type": "boolean", "description": "Match whole words only (add). Default true."},
        }, ["action"]),
    },
    {
        "name": "dub_video",
        "description": "Dub a video into another language (takes minutes). Saves an MP4 and an SRT and returns their paths.",
        "inputSchema": _schema({
            "file_path": _FILE,
            "target_language": _LANGUAGE,
            "voice": {**_VOICE, "description": "A saved voice name or id. Omit to clone the original speaker."},
            "output_path": {"type": "string", "description": "Where to save the MP4. Default: the Voxwell MCP folder."},
        }, ["file_path", "target_language"]),
    },
]


class ToolError(Exception):
    """Shown to the assistant as a failed tool result."""


def _client() -> cli.Client:
    return cli.Client()


def _default_folder() -> str:
    from voxwell.paths import data_dir

    return str(data_dir("mcp"))


def _run(command, **values) -> str:
    """Run a CLI command; its human-readable result is the tool's text."""
    text, _ = command(_client(), argparse.Namespace(json=True, **values))
    return text


def _required(args: dict, key: str) -> str:
    value = str(args.get(key) or "").strip()
    if not value:
        raise ToolError(f"{key} is required.")
    return value


def list_voices(args: dict) -> str:
    return _run(cli.cmd_voices)


def voice_collections(args: dict) -> str:
    action = _required(args, "action")
    if action == "rename":
        rest = [_required(args, "new_name")]
    elif action in ("add", "remove"):
        rest = [str(v) for v in args.get("voices") or []]
    else:
        rest = []
    return _run(cli.cmd_collection, action=action, name=args.get("name"), rest=rest)


def speak(args: dict) -> str:
    text = _required(args, "text")
    if text == "-":  # the CLI reads "-" from stdin, which is this server's protocol stream
        raise ToolError("text is required.")
    return _run(cli.cmd_speak, text=text, voice=args.get("voice"), language=args.get("language") or "en", speed=1.0,
                output=args.get("output_path") or _default_folder())


def generate_sound(args: dict) -> str:
    return _run(cli.cmd_sound, prompt=_required(args, "prompt"), duration=float(args.get("duration") or 10),
                seed=args.get("seed"), steps=100, output=args.get("output_path") or _default_folder())


def transcribe(args: dict) -> str:
    text = _run(cli.cmd_transcribe, file=_required(args, "file_path"), language=args.get("language"), format="txt", output=None)
    return text or "(no speech found)"


def edit_transcript(args: dict) -> str:
    text, path = args.get("text"), str(args.get("file_path") or "").strip()
    if (text is None) == (not path):
        raise ToolError("Give either text or file_path.")
    if text is not None and not str(text).strip():
        raise ToolError("text is required.")
    return _run(cli.cmd_edit, file=path or "text", text=text, preset=args.get("preset"), instruction=args.get("instruction"), output=None)


def isolate_voice(args: dict) -> str:
    return _run(cli.cmd_isolate, file=_required(args, "file_path"), output=args.get("output_folder"))


def clone_voice(args: dict) -> str:
    return _run(cli.cmd_clone, name=_required(args, "name"), file=_required(args, "file_path"))


def design_voice(args: dict) -> str:
    return _run(cli.cmd_design, description=_required(args, "description"), name=_required(args, "name"),
                sample=args.get("sample_text"), preview=None)


def convert_voice(args: dict) -> str:
    return _run(cli.cmd_convert, file=_required(args, "file_path"), voice=_required(args, "voice"),
                output=args.get("output_path") or _default_folder())


def dub_video(args: dict) -> str:
    return _run(cli.cmd_dub, file=_required(args, "file_path"), to=_required(args, "target_language").lower(),
                voice=args.get("voice") or "original", output=args.get("output_path") or _default_folder())


def apply_effects(args: dict) -> str:
    try:
        levels = {k: float(args.get(k) or 0) for k in ("reverb", "distance", "noise", "pan")}
    except (TypeError, ValueError):
        raise ToolError("reverb, distance, noise and pan must be numbers.")
    return _run(cli.cmd_effects, file=_required(args, "file_path"), noise_color=args.get("noise_color") or "pink",
                output=args.get("output_path") or _default_folder(), **levels)
def manage_pronunciations(args: dict) -> str:
    action = _required(args, "action")
    if action not in ("list", "add", "remove"):
        raise ToolError("action must be list, add or remove.")
    return _run(cli.cmd_pronounce, action=action, word=args.get("word"), respelling=args.get("respelling"),
                language=args.get("language") or "en", case_sensitive=bool(args.get("case_sensitive")),
                partial=args.get("whole_word") is False)


HANDLERS = {
    "list_voices": list_voices, "voice_collections": voice_collections, "speak": speak, "generate_sound": generate_sound, "transcribe": transcribe, "edit_transcript": edit_transcript, "isolate_voice": isolate_voice,
    "clone_voice": clone_voice, "design_voice": design_voice, "convert_voice": convert_voice, "dub_video": dub_video,
    "apply_effects": apply_effects,
    "manage_pronunciations": manage_pronunciations,
}


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
        except (ToolError, cli.CliError) as exc:
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
