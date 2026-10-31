import io
import json
import re
import shutil
import urllib.error
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from voxwell import cli, voices
from voxwell.features.dictation import engine as stt
from voxwell.features.dictation.engine import AudioError, Segment, Transcript
from voxwell.features.integrations import mcp_server
from voxwell.features.transcription import jobs as transcription_jobs
from voxwell.features.integrations import router as integrations_router
from voxwell.features.voice_cloning import engine as tts
from voxwell.main import app

client = TestClient(app, base_url="http://127.0.0.1")
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
RATE = 24000


def wav_bytes(seconds: float = 1.0) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"\x10\x00\xf0\xff" * int(seconds * RATE / 2))
    return buf.getvalue()


def seconds(data: bytes) -> float:
    with wave.open(io.BytesIO(data)) as w:
        return w.getnframes() / w.getframerate()


@pytest.fixture
def fake_tts(monkeypatch):
    calls = []
    monkeypatch.setattr(tts, "synthesize", lambda t, l, r=None: calls.append((t, l, r and r.stem)) or wav_bytes())
    return calls


@pytest.fixture
def fake_stt(monkeypatch):
    t = Transcript("Hello there. Bye.", "en", [Segment(0.0, 1.0, "Hello there."), Segment(1.5, 2.0, "Bye.")])
    monkeypatch.setattr(stt, "transcribe", lambda p, language=None, on_progress=None: t)


def speech(**body):
    return client.post("/v1/audio/speech", json={"input": "Hello there.", "response_format": "wav", **body})


# --- /v1/audio/speech ----------------------------------------------------------------------


def test_models():
    assert {m["id"] for m in client.get("/v1/models").json()["data"]} >= {"tts-1", "whisper-1"}


def test_speech_wav(fake_tts):
    r = speech(model="tts-1", voice="alloy")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    assert seconds(r.content) == pytest.approx(1.0, abs=0.01)
    assert fake_tts == [("Hello there.", "en", None)]  # OpenAI voice names use the default voice


def test_voice_by_name_or_id(fake_tts):
    v = voices.save_voice("Narrator Anna", wav_bytes(), "upload")
    speech(voice="narrator anna")
    speech(voice=v.id, language="es")
    assert fake_tts == [("Hello there.", "en", v.id), ("Hello there.", "es", v.id)]


def test_unknown_voice_lists_saved_voices(fake_tts):
    voices.save_voice("Anna", wav_bytes(), "upload")
    r = speech(voice="Bob")
    assert r.status_code == 400
    assert r.json()["error"] == {"message": "Unknown voice 'Bob'. Saved voices: Anna.", "type": "invalid_request_error", "param": "voice"}


def test_long_input_is_spoken_in_pieces(fake_tts):
    text = " ".join(f"This is sentence number {i} of a long text." for i in range(20))
    r = speech(input=text)
    assert r.status_code == 200 and len(fake_tts) > 1
    assert " ".join(c[0] for c in fake_tts).split() == text.split()


def test_pcm_is_raw_samples(fake_tts):
    r = speech(response_format="pcm")
    assert r.content == wav_bytes()[44:]


@needs_ffmpeg
@pytest.mark.parametrize("fmt,magic", [("mp3", (b"ID3", b"\xff\xfb", b"\xff\xf3")), ("flac", (b"fLaC",)), ("opus", (b"OggS",))])
def test_encoded_formats(fake_tts, fmt, magic):
    r = speech(response_format=fmt)
    assert r.status_code == 200 and r.content.startswith(magic)


@needs_ffmpeg
def test_speed(fake_tts):
    assert seconds(speech(speed=2.0).content) == pytest.approx(0.5, abs=0.05)


@pytest.mark.parametrize("body,param", [
    ({"input": ""}, "input"), ({"input": "x" * 4097}, "input"), ({"response_format": "midi"}, "response_format"),
    ({"speed": 9}, "speed"), ({"language": "xx"}, "language"),
])
def test_speech_rejects(fake_tts, body, param):
    r = speech(**body)
    assert r.status_code == 400 and r.json()["error"]["param"] == param and fake_tts == []


# --- /v1/audio/transcriptions --------------------------------------------------------------


def transcribe(fmt="json", data=b"audio"):
    return client.post("/v1/audio/transcriptions", files={"file": ("a.mp3", data)}, data={"model": "whisper-1", "response_format": fmt})


@pytest.mark.parametrize("fmt,expected", [
    ("json", {"text": "Hello there. Bye."}),
    ("text", "Hello there. Bye."),
    ("srt", "1\n00:00:00,000 --> 00:00:01,000\nHello there.\n"),
    ("vtt", "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello there.\n"),
])
def test_transcription_formats(fake_stt, fmt, expected):
    r = transcribe(fmt)
    assert r.status_code == 200
    if isinstance(expected, dict):
        assert r.json() == expected
    else:
        assert r.text.startswith(expected)


def test_verbose_json(fake_stt):
    body = transcribe("verbose_json").json()
    assert body["language"] == "en" and body["duration"] == 2.0
    assert body["segments"][1] == {"id": 1, "start": 1.5, "end": 2.0, "text": "Bye."}


def test_transcription_errors(monkeypatch, fake_stt):
    assert transcribe(data=b"").status_code == 400
    assert transcribe("pdf").status_code == 400

    def bad(*a, **k):
        raise AudioError("Could not decode the audio.")

    monkeypatch.setattr(stt, "transcribe", bad)
    r = transcribe()
    assert r.status_code == 400 and r.json()["error"]["message"] == "Could not decode the audio."


# --- integrations info ---------------------------------------------------------------------


def test_info(monkeypatch, tmp_path):
    monkeypatch.setattr(integrations_router, "_home", lambda: tmp_path)
    body = client.get("/api/integrations/info").json()
    assert body["api_base"] == "http://127.0.0.1:8765/v1"
    assert body["mcp"]["args"][-1] == "voxwell-mcp" and body["mcp"]["args"][2].endswith("backend")
    assert body["mcp"]["env"]["UV_SYSTEM_CERTS"] == "1"  # uv must work behind TLS-inspecting networks
    assert "voxwell" in body["cli"] and body["skill"] == {"claude": False, "codex": False}


@pytest.mark.parametrize("agent", ["claude", "codex"])
def test_install_skill_fills_in_the_command(monkeypatch, tmp_path, agent):
    monkeypatch.setattr(integrations_router, "_home", lambda: tmp_path)
    r = client.post(f"/api/integrations/skill/{agent}")
    path = tmp_path / f".{agent}" / "skills" / "voxwell" / "SKILL.md"
    assert r.status_code == 200 and r.json()["path"] == str(path)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\nname: voxwell\n") and integrations_router.cli_command() in text
    assert integrations_router.SKILL_GENERIC_COMMAND not in text
    assert client.get("/api/integrations/info").json()["skill"][agent] is True
    assert client.post("/api/integrations/skill/cursor").status_code == 422


def test_skill_source_has_the_placeholder_the_installer_replaces():
    assert integrations_router.SKILL_GENERIC_COMMAND in integrations_router.SKILL_SOURCE.read_text(encoding="utf-8")


# --- MCP server ----------------------------------------------------------------------------


class AppClient(cli.Client):
    """cli.Client wired to the app in-process, so MCP tool calls run end to end."""

    def __init__(self):
        super().__init__("http://testserver")

    def request(self, method, path, body=None, headers=None):
        if body is not None and not isinstance(body, bytes):
            body = b"".join(body)  # the streamed upload
        r = client.request(method, path, content=body, headers=headers)
        if r.status_code >= 400:
            raise cli.CliError(cli._error_message(r.content, r.reason_phrase))
        return r.content


@pytest.fixture
def mcp(monkeypatch):
    monkeypatch.setattr(mcp_server, "_client", AppClient)
    monkeypatch.setattr(cli, "POLL_SECONDS", 0)
    monkeypatch.setattr(transcription_jobs, "start", transcription_jobs._work)  # run synchronously

    def call(method, params=None, msg_id=1):
        return mcp_server.handle({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}})

    return call


def tool(mcp, tool_name, /, **arguments):
    return mcp("tools/call", {"name": tool_name, "arguments": arguments})["result"]


def test_mcp_handshake_and_tool_list(mcp):
    init = mcp("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test"}})
    assert init["result"]["protocolVersion"] == "2025-03-26" and "tools" in init["result"]["capabilities"]
    assert mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    names = {t["name"] for t in mcp("tools/list")["result"]["tools"]}
    assert names == {"list_voices", "voice_collections", "speak", "generate_sound", "make_music", "transcribe", "edit_transcript", "align_script", "isolate_voice", "clone_voice", "design_voice", "convert_voice", "dub_video", "manage_pronunciations", "apply_effects", "translate_speech", "chat_with_agent"}
    assert names == set(mcp_server.HANDLERS)
    assert mcp("ping")["result"] == {}
    assert mcp("resources/list")["error"]["code"] == -32601


def test_integrations_page_lists_every_tool():
    """The page's tool table is static (it must show while the backend is offline), so keep it in step."""
    page = (integrations_router.BACKEND_DIR.parent / "app/src/features/integrations/Page.tsx").read_text(encoding="utf-8")
    assert set(re.findall(r"mcp: '(\w+)'", page)) == set(mcp_server.HANDLERS)
    assert set(re.findall(r"cli: '(\w+)'", page)) == {n[4:] for n in dir(cli) if n.startswith("cmd_")} - {"status"}


def test_mcp_speak_saves_a_wav(mcp, fake_tts, tmp_path):
    voices.save_voice("Anna", wav_bytes(), "upload")
    out = tmp_path / "hello.mp3"  # the extension is corrected to .wav
    result = tool(mcp, "speak", text="Hi there", voice="Anna", output_path=str(out))
    assert result["isError"] is False and str(out.with_suffix(".wav")) in result["content"][0]["text"]
    assert seconds(out.with_suffix(".wav").read_bytes()) == pytest.approx(1.0, abs=0.01)


def test_mcp_speak_default_location(mcp, fake_tts, isolated_data_dir):
    result = tool(mcp, "speak", text="Hi")
    assert result["isError"] is False and len(list((isolated_data_dir / "mcp").glob("speech-*.wav"))) == 1


def test_mcp_transcribe_and_list_voices(mcp, fake_stt, tmp_path):
    f = tmp_path / "talk.mp3"
    f.write_bytes(b"audio")
    assert tool(mcp, "transcribe", file_path=str(f))["content"][0]["text"] == "Hello there. Bye."
    assert "No saved voices" in tool(mcp, "list_voices")["content"][0]["text"]


def test_mcp_transcribe_can_label_speakers(mcp, monkeypatch, tmp_path):
    from voxwell.features.transcription import diarization

    t = Transcript("Hi. Bye.", "en", [Segment(0.0, 1.0, "Hi."), Segment(1.0, 2.0, "Bye.")])
    monkeypatch.setattr(stt, "transcribe", lambda p, language=None, on_progress=None: t)
    seen = []
    monkeypatch.setattr(diarization, "diarize", lambda path, n=0, on_progress=None: seen.append(n) or [diarization.Turn(0.0, 1.0, 0), diarization.Turn(1.0, 2.0, 1)])
    f = tmp_path / "talk.mp3"
    f.write_bytes(b"audio")
    plain = tool(mcp, "transcribe", file_path=str(f))["content"][0]["text"]
    assert plain == "Hi. Bye." and seen == []  # off by default
    labelled = tool(mcp, "transcribe", file_path=str(f), label_speakers=True, num_speakers=2)["content"][0]["text"]
    assert labelled.startswith("Speaker 1: Hi.") and "Speaker 2: Bye." in labelled and seen == [2]
    schema = next(x for x in mcp("tools/list")["result"]["tools"] if x["name"] == "dub_video")["inputSchema"]["properties"]
    assert "label_speakers" in schema and "num_speakers" in schema


def test_mcp_align_script(mcp, monkeypatch, tmp_path, isolated_data_dir):
    from voxwell.features.dictation.engine import Word, WordTimings

    monkeypatch.setattr(stt, "transcribe_words", lambda p, language=None, on_progress=None: WordTimings("en", [Word(0.0, 1.0, "Hi")]), raising=False)
    audio = tmp_path / "talk.mp3"
    audio.write_bytes(b"audio")
    result = tool(mcp, "align_script", file_path=str(audio), script="Hi")
    assert result["isError"] is False and (isolated_data_dir / "mcp" / "talk.srt").read_text(encoding="utf-8").startswith("1\n")
    script = tmp_path / "s.txt"
    script.write_text("Hi", encoding="utf-8")
    out = tmp_path / "talk.vtt"
    assert tool(mcp, "align_script", file_path=str(audio), script_path=str(script), format="vtt", output_path=str(out))["isError"] is False
    assert out.read_text(encoding="utf-8").startswith("WEBVTT")
    for args in ({}, {"script": "a", "script_path": "b"}, {"script": "  "}, {"script": "a", "format": "ass"}):
        assert tool(mcp, "align_script", file_path=str(audio), **args)["isError"] is True


def test_mcp_edit_transcript(mcp, monkeypatch, tmp_path):
    from voxwell.features.tools import direction

    monkeypatch.setattr(direction, "complete", lambda system, user, max_new_tokens=80: "Clean text.")
    assert tool(mcp, "edit_transcript", text="um text", preset="filler")["content"][0]["text"] == "Clean text."
    f = tmp_path / "t.txt"
    f.write_text("um text", encoding="utf-8")
    assert tool(mcp, "edit_transcript", file_path=str(f), instruction="clean it")["content"][0]["text"] == "Clean text."
    for args in ({}, {"text": "a", "file_path": "b"}, {"text": "  "}, {"text": "a"}):
        assert tool(mcp, "edit_transcript", **args)["isError"] is True


def test_mcp_isolate_clone_convert_design(mcp, monkeypatch, tmp_path, isolated_data_dir):
    from voxwell.features.tools import engine as tools_engine
    from voxwell.features.tools import isolation
    from voxwell.features.voice_design import engine as design_engine

    clip = tmp_path / "clip.wav"
    clip.write_bytes(wav_bytes())

    def fake_isolate(source, voice_out, background_out):
        voice_out.write_bytes(wav_bytes())
        background_out.write_bytes(wav_bytes())
        return 1.0

    monkeypatch.setattr(isolation, "isolate", fake_isolate)
    text = tool(mcp, "isolate_voice", file_path=str(clip))["content"][0]["text"]
    assert str(tmp_path / "clip.voice.wav") in text and (tmp_path / "clip.background.wav").exists()

    assert "Saved the voice 'Anna'" in tool(mcp, "clone_voice", name="Anna", file_path=str(clip))["content"][0]["text"]
    monkeypatch.setattr(tools_engine, "convert", lambda source, target: wav_bytes())
    result = tool(mcp, "convert_voice", file_path=str(clip), voice="anna")
    assert result["isError"] is False and (isolated_data_dir / "mcp" / "clip.converted.wav").exists()

    monkeypatch.setattr(design_engine, "design", lambda description, sample: wav_bytes())
    assert "'Deep'" in tool(mcp, "design_voice", description="deep calm narrator", name="Deep")["content"][0]["text"]
    assert {v.name for v in voices.list_voices()} == {"Anna", "Deep"}


def test_mcp_dub_video(mcp, monkeypatch, fake_tts, tmp_path, isolated_data_dir):
    from voxwell.features.dubbing import ffmpeg, translate
    from voxwell.features.dubbing import jobs as dubbing_jobs

    def fake_ffmpeg(args):
        out = Path(args[-1])
        out.write_bytes(wav_bytes() if out.suffix == ".wav" else b"video")

    monkeypatch.setattr(ffmpeg, "run_ffmpeg", fake_ffmpeg)
    monkeypatch.setattr(stt, "transcribe", lambda p, language=None: Transcript("hola", "es", [Segment(0.0, 1.0, "hola")]))
    monkeypatch.setattr(translate, "translate", lambda texts, s, t: texts)
    monkeypatch.setattr(dubbing_jobs, "start", dubbing_jobs._work)
    video = tmp_path / "talk.mp4"
    video.write_bytes(b"fakevideo")
    result = tool(mcp, "dub_video", file_path=str(video), target_language="EN")
    assert result["isError"] is False and (isolated_data_dir / "mcp" / "talk.en.mp4").read_bytes() == b"video"


def test_mcp_chat_with_agent(mcp, monkeypatch):
    from voxwell.features.agents import conversation, store

    replies = iter(['{"tool": "calculator", "arguments": {"expression": "2 + 2"}}', "Four."])
    monkeypatch.setattr(conversation, "_chat", lambda messages: next(replies))
    store.create(name="Maths", system_prompt="", voice="", language="en", tools=["calculator"])
    result = tool(mcp, "chat_with_agent", agent="maths", message="2+2?")
    assert result["isError"] is False and result["content"][0]["text"] == "[calculator: 4]\nFour."
    result = tool(mcp, "chat_with_agent", agent="Nobody", message="hi")
    assert result["isError"] is True and "Saved agents: Maths" in result["content"][0]["text"]


def test_mcp_translate_speech(mcp, monkeypatch, fake_tts, fake_stt, tmp_path, isolated_data_dir):
    from voxwell.features.dubbing import translate

    monkeypatch.setattr(translate, "translate", lambda texts, s, t: [f"[{s}>{t}] {x}" for x in texts])
    result = tool(mcp, "translate_speech", text="Good morning", target_language="ES")
    assert result["isError"] is False and result["content"][0]["text"].startswith("[en>es] Good morning")
    clip = tmp_path / "talk.wav"
    clip.write_bytes(wav_bytes())
    result = tool(mcp, "translate_speech", file_path=str(clip), target_language="fr", output_path=str(tmp_path / "out.wav"))
    assert result["isError"] is False and (tmp_path / "out.wav").read_bytes()[:4] == b"RIFF"
    assert len(list((isolated_data_dir / "mcp").glob("translation-*.es.wav"))) == 1
    assert tool(mcp, "translate_speech", target_language="es")["isError"] is True  # neither text nor file
    assert tool(mcp, "translate_speech", text="hi", file_path=str(clip), target_language="es")["isError"] is True


def test_mcp_tool_errors_are_reported_not_raised(mcp, fake_tts, tmp_path):
    assert tool(mcp, "speak", text="Hi", voice="Nobody")["isError"] is True
    assert tool(mcp, "speak", text="-")["isError"] is True  # never read the protocol stream as text
    assert tool(mcp, "clone_voice", name="", file_path="x")["content"][0]["text"] == "name is required."
    assert tool(mcp, "transcribe", file_path=str(tmp_path / "missing.wav"))["content"][0]["text"].startswith("File not found")
    assert mcp("tools/call", {"name": "nope"})["error"]["code"] == -32602


def test_mcp_when_voxwell_is_closed(monkeypatch):
    def refuse(*a, **k):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(cli.urllib.request, "urlopen", refuse)
    result = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "list_voices"}})
    assert result["result"]["isError"] and "not running" in result["result"]["content"][0]["text"]


def test_mcp_stdio_loop(monkeypatch, capsys):
    lines = [json.dumps({"jsonrpc": "2.0", "id": 7, "method": "ping"}), "not json", ""]
    monkeypatch.setattr(mcp_server.sys, "stdin", io.StringIO("\n".join(lines) + "\n"))
    mcp_server.main()
    out = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert out == [{"jsonrpc": "2.0", "id": 7, "result": {}}, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}]


def test_mcp_voice_collections(mcp):
    anna = voices.save_voice("Anna", wav_bytes(), "upload")
    text = lambda **a: tool(mcp, "voice_collections", **a)["content"][0]["text"]  # noqa: E731
    assert "No collections yet" in text(action="list")
    assert "Created the collection 'Leads'" in text(action="create", name="Leads")
    assert "Added to 'leads'" in text(action="add", name="leads", voices=["anna"])
    assert anna.id in text(action="show", name="Leads")
    assert "Renamed the collection to 'Cast'" in text(action="rename", name="Leads", new_name="Cast")
    assert "Removed from 'Cast'" in text(action="remove", name="Cast", voices=[anna.id])
    assert "Deleted the collection 'Cast'" in text(action="delete", name="Cast")
    assert voices.list_voices() == [anna]
    assert tool(mcp, "voice_collections", action="show", name="Nope")["isError"] is True


def test_mcp_make_music(mcp, monkeypatch, tmp_path):
    from voxwell.features.music import engine as music_engine
    from voxwell.features.music import jobs as music_jobs
    from voxwell.features.music import runtime as music_runtime

    assert "not installed" in tool(mcp, "make_music", prompt="lo-fi", instrumental=True)["content"][0]["text"]

    seen = []

    def generate(fields, files, on_progress):
        seen.append((fields, sorted(files)))
        return wav_bytes(), {"seed": fields["seed"], "metas": {}}

    monkeypatch.setattr(music_runtime, "is_installed", lambda: True)
    monkeypatch.setattr(music_engine, "generate", generate)
    monkeypatch.setattr(music_jobs, "submit", lambda *args: music_jobs._run(*args))
    reference = tmp_path / "ref.wav"
    reference.write_bytes(wav_bytes())
    out = tmp_path / "song.wav"
    result = tool(mcp, "make_music", prompt="dreamy synth-pop", lyrics="[Chorus]\nLa la", duration=20, bpm=100, key="A minor",
                  seed=9, reference_path=str(reference), output_path=str(out))
    assert result["isError"] is False and str(out) in result["content"][0]["text"] and out.read_bytes() == wav_bytes()
    (fields, files), = seen
    assert fields["lyrics"] == "[Chorus]\nLa la" and fields["bpm"] == 100 and fields["key_scale"] == "A minor" and fields["seed"] == 9
    assert fields["audio_duration"] == 20 and files == ["reference_audio"]
    assert tool(mcp, "make_music", prompt="pop")["isError"] is True  # lyrics or instrumental is required
