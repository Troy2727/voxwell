"""Engine calls must match the installed model libraries' real signatures.

Feature tests mock the engines entirely, so a wrong keyword (e.g. a parameter that only exists
in an unreleased version) would only surface on first real use. These tests replace the model
classes with autospecs, which raise TypeError on any call the real API would reject.
"""

from pathlib import Path
from unittest import mock

import pytest


def test_chatterbox_calls_match_installed_api(monkeypatch):
    mtl = pytest.importorskip("chatterbox.mtl_tts")
    import numpy as np

    from voxwell.features.voice_cloning import engine

    model = mock.create_autospec(mtl.ChatterboxMultilingualTTS, instance=True)
    model.sr = 24000
    model.generate.return_value = np.zeros(10, dtype="float32")
    loader = mock.create_autospec(mtl.ChatterboxMultilingualTTS.from_pretrained, return_value=model)
    monkeypatch.setattr(mtl.ChatterboxMultilingualTTS, "from_pretrained", loader)
    monkeypatch.setattr(engine, "_model", None)
    monkeypatch.setattr(engine, "_pick_device", lambda: "cpu")

    assert engine.synthesize("Hello", "en", Path("ref.wav"))[:4] == b"RIFF"
    # Japanese is excluded on purpose (its dependency is GPL-3.0; see engine.LANGUAGES).
    assert engine.LANGUAGES.keys() == mtl.SUPPORTED_LANGUAGES.keys() - {"ja"}


def test_chatterbox_watermarker_imports():
    pytest.importorskip("chatterbox.mtl_tts")
    import perth

    # perth swallows its ImportError and sets this to None; Chatterbox then fails at load time.
    assert perth.PerthImplicitWatermarker is not None


def test_chatterbox_checkpoints_load_without_cuda(monkeypatch):
    torch = pytest.importorskip("torch")
    from voxwell.features.voice_cloning import engine

    calls = []
    monkeypatch.setattr(torch, "load", lambda *a, **k: calls.append(k))
    before = torch.load
    with engine._torch_load_to_cpu():
        torch.load("ve.pt", weights_only=True)  # how chatterbox 0.1.6 calls it
        torch.load("conds.pt", map_location="cuda")  # explicit choices are kept
    assert calls == [{"weights_only": True, "map_location": "cpu"}, {"map_location": "cuda"}]
    assert torch.load is before  # restored afterwards


def test_faster_whisper_calls_match_installed_api(monkeypatch, tmp_path):
    fw = pytest.importorskip("faster_whisper")
    from voxwell.features.dictation import engine

    whisper = mock.create_autospec(fw.WhisperModel)
    segment = mock.Mock(start=0.0, end=1.0, text=" hello ")
    whisper.return_value.transcribe.return_value = (iter([segment]), mock.Mock(language="en"))
    monkeypatch.setattr(fw, "WhisperModel", whisper)
    monkeypatch.setattr(engine, "_model", None)

    transcript = engine.transcribe(tmp_path / "clip.wav", "en")
    assert (transcript.text, transcript.language) == ("hello", "en")


def test_m2m100_calls_match_installed_api(monkeypatch):
    transformers = pytest.importorskip("transformers")
    from voxwell.features.dubbing import translate

    tok = mock.create_autospec(transformers.M2M100Tokenizer, instance=True)
    tok.return_value = mock.Mock(**{"to.return_value": {"input_ids": [[1]]}})
    tok.get_lang_id.return_value = 7
    tok.batch_decode.return_value = ["hola"]
    model = mock.create_autospec(transformers.M2M100ForConditionalGeneration, instance=True)
    monkeypatch.setattr(translate, "_cache", {"tok": tok, "model": model, "device": "cpu"})

    assert translate.translate(["hello"], "en", "es") == ["hola"]
