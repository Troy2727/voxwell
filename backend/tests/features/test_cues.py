"""Cue tags: the pure parsing functions, routing between the two Chatterbox models (both faked),
the audiobook chunker and the voice cloning endpoints."""

import io
import threading
import time
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient

from voxwell.features.audiobook.chunking import MAX_CHARS, chapter_chunks
from voxwell.features.pronunciation import store as pronunciation
from voxwell.features.voice_cloning import cues, engine
from voxwell.main import app

client = TestClient(app, base_url="http://127.0.0.1")


# Parsing (no model)


def test_vocabulary_has_the_turbo_tags_in_lowercase():  # T1
    assert len(cues.VOCABULARY) == 19
    assert all(tag == tag.lower() for tag in cues.VOCABULARY)
    grouped = [tag for _, tags in cues.GROUPS for tag in tags]
    assert len(grouped) == len(set(grouped)) == 19


def test_matching_ignores_case_and_extra_spaces_but_not_other_spellings():  # T2
    assert cues.find("[Laugh] and [ clear   throat ] and [LAUGH]") == ["[laugh]", "[clear throat]", "[laugh]"]
    assert cues.canonical("Hi [ Clear  Throat ] there [LAUGH]") == "Hi [clear throat] there [laugh]"
    for text in ["[clear_throat]", "[laughs]", "[laugh", "laugh]", "[clear-throat]"]:
        assert cues.find(text) == []


def test_find_and_strip():  # T3
    assert cues.find("A [sigh] b [laugh] c") == ["[sigh]", "[laugh]"]
    assert cues.find("No tags here.") == []
    assert cues.strip_known("Well [sigh], ok.") == "Well, ok."
    assert cues.strip_known("Hi. [laugh] Bye.") == "Hi. Bye."
    assert cues.strip_known("[laugh] Hello there [sigh]") == "Hello there"
    assert cues.strip_known("Hi [laugh] [sigh] there.") == "Hi there."
    assert cues.strip_known("Plain  text, with  odd spacing .") == "Plain  text, with  odd spacing ."


def test_other_bracket_text_survives_and_reserved_tokens_go():  # T4
    for text in ["See [1].", "It was [sic] fine.", "[Chapter 2] Begin.", "[inaudible] yes"]:
        assert cues.strip_known(text) == text
        assert cues.strip_reserved(text) == text
    assert cues.strip_reserved("Oh [giggle] no [music].") == "Oh no."
    assert cues.strip_reserved("A [clear_throat] b") == "A b"
    assert cues.strip_reserved("Ha [laugh] [sigh] [clear throat].") == "Ha [laugh] [sigh] [clear throat]."


def test_pauses_are_split_out_before_cues():  # T5
    assert engine.split_pauses("Hello [pause 2] [laugh] there") == ["Hello", 2.0, "[laugh] there"]
    assert cues.find("[pause 2] [pause]") == []


# Routing (both models faked)


class FakeModel:
    sr = 24000

    def __init__(self, level: float):
        self.level, self.calls, self.busy, self.overlapped = level, [], False, False

    def generate(self, text, **kwargs):
        if self.busy:
            self.overlapped = True
        self.busy = True
        time.sleep(0.01)
        self.calls.append((text, kwargs))
        self.busy = False
        return np.full(100, self.level, dtype=np.float32)


@pytest.fixture
def models(monkeypatch):
    multi, turbo = FakeModel(0.1), FakeModel(0.2)
    hub = {"loads": 0, "error": None}

    def from_hub(device):
        hub["loads"] += 1
        if hub["error"]:
            raise hub["error"]
        return turbo

    monkeypatch.setattr(engine, "_load_model", lambda: multi)
    monkeypatch.setattr(engine, "_turbo_from_hub", from_hub)
    monkeypatch.setattr(engine, "_turbo", None)
    monkeypatch.setattr(engine, "_turbo_state", None)
    monkeypatch.setattr(engine, "_pick_device", lambda: "cpu")
    return multi, turbo, hub


def clip(tmp_path, seconds: float):
    path = tmp_path / f"ref-{seconds}.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x01" * int(16000 * seconds))
    return path


def test_english_cue_goes_to_turbo_with_the_voice(models, tmp_path):  # T6
    multi, turbo, _ = models
    ref = clip(tmp_path, 6)
    engine.synthesize("Hi [Laugh] there", "en", ref, exaggeration=0.9, cfg_weight=0.3)
    assert turbo.calls == [("Hi [laugh] there", {"audio_prompt_path": str(ref)})]
    assert multi.calls == []


def test_english_cue_without_a_voice_uses_turbos_own_voice(models):
    _, turbo, _ = models
    engine.synthesize("[sigh] Fine.", "en")
    assert turbo.calls == [("[sigh] Fine.", {})]


def test_other_languages_strip_cues_and_never_load_turbo(models):  # T7
    multi, turbo, hub = models
    engine.synthesize("Bonjour [laugh] toi.", "fr")
    assert multi.calls == [("Bonjour toi.", {"language_id": "fr", "exaggeration": 0.5, "cfg_weight": 0.5})]
    assert hub["loads"] == 0 and turbo.calls == []


def test_text_without_tags_takes_exactly_the_old_path(models):  # T8
    multi, _, hub = models
    out = engine.synthesize("Hello there. [pause 1] Bye.", "en")
    kwargs = {"language_id": "en", "exaggeration": 0.5, "cfg_weight": 0.5}
    assert multi.calls == [("Hello there.", kwargs), ("Bye.", kwargs)]
    expected = np.concatenate([np.full(100, 0.1, np.float32), np.zeros(24000, np.float32), np.full(100, 0.1, np.float32)])
    assert out == engine._to_wav(expected, 24000)
    assert hub["loads"] == 0


def test_unknown_brackets_are_spoken_and_cue_only_text_is_refused(models):  # T9
    multi, _, hub = models
    engine.synthesize("It was [sic] fine.", "en")
    assert multi.calls[0][0] == "It was [sic] fine."
    multi.calls.clear()
    with pytest.raises(ValueError, match="Nothing to say"):
        engine.synthesize("[laugh] [pause 1] [sigh]", "fr")
    r = client.post("/api/voice_cloning/synthesize", json={"text": "[laugh]", "language": "fr"})
    assert r.status_code == 422 and r.json()["detail"] == "Nothing to say after removing cue tags."
    assert multi.calls == [] and hub["loads"] == 0


def test_short_reference_falls_back_with_cues_left_out(models, tmp_path, monkeypatch):  # T10
    multi, turbo, hub = models
    from voxwell import voices

    engine.synthesize("Hi [laugh] there", "en", clip(tmp_path, 4))
    assert multi.calls[0][0] == "Hi there" and turbo.calls == [] and hub["loads"] == 0

    voice = voices.save_voice("Short", clip(tmp_path, 4).read_bytes(), "upload")
    r = client.post("/api/voice_cloning/synthesize", json={"text": "Hi [laugh]", "language": "en", "voice_id": voice.id})
    assert r.status_code == 200 and r.json()["cues_ignored"] is True


def test_turbo_that_cannot_load_falls_back_and_is_not_retried(models):  # T11
    multi, turbo, hub = models
    hub["error"] = OSError("offline")
    engine.synthesize("Hi [laugh] there", "en")
    engine.synthesize("Again [sigh]", "en")
    assert [c[0] for c in multi.calls] == ["Hi there", "Again"]
    assert hub["loads"] == 1 and engine.cues_ignored("Again [sigh]", "en")
    assert engine.turbo_available() is False


def test_turbo_out_of_memory_frees_retries_once_and_tries_again_next_call(models, monkeypatch):
    multi, turbo, hub = models
    monkeypatch.setattr(engine, "_model", multi)
    hub["error"] = RuntimeError("CUDA out of memory")
    engine.synthesize("Hi [laugh] there", "en")
    assert hub["loads"] == 2 and engine._model is None  # freed, retried once
    hub["error"] = None
    engine.synthesize("Hi [laugh] there", "en")
    assert hub["loads"] == 3 and turbo.calls == [("Hi [laugh] there", {})]


def test_pronunciation_never_rewrites_a_cue(models):  # T12
    _, turbo, _ = models
    pronunciation.add_entry("en", "laugh", "laff")
    engine.synthesize("I laugh [laugh] a lot", "en")
    assert turbo.calls[0][0] == "I laff [laugh] a lot"


def test_the_two_models_never_generate_at_the_same_time(monkeypatch, models):  # T13
    multi, turbo, _ = models
    shared = FakeModel(0.1)  # one object for both, so any overlap between the calls is seen
    monkeypatch.setattr(engine, "_load_model", lambda: shared)
    monkeypatch.setattr(engine, "_turbo_from_hub", lambda device: shared)
    threads = [threading.Thread(target=engine.synthesize, args=(t, "en")) for t in ["A [laugh]. B. [pause] C."] * 3 + ["A. [pause] B. [pause] C."] * 3]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(shared.calls) == 3 * 2 + 3 * 3 and not shared.overlapped


def test_low_gpu_memory_releases_multilingual_before_loading_turbo(models, monkeypatch):  # T14
    multi, turbo, _ = models
    monkeypatch.setattr(engine, "MIN_FREE_GPU_BYTES", 1000)
    monkeypatch.setattr(engine, "_release", lambda which, device: monkeypatch.setattr(engine, "_model", None))
    for device, free, kept in [("cuda", 10, False), ("cuda", 5000, True), ("cpu", 10, True), ("mps", 10, True)]:
        monkeypatch.setattr(engine, "_pick_device", lambda d=device: d)
        monkeypatch.setattr(engine, "_free_gpu_bytes", lambda f=free: f)
        monkeypatch.setattr(engine, "_model", multi)
        monkeypatch.setattr(engine, "_turbo", None)
        assert engine._load_turbo() is turbo
        assert (engine._model is multi) is kept, device


def test_status_lists_cues_and_synthesize_flags_ignored_ones(models):  # T15
    body = client.get("/api/voice_cloning/status").json()
    assert {"ready", "languages"} <= body.keys() and "en" in body["languages"]
    assert body["cues"]["languages"] == ["en"] and isinstance(body["cues"]["available"], bool)
    tags = [t["tag"] for g in body["cues"]["groups"] for t in g["tags"]]
    assert len(tags) == 19 and "clear throat" in tags
    assert {"tag": "clear throat", "label": "Clear throat"} in body["cues"]["groups"][0]["tags"]

    r = client.post("/api/voice_cloning/synthesize", json={"text": "Hola [laugh] amigo", "language": "es"})
    assert r.status_code == 200 and r.json()["cues_ignored"] is True
    r = client.post("/api/voice_cloning/synthesize", json={"text": "Hi [laugh] friend", "language": "en"})
    assert r.status_code == 200 and "cues_ignored" not in r.json()
    r = client.post("/api/voice_cloning/synthesize", json={"text": "Plain.", "language": "es"})
    assert set(r.json()) == {"id", "url"}


def test_chunker_keeps_cues_whole_and_never_alone():  # T16
    words = "word " * ((MAX_CHARS - 10) // 5)  # "[clear throat]" straddles the cut point
    sentence = f"{words}[clear throat] and then some more words to finish the sentence"
    out = [c for p in chapter_chunks(sentence) for c in p]
    assert len(out) > 1 and any("[clear throat]" in c for c in out)
    assert not any(c.endswith("[clear") or c.startswith("throat]") for c in out)

    prefix = ("word " * 60)[: MAX_CHARS - 6].rstrip()  # the last space before the cut is right before the tag
    out = [c for p in chapter_chunks(f"{prefix} [laugh].") for c in p]
    assert all(cues.has_speech(c) for c in out) and out[-1].endswith("[laugh].")

    out = [c for p in chapter_chunks("This sentence is long enough to stand alone. [sigh]") for c in p]
    assert out == ["This sentence is long enough to stand alone. [sigh]"]


def test_cues_false_keeps_the_old_behavior(models):  # T17
    multi, turbo, hub = models
    engine.synthesize("Hi [laugh] there", "en", cues=False)
    assert multi.calls[0][0] == "Hi there" and hub["loads"] == 0


# Review fixes


REAL_LOAD_MODEL = engine._load_model  # the models fixture replaces it


class VoiceModel(FakeModel):
    """A fake that, like Chatterbox, keeps the last cloned voice in .conds."""

    def __init__(self):
        super().__init__(0.1)
        self.conds, self.voices = "built-in", []

    def generate(self, text, audio_prompt_path=None, **kwargs):
        if audio_prompt_path:
            self.conds = f"clone of {audio_prompt_path}"
        self.voices.append(self.conds)
        return super().generate(text, **kwargs)


def test_no_voice_after_a_cloned_one_gets_the_built_in_voice_again(models, monkeypatch, tmp_path):
    turbo, multi = VoiceModel(), VoiceModel()
    monkeypatch.setattr(engine, "_turbo_from_hub", lambda device: turbo)
    monkeypatch.setattr(engine, "_multilingual_from_hub", lambda device: multi)
    monkeypatch.setattr(engine, "_load_model", REAL_LOAD_MODEL)
    monkeypatch.setattr(engine, "_model", None)
    ref = clip(tmp_path, 6)
    for text in ["Hi [laugh]", "Hello."]:  # Turbo, then Multilingual
        engine.synthesize(text, "en", ref)
        engine.synthesize(text, "en")
    assert turbo.voices == [f"clone of {ref}", "built-in"]
    assert multi.voices == [f"clone of {ref}", "built-in"]


def test_multilingual_out_of_memory_releases_turbo_and_retries_once(models, monkeypatch):
    multi, turbo, _ = models
    attempts = []

    def from_hub(device):
        attempts.append(device)
        if len(attempts) == 1:
            raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
        return multi

    monkeypatch.setattr(engine, "_multilingual_from_hub", from_hub)
    monkeypatch.setattr(engine, "_load_model", REAL_LOAD_MODEL)
    monkeypatch.setattr(engine, "_model", None)
    monkeypatch.setattr(engine, "_turbo", turbo)
    assert engine._load_model() is multi
    assert len(attempts) == 2 and engine._turbo is None

    monkeypatch.setattr(engine, "_model", None)
    monkeypatch.setattr(engine, "_multilingual_from_hub", lambda device: (_ for _ in ()).throw(OSError("offline")))
    with pytest.raises(OSError):  # anything else is not retried
        engine._load_model()


def test_hard_cut_with_no_safe_space_lands_on_a_tag_edge():
    for tag in ["[clear throat]", "[laugh]"]:
        long_word = "x" * (MAX_CHARS - 5) + tag + "y" * 50  # no space outside the tag; the tag crosses MAX_CHARS
        out = [c for p in chapter_chunks(long_word) for c in p]
        assert len(out) > 1 and "".join(out) == long_word  # cut at the tag's start: nothing lost, tag whole
        assert any(tag in c for c in out), out


def test_stripping_a_tag_between_two_words_keeps_them_apart():
    assert cues.strip_known("word[laugh]word") == "word word"
    assert cues.strip_known("word[laugh], ok") == "word, ok"
    assert cues.strip_known("([laugh]hi)") == "(hi)"


def test_audiobook_skips_a_cue_only_chunk_but_not_the_whole_text(models):
    from voxwell.features.audiobook.books import render_text

    multi, _, _ = models
    wav = render_text([["Bonjour tout le monde."], ["[laugh]"], ["Au revoir."]], "fr", None)
    assert [c[0] for c in multi.calls] == ["Bonjour tout le monde.", "Au revoir."]
    assert wav[:4] == b"RIFF"
    with pytest.raises(engine.NothingToSay):
        render_text([["[laugh]"], ["[music]"]], "fr", None)


def test_openai_speech_answers_400_when_only_cue_tags_were_sent(models):
    multi, _, _ = models
    r = client.post("/v1/audio/speech", json={"input": "[laugh] [sigh]", "language": "fr", "response_format": "wav"})
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "Nothing to say after removing cue tags."
    assert multi.calls == []


@pytest.mark.parametrize("path, body", [("/api/tools/speak", {"text": "[laugh]", "language": "fr"}), ("/api/tools/direction/speak", {"text": "[laugh]", "language": "fr"})])
def test_tools_say_why_a_cue_only_text_is_not_spoken(monkeypatch, path, body):
    def nothing(*a, **k):
        raise engine.NothingToSay("Nothing to say after removing cue tags.")

    monkeypatch.setattr(engine, "synthesize", nothing)
    r = client.post(path, json=body)
    assert r.status_code == 422 and r.json()["detail"] == "Nothing to say after removing cue tags."


def test_stripping_is_fast_on_long_runs_of_spaces():
    start = time.monotonic()
    text = " " * 50_000 + "x" + "\t" * 50_000 + "[laugh]"
    assert cues.strip_known(text) == " " * 50_000 + "x"
    assert time.monotonic() - start < 1
