"""The `voxwell` command.

With no arguments (or `serve`) it starts the Voxwell server, which is what the desktop app runs.
Every other command is a client of that running server over its local HTTP API, so models load
once, in the server, and the CLI itself needs only the standard library. Output is a short
sentence for people, or one JSON object with --json (for scripts and AI agents); errors go to
stderr (or a JSON {"error": ...} object) with exit code 1.
"""

import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path, PureWindowsPath

POLL_SECONDS = 2


class CliError(Exception):
    """A failure to report to the user, with a message that says what to do."""


class Client:
    """The running Voxwell server's HTTP API."""

    def __init__(self, base: str | None = None):
        self.base = base or f"http://127.0.0.1:{os.environ.get('VOXWELL_PORT', '8765')}"

    def request(self, method: str, path: str, body=None, headers: dict | None = None) -> bytes:
        """`body` is bytes or, for large uploads, an iterable of chunks with Content-Length set."""
        req = urllib.request.Request(self.base + path, data=body, headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=3600) as res:  # long texts and files take a while
                return res.read()
        except urllib.error.HTTPError as exc:
            raise CliError(_error_message(exc.read(), str(exc))) from exc
        except urllib.error.URLError as exc:
            raise CliError("Voxwell is not running. Open the Voxwell app, or run `voxwell serve` in another terminal.") from exc

    def get_json(self, path: str):
        return json.loads(self.request("GET", path))

    def post_json(self, path: str, payload: dict):
        return self.request("POST", path, json.dumps(payload).encode(), {"Content-Type": "application/json"})

    def post_form(self, path: str, fields: dict, file: Path):
        """Multipart upload of `fields` plus `file`, streamed so large videos never sit in memory."""
        boundary = uuid.uuid4().hex
        head = b"".join(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
            for name, value in fields.items()
        )
        content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        # The server shows the name as the job's title and never uses it as a path; drop the
        # characters that would end the header value early.
        filename = "".join("_" if c in '"\\\r\n' else c for c in file.name)
        head += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n".encode()
        )
        tail = f"\r\n--{boundary}--\r\n".encode()

        def chunks():
            yield head
            with file.open("rb") as f:
                while block := f.read(1 << 20):
                    yield block
            yield tail

        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(head) + file.stat().st_size + len(tail)),
        }
        return json.loads(self.request("POST", path, chunks(), headers))


def _error_message(body: bytes, fallback: str) -> str:
    """The server's message: FastAPI's {"detail": ...} or the OpenAI API's {"error": {"message": ...}}."""
    try:
        data = json.loads(body)
    except ValueError:
        return body.decode("utf-8", "replace") or fallback
    detail = data.get("detail") if isinstance(data, dict) else None
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list) and detail:  # request validation errors
        return "; ".join(f"{'.'.join(map(str, d.get('loc', [])[1:]))}: {d.get('msg')}" for d in detail)
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict) and error.get("message"):
        return error["message"]
    return fallback


def _on_this_computer(value: str) -> str:
    """Refuse network paths (\\\\server\\share, //server/share) before anything touches them.

    Opening one signs in to that server as the user (Windows sends NTLM), and the MCP tools take
    their paths from an AI assistant, which a document or web page can steer.
    """
    if PureWindowsPath(value).drive.startswith("\\\\"):
        raise CliError(f"Use a file on this computer, not a network path: {value}")
    return value


def _existing_file(value: str) -> Path:
    path = Path(_on_this_computer(value)).expanduser()
    if not path.is_file():
        raise CliError(f"File not found: {path}")
    return path


def _output_path(given: str | None, default_name: str, suffix: str) -> Path:
    path = (Path(_on_this_computer(given)).expanduser() if given else Path.cwd() / default_name).resolve()
    if path.is_dir():
        path = path / default_name
    if path.suffix.lower() != suffix:
        path = path.with_suffix(suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _voice_id(client: Client, voice: str) -> str:
    """A saved voice's id from its id or (case-insensitive) name."""
    saved = client.get_json("/api/voices")
    for v in saved:
        if voice in (v["id"], v["name"]) or voice.lower() == v["name"].lower():
            return v["id"]
    names = ", ".join(v["name"] for v in saved) or "none yet"
    raise CliError(f"Unknown voice '{voice}'. Saved voices: {names}.")


def _collection_id(client: Client, collection: str) -> str:
    """A voice collection's id from its id or (case-insensitive) name."""
    saved = client.get_json("/api/voice_collections")
    for c in saved:
        if collection in (c["id"], c["name"]) or collection.lower() == c["name"].lower():
            return c["id"]
    names = ", ".join(c["name"] for c in saved) or "none yet"
    raise CliError(f"Unknown collection '{collection}'. Collections: {names}.")


def _wait(client: Client, path: str, quiet: bool, label: str) -> dict:
    """Poll a background job until it is done; progress goes to stderr when it is a terminal."""
    quiet = quiet or not sys.stderr.isatty()
    while True:
        job = client.get_json(path)
        if job["state"] == "done":
            if not quiet:
                print(file=sys.stderr)
            return job
        if job["state"] == "error":
            raise CliError(job.get("error") or f"{label} failed.")
        if not quiet:
            step = f" ({job['step']})" if job.get("step") else ""
            print(f"\r{label}: {job.get('percent', 0):3.0f}%{step}".ljust(70), end="", file=sys.stderr, flush=True)
        time.sleep(POLL_SECONDS)


# --- commands: each returns (human text, JSON-able result) -----------------------------------


def cmd_status(client: Client, args) -> tuple[str, dict]:
    health = client.get_json("/api/health")
    return f"Voxwell is running at {client.base}.", {"running": True, "url": client.base, "features": health["features"]}


def cmd_voices(client: Client, args) -> tuple[str, dict]:
    saved = client.get_json("/api/voices")
    if not saved:
        return "No saved voices yet. Add one with `voxwell clone` or `voxwell design`.", {"voices": []}
    lines = [f"{v['name']}  (id {v['id']}, {v['source']})" for v in saved]
    return "\n".join(lines), {"voices": saved}


def cmd_sound(client: Client, args) -> tuple[str, dict]:
    if not args.prompt.strip():
        raise CliError("Describe the sound to make.")
    body = {"prompt": args.prompt.strip(), "duration": args.duration, "steps": args.steps}
    if args.seed is not None:
        body["seed"] = args.seed
    sound = json.loads(client.post_json("/api/sound/generate", body))
    out = _output_path(args.output, f"sound-{_stamp()}.wav", ".wav")
    out.write_bytes(client.request("GET", sound["url"]))
    return f"Saved the sound to {out} (seed {sound['seed']})", {"path": str(out), "seed": sound["seed"], "duration": sound["duration"]}


def cmd_collection(client: Client, args) -> tuple[str, dict]:
    action, name, rest = args.action, (args.name or "").strip(), args.rest
    base = "/api/voice_collections"
    if action == "list":
        collections = client.get_json(base)
        if not collections:
            return "No collections yet. Make one with `voxwell collection create NAME`.", {"collections": []}
        return "\n".join(f"{c['name']}  ({len(c['voice_ids'])} voices, id {c['id']})" for c in collections), {"collections": collections}
    if not name:
        raise CliError(f"Give the collection name: voxwell collection {action} NAME.")
    if action == "create":
        made = json.loads(client.post_json(base, {"name": name}))
        return f"Created the collection '{made['name']}' (id {made['id']}).", made
    collection_id = _collection_id(client, name)
    if action == "show":
        voices = json.loads(client.request("GET", f"{base}/{collection_id}/voices"))
        if not voices:
            return f"'{name}' has no voices yet.", {"voices": []}
        return "\n".join(f"{v['name']}  (id {v['id']}, {v['source']})" for v in voices), {"voices": voices}
    if action == "rename":
        if not rest:
            raise CliError("Give the new name: voxwell collection rename NAME NEW_NAME.")
        body = json.dumps({"name": " ".join(rest)}).encode()
        renamed = json.loads(client.request("PATCH", f"{base}/{collection_id}", body, {"Content-Type": "application/json"}))
        return f"Renamed the collection to '{renamed['name']}'.", renamed
    if action == "delete":
        client.request("DELETE", f"{base}/{collection_id}")
        return f"Deleted the collection '{name}'. Its voices are still saved.", {"deleted": collection_id}
    if not rest:
        raise CliError(f"Give the voices to {action}: voxwell collection {action} NAME VOICE...")
    result = None
    for voice in rest:
        result = json.loads(client.request("PUT" if action == "add" else "DELETE", f"{base}/{collection_id}/voices/{_voice_id(client, voice)}"))
    verb = "Added to" if action == "add" else "Removed from"
    return f"{verb} '{name}': {', '.join(rest)}.", result


def cmd_speak(client: Client, args) -> tuple[str, dict]:
    text = sys.stdin.read() if args.text == "-" else args.text
    if not text.strip():
        raise CliError("Give the text to speak (or - to read it from stdin).")
    body = {"input": text.strip(), "voice": args.voice or "default", "language": args.language, "speed": args.speed,
            "response_format": "wav"}
    wav = client.post_json("/v1/audio/speech", body)
    out = _output_path(args.output, f"speech-{_stamp()}.wav", ".wav")
    out.write_bytes(wav)
    return f"Saved the speech to {out}", {"path": str(out)}


def _speaker_fields(args) -> dict:
    """Form fields for the optional speaker labels; none at all unless they were asked for."""
    return {"speakers": "true", "num_speakers": args.num_speakers} if args.speakers else {}


def cmd_transcribe(client: Client, args) -> tuple[str, dict]:
    source = _existing_file(args.file)
    fields = {"language": args.language or "", **_speaker_fields(args)}
    job_id = client.post_form("/api/transcription/jobs", fields, source)["id"]
    job = _wait(client, f"/api/transcription/jobs/{job_id}", args.json, "Transcribing")
    transcript = job["transcript"]
    result = {"text": transcript["text"], "language": job.get("detected") or job.get("language"), "segments": transcript["segments"]}
    note = transcript.get("speakers_error")  # the transcript is fine, but the labels could not be added
    if note:
        result["speakers_error"] = note
    if args.format == "txt" and not args.output and not args.speakers:
        return transcript["text"], result
    rendered = client.request("GET", f"/api/transcription/jobs/{job_id}/export/{args.format}")
    if args.format == "txt" and not args.output:  # printed with its "Speaker 1:" labels
        return rendered.decode("utf-8").strip() + (f"\n\n[{note}]" if note else ""), result
    out = _output_path(args.output, f"{source.stem}.{args.format}", f".{args.format}")
    out.write_bytes(rendered)
    result["path"] = str(out)
    return f"Saved the transcript to {out}" + (f"\n{note}" if note else ""), result


def cmd_align(client: Client, args) -> tuple[str, dict]:
    audio = _existing_file(args.file)
    if args.script_text is not None:  # given directly (the MCP tool); a CLI always passes a file
        script = args.script_text
    elif args.script == "-":
        script = sys.stdin.read()
    else:
        script = _existing_file(args.script).read_text(encoding="utf-8", errors="replace")
    if not script.strip():
        raise CliError("The script is empty.")
    fields = {"script": script, "language": args.language or "", "max_chars": args.max_chars, "max_seconds": args.max_seconds}
    result = client.post_form("/api/transcription/align", fields, audio)
    out = _output_path(args.output, f"{audio.stem}.{args.format}", f".{args.format}")
    out.write_text(result[args.format], encoding="utf-8")
    note = f" ({result['matched']} of {result['total']} words matched the audio)"
    if result["fallback"]:
        note = " (none of the words matched the audio, so the times are estimates; check the script and language)"
    return f"Saved the subtitles to {out}{note}", {**{k: result[k] for k in ("language", "words", "cues", "matched", "total", "fallback")}, "path": str(out)}


def cmd_edit(client: Client, args) -> tuple[str, dict]:
    if args.text is not None:  # given directly (the MCP tool); a CLI always passes a file
        text = args.text
    elif args.file == "-":
        text = sys.stdin.read()
    else:
        text = _existing_file(args.file).read_text(encoding="utf-8", errors="replace")
    body = {"text": text, **({"preset": args.preset} if args.preset else {"instruction": args.instruction})}
    if not args.preset and not (args.instruction or "").strip():
        raise CliError("Give --preset or --instruction.")
    result = json.loads(client.post_json("/api/transcription/edit", body))
    if not args.output:
        return result["text"], result
    out = _output_path(args.output, f"{Path(args.file).stem}.edited.txt", ".txt")
    out.write_text(result["text"] + "\n", encoding="utf-8")
    return f"Saved the edited text to {out}", {**result, "path": str(out)}


def cmd_isolate(client: Client, args) -> tuple[str, dict]:
    source = _existing_file(args.file)
    folder = (Path(_on_this_computer(args.output)).expanduser() if args.output else source.parent).resolve()
    result = client.post_form("/api/tools/isolate", {}, source)
    folder.mkdir(parents=True, exist_ok=True)
    paths = {}
    for part in ("voice", "background"):
        path = folder / f"{source.stem}.{part}.wav"
        path.write_bytes(client.request("GET", result[part]["url"]))
        paths[part] = str(path)
    return f"Saved the voice to {paths['voice']}\nSaved the background to {paths['background']}", {**paths, "seconds": result["seconds"]}


def cmd_clone(client: Client, args) -> tuple[str, dict]:
    voice = client.post_form("/api/voice_cloning/voices", {"name": args.name}, _existing_file(args.file))
    return f"Saved the voice '{voice['name']}' (id {voice['id']}).", voice


def cmd_design(client: Client, args) -> tuple[str, dict]:
    preview = json.loads(client.post_json("/api/voice_design/preview", {"description": args.description, "sample_text": args.sample}))
    result = {}
    if args.preview:
        out = _output_path(args.preview, f"voice-preview-{_stamp()}.wav", ".wav")
        out.write_bytes(client.request("GET", preview["url"]))
        result["preview_path"] = str(out)
    voice = json.loads(client.post_json("/api/voice_design/save", {"preview_id": preview["preview_id"], "name": args.name}))
    result.update(voice)
    text = f"Saved the designed voice '{voice['name']}' (id {voice['id']})."
    if args.preview:
        text += f"\nSaved a preview to {result['preview_path']}"
    return text, result


def cmd_convert(client: Client, args) -> tuple[str, dict]:
    source = _existing_file(args.file)
    result = client.post_form("/api/tools/convert", {"voice_id": _voice_id(client, args.voice)}, source)
    out = _output_path(args.output, f"{source.stem}.converted.wav", ".wav")
    out.write_bytes(client.request("GET", result["url"]))
    return f"Saved the converted recording to {out}", {"path": str(out)}


def cmd_dub(client: Client, args) -> tuple[str, dict]:
    source = _existing_file(args.file)
    voice = "original" if args.voice == "original" else _voice_id(client, args.voice)
    job_id = client.post_form("/api/dubbing/jobs", {"target_language": args.to, "voice": voice, **_speaker_fields(args)}, source)["id"]
    _wait(client, f"/api/dubbing/jobs/{job_id}", args.json, "Dubbing")
    out = _output_path(args.output, f"{source.stem}.{args.to}.mp4", ".mp4")
    out.write_bytes(client.request("GET", f"/api/dubbing/jobs/{job_id}/video"))
    subtitles = out.with_suffix(".srt")
    subtitles.write_bytes(client.request("GET", f"/api/dubbing/jobs/{job_id}/subtitles"))
    return f"Saved the dubbed video to {out}\nSaved the subtitles to {subtitles}", {"path": str(out), "subtitles": str(subtitles)}


def cmd_chat(client: Client, args) -> tuple[str, dict]:
    message = sys.stdin.read() if args.message == "-" else args.message
    if not message.strip():
        raise CliError("Give the message (or - to read it from stdin).")
    saved = client.get_json("/api/agents/agents")
    agent = next((a for a in saved if args.agent in (a["id"], a["name"]) or args.agent.lower() == a["name"].lower()), None)
    if agent is None:
        names = ", ".join(a["name"] for a in saved) or "none yet (create one on the Voice agents page)"
        raise CliError(f"Unknown agent '{args.agent}'. Saved agents: {names}.")
    result = json.loads(client.post_json(f"/api/agents/agents/{agent['id']}/chat", {"message": message.strip(), "speak": False}))
    lines = [f"[{c['tool'] or 'tool'}: {c.get('result', c.get('error'))}]" for c in result["tool_calls"]]
    return "\n".join([*lines, result["reply"]]), {"agent": agent["name"], **result}


def cmd_translate(client: Client, args) -> tuple[str, dict]:
    if args.file and args.text:
        raise CliError("Give the text or --file, not both.")
    voice = _voice_id(client, args.voice) if args.voice else ""
    if args.file:
        fields = {"target": args.to, "source": args.source or "", "voice": voice}
        result = client.post_form("/api/translation/file", fields, _existing_file(args.file))
    else:
        text = sys.stdin.read() if args.text == "-" else (args.text or "")
        if not text.strip():
            raise CliError("Give the text to translate (or - to read it from stdin), or --file with a recording.")
        body = {"text": text.strip(), "source": args.source or "en", "target": args.to, "voice": voice or None}
        result = json.loads(client.post_json("/api/translation/speak", body))
    out = _output_path(args.output, f"translation-{_stamp()}.{args.to}.wav", ".wav")
    out.write_bytes(client.request("GET", result["url"]))
    data = {"transcript": result["transcript"], "source": result["source"], "translation": result["translation"], "path": str(out)}
    return f"{result['translation']}\nSaved the speech to {out}", data


def _add_speaker_options(p: argparse.ArgumentParser, speakers_help: str) -> None:
    p.add_argument("--speakers", action="store_true", help=speakers_help)
    p.add_argument("--num-speakers", type=int, default=0, metavar="N", help="with --speakers: how many people speak, 1 to 20 (default: find out)")


def cmd_effects(client: Client, args) -> tuple[str, dict]:
    source = _existing_file(args.file)
    fields = {"reverb": args.reverb, "distance": args.distance, "noise": args.noise, "noise_color": args.noise_color, "pan": args.pan}
    result = client.post_form("/api/audio_effects/apply", fields, source)
    out = _output_path(args.output, f"{source.stem}.effects.wav", ".wav")
    out.write_bytes(client.request("GET", result["url"]))
    return f"Saved the processed recording to {out}", {"path": str(out)}


def cmd_pronounce(client: Client, args) -> tuple[str, dict]:
    language = urllib.parse.quote(args.language)
    entries = client.get_json(f"/api/pronunciation/entries?language={language}")
    if args.action == "list":
        if not entries:
            return f"No pronunciations for '{args.language}' yet. Add one with `voxwell pronounce add WORD RESPELLING`.", {"entries": []}
        return "\n".join(f"{e['word']} -> {e['respelling']}" for e in entries), {"entries": entries}
    if not args.word:
        raise CliError("Give the word.")
    existing = next((e for e in entries if e["word"].lower() == args.word.strip().lower()), None)
    if args.action == "remove":
        if existing is None:
            raise CliError(f"'{args.word}' has no pronunciation for '{args.language}'.")
        client.request("DELETE", f"/api/pronunciation/entries/{existing['id']}?language={language}")
        return f"Removed the pronunciation of '{existing['word']}'.", {"removed": existing}
    if not args.respelling:
        raise CliError("Give the respelling, e.g. `voxwell pronounce add Nguyen win`.")
    body = {"language": args.language, "word": args.word, "respelling": args.respelling,
            "case_sensitive": args.case_sensitive, "whole_word": not args.partial}
    if existing is None:
        entry = json.loads(client.post_json("/api/pronunciation/entries", body))
    else:
        entry = json.loads(client.request("PUT", f"/api/pronunciation/entries/{existing['id']}", json.dumps(body).encode(),
                                          {"Content-Type": "application/json"}))
    return f"'{entry['word']}' will be spoken as '{entry['respelling']}'.", entry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voxwell",
        description="Voxwell: local voice cloning, voice design, dubbing, translation, transcription, voice isolation and voice agents. "
        "Commands other than `serve` need Voxwell running (the desktop app, or `voxwell serve`).",
        epilog="Add --json to any command for machine-readable output.",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="print one JSON object instead of text")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    sub.add_parser("serve", help="start the Voxwell server (what the desktop app runs)")
    p = sub.add_parser("status", parents=[common], help="check that Voxwell is running")
    p.set_defaults(run=cmd_status)
    p = sub.add_parser("voices", parents=[common], help="list saved voices")
    p.set_defaults(run=cmd_voices)

    p = sub.add_parser("sound", parents=[common], help="generate a sound effect from a description (WAV)")
    p.add_argument("prompt", help='e.g. "rain on a tin roof, distant thunder"')
    p.add_argument("-d", "--duration", type=float, default=10, help="seconds, 1 to 30 (default 10)")
    p.add_argument("--seed", type=int, help="repeat a previous result by reusing its seed")
    p.add_argument("--steps", type=int, default=100, help="quality steps, 10 to 250 (default 100; fewer is faster)")
    p.add_argument("-o", "--output", help="WAV file or folder (default: ./sound-<time>.wav)")
    p.set_defaults(run=cmd_sound)
    p = sub.add_parser("collection", parents=[common], help="organize saved voices into collections (folders)")
    p.add_argument("action", choices=["list", "show", "create", "rename", "delete", "add", "remove"],
                   help="list collections; show a collection's voices; create/rename/delete one; add/remove voices")
    p.add_argument("name", nargs="?", help="collection name or id")
    p.add_argument("rest", nargs="*", help="rename: the new name; add/remove: saved voice names or ids")
    p.set_defaults(run=cmd_collection)

    p = sub.add_parser("speak", parents=[common], help="turn text into speech (WAV)")
    p.add_argument("text", help="what to say, up to 4096 characters; - reads it from stdin")
    p.add_argument("-v", "--voice", help="saved voice name or id (default: the built-in voice)")
    p.add_argument("-l", "--language", default="en", help="ISO 639-1 code, e.g. en, es, fr (default en)")
    p.add_argument("--speed", type=float, default=1.0, help="0.5 to 2.0 (default 1.0)")
    p.add_argument("-o", "--output", help="WAV file or folder (default: ./speech-<time>.wav)")
    p.set_defaults(run=cmd_speak)

    p = sub.add_parser("transcribe", parents=[common], help="transcribe an audio or video file")
    p.add_argument("file")
    p.add_argument("-l", "--language", help="ISO 639-1 code (default: detect it)")
    p.add_argument("-f", "--format", choices=["txt", "srt", "vtt"], default="txt", help="output format (default txt)")
    p.add_argument("-o", "--output", help="save to this file instead of printing the text")
    _add_speaker_options(p, "label who speaks: a 'Speaker 1:' prefix in TXT and SRT, <v Speaker 1> in VTT")
    p.set_defaults(run=cmd_transcribe)

    p = sub.add_parser("align", parents=[common], help="time a script against its recording (SRT or VTT subtitles)")
    p.add_argument("file", help="the audio or video that speaks the script")
    p.add_argument("script", help="a text file with the words spoken; - reads it from stdin")
    p.add_argument("-l", "--language", help="ISO 639-1 code (default: detect it)")
    p.add_argument("-f", "--format", choices=["srt", "vtt"], default="srt", help="subtitle format (default srt)")
    p.add_argument("-o", "--output", help="subtitle file or folder (default: <name>.<format> in the current folder)")
    p.add_argument("--max-chars", type=int, default=42, help="longest subtitle in characters, 10 to 200 (default 42)")
    p.add_argument("--max-seconds", type=float, default=6.0, help="longest subtitle in seconds, 1 to 30 (default 6)")
    p.set_defaults(run=cmd_align, script_text=None)
    p = sub.add_parser("edit", parents=[common], help="clean up a transcript with the local AI model")
    p.add_argument("file", help="a text file, e.g. from `transcribe -o`; - reads it from stdin")
    p.add_argument("-p", "--preset", help="filler (remove filler words), punctuation, formal or concise")
    p.add_argument("-i", "--instruction", help='your own instruction, e.g. "remove filler words"')
    p.add_argument("-o", "--output", help="save to this .txt file or folder instead of printing the text")
    p.set_defaults(run=cmd_edit, text=None)

    p = sub.add_parser("isolate", parents=[common], help="split a recording into the voice and the background")
    p.add_argument("file", help="WAV, MP3, FLAC or OGG, up to 10 minutes")
    p.add_argument("-o", "--output", help="folder for <name>.voice.wav and <name>.background.wav (default: next to the file)")
    p.set_defaults(run=cmd_isolate)

    p = sub.add_parser("clone", parents=[common], help="save a voice from a short, clean recording")
    p.add_argument("name", help="name for the new voice")
    p.add_argument("file", help="a few seconds of clean speech: WAV, MP3, FLAC or OGG")
    p.set_defaults(run=cmd_clone)

    p = sub.add_parser("design", parents=[common], help="create a voice from a description and save it")
    p.add_argument("description", help='e.g. "warm, low female voice, slight British accent"')
    p.add_argument("--name", required=True, help="name for the new voice")
    p.add_argument("--sample", help="text the preview says")
    p.add_argument("--preview", metavar="FILE", help="also save the preview WAV here")
    p.set_defaults(run=cmd_design)

    p = sub.add_parser("effects", parents=[common], help="add reverb, distance, background noise or stereo pan to a recording")
    p.add_argument("file", help="WAV, MP3, FLAC or OGG")
    p.add_argument("--reverb", type=float, default=0.0, help="0 to 1 (default 0)")
    p.add_argument("--distance", type=float, default=0.0, help="0 (close) to 1 (far away): duller, quieter, more reverberant")
    p.add_argument("--noise", type=float, default=0.0, help="background noise level, 0 to 1 (default 0)")
    p.add_argument("--noise-color", choices=["pink", "brown"], default="pink", help="kind of noise (default pink)")
    p.add_argument("--pan", type=float, default=0.0, help="-1 (left) to 1 (right); any other value makes the output stereo")
    p.add_argument("-o", "--output", help="WAV file or folder (default: <name>.effects.wav in the current folder)")
    p.set_defaults(run=cmd_effects)
    p = sub.add_parser("pronounce", parents=[common], help="list, add or remove how a word is pronounced")
    p.add_argument("action", choices=["list", "add", "remove"], help="add also updates an existing word")
    p.add_argument("word", nargs="?", help="the word as written")
    p.add_argument("respelling", nargs="?", help="how to write it so it is spoken right, e.g. win for Nguyen")
    p.add_argument("-l", "--language", default="en", help="ISO 639-1 code (default en)")
    p.add_argument("--case-sensitive", action="store_true", help="match only this exact capitalization")
    p.add_argument("--partial", action="store_true", help="also match inside longer words")
    p.set_defaults(run=cmd_pronounce)

    p = sub.add_parser("convert", parents=[common], help="re-speak a recording in a saved voice")
    p.add_argument("file")
    p.add_argument("-v", "--voice", required=True, help="saved voice name or id")
    p.add_argument("-o", "--output", help="WAV file or folder (default: <name>.converted.wav in the current folder)")
    p.set_defaults(run=cmd_convert)

    p = sub.add_parser("dub", parents=[common], help="dub a video into another language (MP4 + SRT)")
    p.add_argument("file", help="the video")
    p.add_argument("-t", "--to", required=True, help="target language, ISO 639-1 code")
    p.add_argument("-v", "--voice", default="original", help="saved voice name or id, or original (default: clone the speaker)")
    p.add_argument("-o", "--output", help="MP4 file or folder (default: <name>.<lang>.mp4 in the current folder)")
    _add_speaker_options(p, "keep each speaker's own voice (with the original voice) and label them in the subtitles")
    p.set_defaults(run=cmd_dub)

    p = sub.add_parser("chat", parents=[common], help="send a message to a saved voice agent and print its reply")
    p.add_argument("agent", help="saved agent name or id")
    p.add_argument("message", help="what to say; - reads it from stdin")
    p.set_defaults(run=cmd_chat)

    p = sub.add_parser("translate", parents=[common], help="translate text or a recording and speak it in another language (WAV)")
    p.add_argument("text", nargs="?", help="what to translate; - reads it from stdin (or use --file)")
    p.add_argument("--file", help="translate the speech in this audio or video file instead")
    p.add_argument("-t", "--to", required=True, help="target language, ISO 639-1 code")
    p.add_argument("--from", dest="source", help="source language (default: en for text, detected for --file)")
    p.add_argument("-v", "--voice", help="saved voice name or id (default: the built-in voice)")
    p.add_argument("-o", "--output", help="WAV file or folder (default: ./translation-<time>.<lang>.wav)")
    p.set_defaults(run=cmd_translate)
    return parser


def main(argv: list[str] | None = None, client: Client | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] == "serve":
        from voxwell.main import run

        run()
        return 0
    for stream in (sys.stdout, sys.stderr):  # transcripts and names can be in any language
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        text, result = args.run(client or Client(), args)
    except CliError as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"voxwell: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False) if args.json else text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
