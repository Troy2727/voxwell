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


def test_tail_limit_stops_speech_shortly_after_the_text_ends():
    torch = pytest.importorskip("torch")
    from voxwell.features.voice_cloning import engine

    class Analyzer:  # the parts of AlignmentStreamAnalyzer the limit uses
        def __init__(self):
            self.completed_at, self.curr_frame_pos, self.eos_idx = None, 0, 2

        def step(self, logits, next_token=None):
            self.curr_frame_pos += 1
            return logits

    engine._limit_tail(Analyzer)
    engine._limit_tail(Analyzer)  # applying it twice must not stack
    a = Analyzer()
    picks = []
    for frame in range(100):
        if frame == 40:
            a.completed_at = a.curr_frame_pos  # attention reached the end of the text
        picks.append(int(a.step(torch.zeros(1, 4)).argmax()))
    stop_frames = [f for f, tok in enumerate(picks) if tok == a.eos_idx]
    assert stop_frames[0] == 40 + engine.TAIL_FRAMES  # never earlier: the last word must survive
    assert all(tok == 0 for tok in picks[:stop_frames[0]])


def test_tail_limit_matches_installed_analyzer():
    asa = pytest.importorskip("chatterbox.models.t3.inference.alignment_stream_analyzer")
    t3 = pytest.importorskip("chatterbox.models.t3.t3")
    import inspect

    cls = asa.AlignmentStreamAnalyzer
    assert list(inspect.signature(cls.step).parameters)[:3] == ["self", "logits", "next_token"]
    init = inspect.getsource(cls.__init__)
    for field in ("self.completed_at", "self.curr_frame_pos", "self.eos_idx"):
        assert field in init, f"chatterbox renamed {field}; update engine._limit_tail"
    # Chatterbox builds the analyzer (and so the limit) only for the multilingual model, the one we use.
    assert "is_multilingual" in inspect.getsource(t3.T3.inference)


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


def test_translation_source_languages_match_installed_whisper():
    tokenizer = pytest.importorskip("faster_whisper.tokenizer")
    from voxwell.features.translation import pipeline

    assert pipeline.WHISPER_LANGUAGES == set(tokenizer._LANGUAGE_CODES)


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
