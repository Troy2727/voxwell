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
from pathlib import Path

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


def _existing_file(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_file():
        raise CliError(f"File not found: {path}")
    return path


def _output_path(given: str | None, default_name: str, suffix: str) -> Path:
    path = (Path(given).expanduser() if given else Path.cwd() / default_name).resolve()
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


def cmd_transcribe(client: Client, args) -> tuple[str, dict]:
    source = _existing_file(args.file)
    job_id = client.post_form("/api/transcription/jobs", {"language": args.language or ""}, source)["id"]
    job = _wait(client, f"/api/transcription/jobs/{job_id}", args.json, "Transcribing")
    transcript = job["transcript"]
    result = {"text": transcript["text"], "language": job.get("detected") or job.get("language"), "segments": transcript["segments"]}
    if args.format == "txt" and not args.output:
        return transcript["text"], result
    rendered = client.request("GET", f"/api/transcription/jobs/{job_id}/export/{args.format}")
    out = _output_path(args.output, f"{source.stem}.{args.format}", f".{args.format}")
    out.write_bytes(rendered)
    result["path"] = str(out)
    return f"Saved the transcript to {out}", result


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
    result = client.post_form("/api/tools/isolate", {}, source)
    folder = (Path(args.output).expanduser() if args.output else source.parent).resolve()
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
    job_id = client.post_form("/api/dubbing/jobs", {"target_language": args.to, "voice": voice}, source)["id"]
    _wait(client, f"/api/dubbing/jobs/{job_id}", args.json, "Dubbing")
    out = _output_path(args.output, f"{source.stem}.{args.to}.mp4", ".mp4")
    out.write_bytes(client.request("GET", f"/api/dubbing/jobs/{job_id}/video"))
    subtitles = out.with_suffix(".srt")
    subtitles.write_bytes(client.request("GET", f"/api/dubbing/jobs/{job_id}/subtitles"))
    return f"Saved the dubbed video to {out}\nSaved the subtitles to {subtitles}", {"path": str(out), "subtitles": str(subtitles)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voxwell",
        description="Voxwell: local voice cloning, voice design, dubbing, transcription and voice isolation. "
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
    p.set_defaults(run=cmd_transcribe)

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
    p.set_defaults(run=cmd_dub)
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
