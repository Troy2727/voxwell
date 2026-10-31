import base64
import io
import math
import wave
from array import array

import pytest
from fastapi.testclient import TestClient

from voxwell import voices
from voxwell.features.dictation import engine as stt
from voxwell.features.dubbing import translate
from voxwell.features.translation import pipeline
from voxwell.features.voice_cloning import engine as tts
from voxwell.main import app
from voxwell.paths import data_dir

client = TestClient(app, base_url="http://127.0.0.1")


def wav_bytes(seconds: float = 0.5, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x10\x00" * int(seconds * rate))
    return buf.getvalue()


def speech(ms):
    return array("h", (int(9000 * math.sin(2 * math.pi * 220 * i / 16000)) for i in range(ms * 16))).tobytes()


def silence(ms):
    return bytes(ms * 32)


@pytest.fixture
def models(monkeypatch):
    """Fake speech recognition, translation and synthesis; `calls` records the order they ran in."""
    calls = []
    heard = iter(["one", "two", "three", "four"])

    def transcribe(path, language=None, on_progress=None):
        text = next(heard)
        calls.append(("transcribe", text, language))
        return stt.Transcript(text, language or "en", [])

    def fake_translate(texts, source, target):
        calls.append(("translate", " ".join(texts), source, target))
        return [f"{t}-{target}" for t in texts]

    def synthesize(text, language, reference=None, **kwargs):
        calls.append(("synthesize", text, language, reference and reference.stem))
        return wav_bytes()

    monkeypatch.setattr(stt, "transcribe", transcribe)
    monkeypatch.setattr(translate, "translate", fake_translate)
    monkeypatch.setattr(tts, "synthesize", synthesize)
    return calls


def live_session(config, turns_ms):
    with client.websocket_connect("ws://127.0.0.1/api/translation/live") as ws:
        ws.send_json({"type": "start", "config": {"silence_ms": 400, **config}})
        first = ws.receive_json()
        if first["type"] == "error":
            return [first]
        for ms in turns_ms:
            ws.send_bytes(speech(ms) + silence(500))
        ws.send_json({"type": "end"})
        messages = []
        while (m := ws.receive_json())["type"] != "done":
            messages.append(m)
        return messages


def test_languages_are_what_each_model_supports():
    langs = client.get("/api/translation/status").json()
    assert "en" in langs["sources"] and "es" in langs["targets"]
    assert set(langs["targets"]) <= set(tts.LANGUAGES) and set(langs["targets"]) <= translate.LANGUAGES
    assert set(langs["sources"]) <= translate.LANGUAGES and set(langs["sources"]) <= pipeline.WHISPER_LANGUAGES
    assert "ja" not in langs["targets"] and "ja" in langs["sources"]  # Japanese can be heard, not spoken


def test_live_turns_run_the_pipeline_in_order(models):
    voice = voices.save_voice("Anna", wav_bytes(), "upload")
    messages = live_session({"source": "en", "target": "es", "voice": voice.id}, [600, 600])
    turns = [m for m in messages if m["type"] == "turn"]
    assert [(t["index"], t["transcript"], t["translation"]) for t in turns] == [(0, "one", "one-es"), (1, "two", "two-es")]
    assert all(base64.b64decode(t["audio"])[:4] == b"RIFF" for t in turns)
    # Speech goes through the audiobook chunker, which ends a short line with a period.
    assert models == [
        ("transcribe", "one", "en"), ("translate", "one", "en", "es"), ("synthesize", "one-es.", "es", voice.id),
        ("transcribe", "two", "en"), ("translate", "two", "en", "es"), ("synthesize", "two-es.", "es", voice.id),
    ]
    assert list(data_dir("live").iterdir()) == []


def test_live_detects_the_source_language_by_default(models):
    live_session({"target": "fr"}, [600])
    assert models[0] == ("transcribe", "one", None)


def test_live_tts_failure_still_delivers_the_text(models, monkeypatch):
    def broken(text, language, reference=None, **kwargs):
        raise RuntimeError("out of memory")

    monkeypatch.setattr(tts, "synthesize", broken)
    [turn] = [m for m in live_session({"target": "es"}, [600]) if m["type"] == "turn"]
    assert turn["translation"] == "one-es" and "audio" not in turn
    assert turn["warning"] == "Could not speak the translation: out of memory"


@pytest.mark.parametrize(
    "config, message",
    [
        ({"target": "ja"}, "Unsupported target language 'ja'"),  # translatable, but not speakable
        ({"target": "xx"}, "Unsupported target language"),
        ({"source": "xx", "target": "es"}, "Unsupported source language 'xx'"),
        ({}, "Choose a target language"),
        ({"target": "es", "voice": "nope"}, "Unknown voice"),
    ],
)
def test_live_rejects_bad_settings(models, config, message):
    [error] = live_session(config, [])
    assert error["type"] == "error" and message in error["message"]


def test_live_detected_language_that_cannot_be_translated(models, monkeypatch):
    monkeypatch.setattr(stt, "transcribe", lambda path, language=None: stt.Transcript("sawubona", "jw", []))
    [error] = [m for m in live_session({"target": "es"}, [600]) if m["type"] == "error"]
    assert error["index"] == 0 and "does not support the language 'jw'" in error["message"]


def test_speak_text(models):
    r = client.post("/api/translation/speak", json={"text": "Hello. How are you?", "target": "de"})
    assert r.status_code == 200
    body = r.json()
    assert body["translation"] == "Hello. How are you?-de" and body["source"] == "en"
    assert client.get(body["url"]).content[:4] == b"RIFF"


def test_speak_text_errors(models):
    assert client.post("/api/translation/speak", json={"text": " ", "target": "de"}).status_code == 422
    r = client.post("/api/translation/speak", json={"text": "hi", "target": "xx"})
    assert r.status_code == 422 and "Unsupported target language" in r.json()["detail"]
    assert client.post("/api/translation/speak", json={"text": "x" * 5000, "target": "de"}).status_code == 422


def test_translate_file(models):
    r = client.post("/api/translation/file", files={"file": ("../talk.wav", wav_bytes(), "audio/wav")}, data={"target": "it"})
    assert r.status_code == 200 and r.json()["transcript"] == "one" and r.json()["translation"] == "one-it"
    assert [p.suffix for p in data_dir("translation").iterdir()] == [".wav"]  # the upload is gone


def test_audio_ids_are_checked():
    assert client.get("/api/translation/audio/..%2Fsecret").status_code == 404
    assert client.get("/api/translation/audio/" + "0" * 32).status_code == 404
