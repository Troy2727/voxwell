"""The `voxwell` CLI, run against the real app in-process (models faked as in the feature tests)."""

import io
import json
import os
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from voxwell import cli, voices
from voxwell.features.dictation import engine as dictation_engine
from voxwell.features.dictation.engine import Segment, Transcript
from voxwell.features.dubbing import ffmpeg
from voxwell.features.dubbing import jobs as dubbing_jobs
from voxwell.features.dubbing import translate as translator
from voxwell.features.tools import engine as tools_engine
from voxwell.features.tools import isolation
from voxwell.features.transcription import jobs as transcription_jobs
from voxwell.features.voice_cloning import engine as cloning_engine
from voxwell.features.voice_design import engine as design_engine
from voxwell.main import app


def wav_bytes(seconds: float = 1.0, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x10\x00\xf0\xff" * int(seconds * rate / 2))
    return buf.getvalue()


class AppClient(cli.Client):
    """cli.Client wired to the app in-process instead of over the network."""

    def __init__(self):
        super().__init__("http://testserver")
        self.http = TestClient(app, base_url="http://127.0.0.1")

    def request(self, method, path, body=None, headers=None):
        if body is not None and not isinstance(body, bytes):
            body = b"".join(body)  # the streamed upload
        res = self.http.request(method, path, content=body, headers=headers)
        if res.status_code >= 400:
            raise cli.CliError(cli._error_message(res.content, res.reason_phrase))
        return res.content


def run(capsys, *argv):
    code = cli.main(list(argv), client=AppClient())
    out, err = capsys.readouterr()
    return code, out, err


@pytest.fixture(autouse=True)
def fast_polling(monkeypatch):
    monkeypatch.setattr(cli, "POLL_SECONDS", 0)


@pytest.fixture
def audio(tmp_path) -> Path:
    path = tmp_path / "clip.wav"
    path.write_bytes(wav_bytes())
    return path


@pytest.mark.parametrize("path", ["//server/share/clip.wav", "\\\\server\\share\\clip.wav", "\\\\?\\UNC\\server\\share\\clip.wav"])
def test_network_paths_are_refused(path):
    """Opening \\\\server\\share signs in to that server as the user (Windows sends NTLM), so the
    CLI and MCP tools only read and write files on this computer."""
    with pytest.raises(cli.CliError, match="this computer"):
        cli._existing_file(path)
    with pytest.raises(cli.CliError, match="this computer"):
        cli._output_path(path, "out.wav", ".wav")


def test_isolate_refuses_a_network_output_folder(capsys, monkeypatch, audio):
    monkeypatch.setattr(isolation, "isolate", lambda *a, **k: pytest.fail("must refuse before isolating"))
    code, _, err = run(capsys, "isolate", str(audio), "-o", "//server/share")
    assert code != 0 and "this computer" in err


def test_no_arguments_start_the_server(monkeypatch):
    started = []
    monkeypatch.setattr("voxwell.main.run", lambda: started.append(True))
    assert cli.main([]) == 0 and cli.main(["serve"]) == 0 and started == [True, True]


def test_status_and_voices(capsys):
    code, out, _ = run(capsys, "status", "--json")
    assert code == 0 and json.loads(out)["running"] is True
    assert "No saved voices yet" in run(capsys, "voices")[1]
    voices.save_voice("Narrator", wav_bytes(), "upload")
    code, out, _ = run(capsys, "voices", "--json")
    assert [v["name"] for v in json.loads(out)["voices"]] == ["Narrator"]


def test_speak_saves_a_wav(capsys, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(cloning_engine, "synthesize", lambda text, language, ref=None, **k: calls.append((text, language)) or wav_bytes())
    code, out, _ = run(capsys, "speak", "Hello there.", "-l", "es", "-o", str(tmp_path / "hi"), "--json")
    path = Path(json.loads(out)["path"])
    assert code == 0 and path == tmp_path / "hi.wav" and path.read_bytes()[:4] == b"RIFF"
    assert calls == [("Hello there.", "es")]


def test_speak_reads_stdin(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(cloning_engine, "synthesize", lambda text, language, ref=None, **k: wav_bytes())
    monkeypatch.setattr("sys.stdin", io.StringIO("From a pipe"))
    code, out, _ = run(capsys, "speak", "-", "-o", str(tmp_path / "piped.wav"))
    assert code == 0 and "Saved the speech" in out and (tmp_path / "piped.wav").exists()


def test_transcribe_prints_or_saves(capsys, monkeypatch, audio, tmp_path):
    transcript = Transcript("Hello there.", "en", [Segment(0.0, 1.0, "Hello there.")])
    monkeypatch.setattr(dictation_engine, "transcribe", lambda path, language=None, on_progress=None: transcript)
    monkeypatch.setattr(transcription_jobs, "start", transcription_jobs._work)
    code, out, _ = run(capsys, "transcribe", str(audio))
    assert code == 0 and out.strip() == "Hello there."
    code, out, _ = run(capsys, "transcribe", str(audio), "-f", "srt", "-o", str(tmp_path / "subs"), "--json")
    result = json.loads(out)
    assert result["text"] == "Hello there." and Path(result["path"]).read_text().startswith("1\n00:00:00,000 --> ")


def test_align_writes_subtitles(capsys, monkeypatch, audio, tmp_path):
    from voxwell.features.dictation.engine import Word, WordTimings

    heard = [Word(0.0, 0.4, "Hello"), Word(0.5, 0.9, "there")]
    monkeypatch.setattr(dictation_engine, "transcribe_words", lambda path, language=None, on_progress=None: WordTimings("en", heard))
    script = tmp_path / "script.txt"
    script.write_text("Hello there!", encoding="utf-8")
    code, out, _ = run(capsys, "align", str(audio), str(script), "-o", str(tmp_path / "subs"))
    assert code == 0 and "2 of 2 words matched" in out
    assert (tmp_path / "subs.srt").read_text(encoding="utf-8") == "1\n00:00:00,000 --> 00:00:00,900\nHello there!\n"
    code, out, _ = run(capsys, "align", str(audio), str(script), "-f", "vtt", "-o", str(tmp_path / "v"), "--json")
    result = json.loads(out)
    assert code == 0 and result["matched"] == 2 and result["cues"][0]["text"] == "Hello there!"
    assert Path(result["path"]).read_text(encoding="utf-8").startswith("WEBVTT")
    monkeypatch.setattr("sys.stdin", io.StringIO("Something else entirely"))
    code, out, _ = run(capsys, "align", str(audio), "-", "-o", str(tmp_path / "x"))
    assert code == 0 and "estimates" in out
    assert run(capsys, "align", str(audio), str(tmp_path / "missing.txt"))[0] == 1
    script.write_text(" \n", encoding="utf-8")
    assert "script is empty" in run(capsys, "align", str(audio), str(script))[2]
    assert run(capsys, "align", str(audio), str(script), "--max-chars", "1")[0] == 1


def test_edit_prints_or_saves(capsys, monkeypatch, tmp_path):
    from voxwell.features.tools import direction

    monkeypatch.setattr(direction, "complete", lambda system, user, max_new_tokens=80: "Edited.")
    source = tmp_path / "talk.txt"
    source.write_text("Um, hello.", encoding="utf-8")
    code, out, _ = run(capsys, "edit", str(source), "-p", "filler")
    assert code == 0 and out.strip() == "Edited."
    code, out, _ = run(capsys, "edit", str(source), "-i", "make it formal", "-o", str(tmp_path / "out"), "--json")
    result = json.loads(out)
    assert code == 0 and Path(result["path"]).read_text(encoding="utf-8") == "Edited.\n" and Path(result["path"]).name == "out.txt"
    monkeypatch.setattr("sys.stdin", io.StringIO("From a pipe"))
    assert run(capsys, "edit", "-", "-p", "filler")[1].strip() == "Edited."
    code, _, err = run(capsys, "edit", str(source))
    assert code == 1 and "--preset or --instruction" in err
    assert run(capsys, "edit", str(source), "-p", "nope")[0] == 1


def test_isolate_writes_two_tracks(capsys, monkeypatch, audio, tmp_path):
    def fake_isolate(source, voice_out, background_out):
        voice_out.write_bytes(wav_bytes())
        background_out.write_bytes(wav_bytes(0.5))
        return 1.0

    monkeypatch.setattr(isolation, "isolate", fake_isolate)
    code, out, _ = run(capsys, "isolate", str(audio), "-o", str(tmp_path / "stems"), "--json")
    result = json.loads(out)
    assert code == 0 and Path(result["voice"]).name == "clip.voice.wav" and Path(result["background"]).name == "clip.background.wav"
    assert Path(result["voice"]).read_bytes() == wav_bytes() and Path(result["background"]).read_bytes() == wav_bytes(0.5)


def test_clone_then_convert_by_name(capsys, monkeypatch, audio, tmp_path):
    code, out, _ = run(capsys, "clone", "My Voice", str(audio), "--json")
    assert code == 0 and json.loads(out)["name"] == "My Voice"
    targets = []
    monkeypatch.setattr(tools_engine, "convert", lambda source, target: targets.append(target.stem) or wav_bytes())
    code, out, _ = run(capsys, "convert", str(audio), "-v", "my voice", "-o", str(tmp_path / "out.wav"))
    assert code == 0 and targets == [voices.list_voices()[0].id] and (tmp_path / "out.wav").exists()


def test_collections_organize_voices(capsys):
    voice = voices.save_voice("Narrator", wav_bytes(), "upload")
    assert "No collections yet" in run(capsys, "collection", "list")[1]
    assert run(capsys, "collection", "create", "Leads")[0] == 0
    assert run(capsys, "collection", "create", "leads")[0] == 1  # names are unique, any case
    assert run(capsys, "collection", "add", "leads", "narrator")[0] == 0
    code, out, _ = run(capsys, "collection", "show", "Leads", "--json")
    assert code == 0 and [v["id"] for v in json.loads(out)["voices"]] == [voice.id]
    assert run(capsys, "collection", "rename", "Leads", "Cast", "Members")[0] == 0
    code, out, _ = run(capsys, "collection", "list", "--json")
    assert [(c["name"], c["voice_ids"]) for c in json.loads(out)["collections"]] == [("Cast Members", [voice.id])]
    assert run(capsys, "collection", "remove", "Cast Members", "Narrator")[0] == 0
    assert run(capsys, "collection", "delete", "Cast Members")[0] == 0
    assert run(capsys, "collection", "show", "Cast Members")[0] == 1
    assert len(voices.list_voices()) == 1


def test_design_saves_the_voice_and_preview(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(design_engine, "design", lambda description, sample: wav_bytes())
    code, out, _ = run(capsys, "design", "deep calm narrator", "--name", "Deep", "--preview", str(tmp_path / "p.wav"), "--json")
    result = json.loads(out)
    assert code == 0 and result["name"] == "Deep" and result["source"] == "design" and Path(result["preview_path"]).exists()


@pytest.mark.parametrize("name, title", [
    ("Café talk.wav", "Café talk"),
    pytest.param('say "hi".wav', "say _hi_", marks=pytest.mark.skipif(os.name == "nt", reason='Windows file names cannot hold "')),
])
def test_jobs_are_titled_after_the_file(capsys, monkeypatch, audio, tmp_path, name, title):
    """Projects lists CLI and MCP work under the file's name, even one the header can't hold as is."""
    transcript = Transcript("Hi.", "en", [Segment(0.0, 1.0, "Hi.")])
    monkeypatch.setattr(dictation_engine, "transcribe", lambda path, language=None, on_progress=None: transcript)
    monkeypatch.setattr(transcription_jobs, "start", transcription_jobs._work)
    named = tmp_path / name
    named.write_bytes(audio.read_bytes())
    assert run(capsys, "transcribe", str(named))[0] == 0
    items = TestClient(app, base_url="http://127.0.0.1").get("/api/projects/items").json()
    assert title in [item["title"] for item in items if item["kind"] == "transcript"]


def test_chat_with_an_agent(capsys, monkeypatch):
    from voxwell.features.agents import conversation, store

    seen = []
    monkeypatch.setattr(conversation, "_chat", lambda messages, tools=None: seen.append(messages) or "Hello!")
    store.create(name="Guide", system_prompt="Be brief.", voice="", language="en", tools=[])
    code, out, _ = run(capsys, "chat", "guide", "Hi there", "--json")
    result = json.loads(out)
    assert code == 0 and result["reply"] == "Hello!" and result["agent"] == "Guide" and "audio" not in result
    assert seen[0][-1] == {"role": "user", "content": "Hi there"}
    code, _, err = run(capsys, "chat", "nobody", "hi")
    assert code == 1 and "Unknown agent 'nobody'" in err


def test_translate_text_or_file(capsys, monkeypatch, audio, tmp_path):
    calls = []
    monkeypatch.setattr(translator, "translate", lambda texts, s, t: calls.append((s, t)) or [f"[{t}] {x}" for x in texts])
    monkeypatch.setattr(cloning_engine, "synthesize", lambda *a, **k: wav_bytes())
    monkeypatch.setattr(dictation_engine, "transcribe", lambda p, language=None: Transcript("hola", "es", []))
    code, out, _ = run(capsys, "translate", "Hello there.", "--to", "fr", "-o", str(tmp_path / "fr"), "--json")
    result = json.loads(out)
    assert code == 0 and result["translation"] == "[fr] Hello there." and Path(result["path"]) == tmp_path / "fr.wav"
    code, out, _ = run(capsys, "translate", "--file", str(audio), "--to", "en", "-o", str(tmp_path / "en.wav"))
    assert code == 0 and out.startswith("[en] hola") and (tmp_path / "en.wav").exists()
    assert calls == [("en", "fr"), ("es", "en")]
    code, _, err = run(capsys, "translate", "Hi", "--to", "xx")
    assert code == 1 and "Unsupported target language 'xx'" in err
    code, _, err = run(capsys, "translate", "--to", "es")
    assert code == 1 and "Give the text" in err


def test_dub_downloads_video_and_subtitles(capsys, monkeypatch, tmp_path):
    def fake_ffmpeg(args):
        out = Path(args[-1])
        out.write_bytes(wav_bytes() if out.suffix == ".wav" else b"video")

    monkeypatch.setattr(ffmpeg, "run_ffmpeg", fake_ffmpeg)
    monkeypatch.setattr(dictation_engine, "transcribe", lambda p, language=None: Transcript("hola", "es", [Segment(0.0, 1.0, "hola")]))
    monkeypatch.setattr(translator, "translate", lambda texts, s, t: [f"[{t}] {x}" for x in texts])
    monkeypatch.setattr(cloning_engine, "synthesize", lambda *a, **k: wav_bytes())
    monkeypatch.setattr(dubbing_jobs, "start", dubbing_jobs._work)
    video = tmp_path / "talk.mp4"
    video.write_bytes(b"fakevideo")
    code, out, _ = run(capsys, "dub", str(video), "--to", "en", "-o", str(tmp_path / "dubbed"), "--json")
    result = json.loads(out)
    assert code == 0 and Path(result["path"]).read_bytes() == b"video"
    assert Path(result["subtitles"]).read_text(encoding="utf-8").strip().endswith("[en] hola")


def test_transcribe_and_dub_label_speakers(capsys, monkeypatch, audio, tmp_path):
    from voxwell.features.transcription import diarization

    turns = [diarization.Turn(0.0, 1.0, 0), diarization.Turn(1.0, 2.0, 1)]
    seen = []
    monkeypatch.setattr(diarization, "diarize", lambda path, n=0, on_progress=None: seen.append(n) or turns)
    transcript = Transcript("Hi. Bye.", "en", [Segment(0.0, 1.0, "Hi."), Segment(1.0, 2.0, "Bye.")])
    monkeypatch.setattr(dictation_engine, "transcribe", lambda path, language=None, on_progress=None: transcript)
    monkeypatch.setattr(transcription_jobs, "start", transcription_jobs._work)
    code, out, _ = run(capsys, "transcribe", str(audio), "--speakers", "--num-speakers", "2")
    assert code == 0 and out.strip() == "Speaker 1: Hi.\n\nSpeaker 2: Bye."
    assert seen == [2]
    code, out, _ = run(capsys, "transcribe", str(audio), "--speakers", "--json")
    assert [s["speaker"] for s in json.loads(out)["segments"]] == ["Speaker 1", "Speaker 2"]
    code, out, _ = run(capsys, "transcribe", str(audio), "--speakers", "-f", "vtt", "-o", str(tmp_path / "v"))
    assert "<v Speaker 2>Bye." in (tmp_path / "v.vtt").read_text(encoding="utf-8")

    def offline(path, n=0, on_progress=None):
        raise diarization.DiarizationError("Could not download the speaker model: offline")

    monkeypatch.setattr(diarization, "diarize", offline)
    code, out, _ = run(capsys, "transcribe", str(audio), "--speakers")
    assert code == 0 and out.startswith("Hi. Bye.") and out.strip().endswith("[Speaker labels failed: Could not download the speaker model: offline]")

    monkeypatch.setattr(diarization, "diarize", lambda path, n=0, on_progress=None: turns)

    def fake_ffmpeg(args):
        out_file = Path(args[-1])
        out_file.write_bytes(wav_bytes() if out_file.suffix == ".wav" else b"video")

    monkeypatch.setattr(ffmpeg, "run_ffmpeg", fake_ffmpeg)
    monkeypatch.setattr(dictation_engine, "transcribe", lambda p, language=None: transcript)
    monkeypatch.setattr(translator, "translate", lambda texts, s, t: texts)
    monkeypatch.setattr(cloning_engine, "synthesize", lambda *a, **k: wav_bytes())
    monkeypatch.setattr(dubbing_jobs, "start", dubbing_jobs._work)
    video = tmp_path / "talk.mp4"
    video.write_bytes(b"fakevideo")
    code, out, _ = run(capsys, "dub", str(video), "--to", "en", "--speakers", "-o", str(tmp_path / "dubbed"), "--json")
    assert code == 0 and "Speaker 2: Bye." in Path(json.loads(out)["subtitles"]).read_text(encoding="utf-8")


def test_errors_are_clear(capsys, tmp_path):
    code, _, err = run(capsys, "isolate", str(tmp_path / "missing.wav"))
    assert code == 1 and "File not found" in err
    code, out, _ = run(capsys, "convert", str(tmp_path), "-v", "x", "--json")  # a folder is not a file
    assert code == 1 and "File not found" in json.loads(out)["error"]
    (tmp_path / "a.wav").write_bytes(wav_bytes())
    code, _, err = run(capsys, "convert", str(tmp_path / "a.wav"), "-v", "Nobody")
    assert code == 1 and "Unknown voice 'Nobody'" in err


def test_server_errors_are_passed_on(capsys, audio):
    code, _, err = run(capsys, "speak", "Hi", "-v", "Nobody")  # the OpenAI-style error shape
    assert code == 1 and "Unknown voice 'Nobody'" in err
    bad = audio.with_name("bad.wav")
    bad.write_bytes(b"not audio")
    code, _, err = run(capsys, "isolate", str(bad))  # FastAPI's {"detail": ...} shape
    assert code == 1 and "Could not read the file as audio" in err


def test_not_running(capsys):
    code = cli.main(["voices", "--json"], client=cli.Client("http://127.0.0.1:9"))
    assert code == 1 and "Voxwell is not running" in json.loads(capsys.readouterr().out)["error"]
