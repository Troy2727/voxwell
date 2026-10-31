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

    word = mock.Mock(start=0.0, end=0.5, word=" hello")
    segment = mock.Mock(start=0.0, end=1.0, words=[word])
    whisper.return_value.transcribe.return_value = (iter([segment]), mock.Mock(language="en"))
    timings = engine.transcribe_words(tmp_path / "clip.wav", "en")
    assert [(w.start, w.end, w.text) for w in timings.words] == [(0.0, 0.5, "hello")]


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


def test_sherpa_onnx_diarization_calls_match_installed_api(monkeypatch, tmp_path):
    sherpa = pytest.importorskip("sherpa_onnx")
    import numpy as np
    from faster_whisper import audio as fw_audio

    from voxwell.features.transcription import diarization

    (tmp_path / "seg.onnx").write_bytes(b"x")
    (tmp_path / "emb.onnx").write_bytes(b"x")
    monkeypatch.setattr(diarization, "model_paths", lambda: (tmp_path / "seg.onnx", tmp_path / "emb.onnx"))
    monkeypatch.setattr(fw_audio, "decode_audio", lambda path, sampling_rate: np.zeros(16000, dtype="float32"))

    segment = mock.Mock(start=0.0, end=1.0, speaker=3)
    diarizer = mock.Mock(sample_rate=16000)
    diarizer.process.return_value.sort_by_start_time.return_value = [segment]
    configs = []

    def make(config):  # the config is the real class, so a wrong keyword fails here, as it would at runtime
        assert config.validate()
        configs.append(config)
        return diarizer

    real = sherpa.OfflineSpeakerDiarization
    monkeypatch.setattr(sherpa, "OfflineSpeakerDiarization", make)
    turns = diarization.diarize(tmp_path / "clip.wav", num_speakers=2)
    assert turns == [diarization.Turn(0.0, 1.0, 3)] and configs[0].clustering.num_clusters == 2
    callback = diarizer.process.call_args.kwargs["callback"]
    assert callback(1, 4) == 0  # sherpa-onnx keeps going when the callback returns 0
    diarization.diarize(tmp_path / "clip.wav")
    assert configs[1].clustering.num_clusters == -1  # detect the number of speakers
    # The Python wrapper exposes the calls we make: process(samples, callback=...) and the result's sorting.
    assert "callback" in real.process.__doc__ and "samples" in real.process.__doc__
    assert hasattr(sherpa.OfflineSpeakerDiarizationResult, "sort_by_start_time")


def test_chatterbox_diffusers_imports_still_exist():
    """chatterbox-tts 0.1.6 pins diffusers==0.29.0 but runs on the newer one we override it with
    (for Stable Audio; see pyproject.toml). Newer diffusers releases removed some of these names,
    so a bump that drops one must fail here instead of when a user first clones a voice."""
    pytest.importorskip("diffusers")
    from diffusers.models.activations import get_activation
    from diffusers.models.attention import GEGLU, GELU, AdaLayerNorm, AdaLayerNormZero, ApproximateGELU
    from diffusers.models.attention_processor import Attention
    from diffusers.models.lora import LoRACompatibleLinear
    from diffusers.utils.torch_utils import maybe_allow_in_graph

    assert all([get_activation, GEGLU, GELU, AdaLayerNorm, AdaLayerNormZero, ApproximateGELU, Attention,
                LoRACompatibleLinear, maybe_allow_in_graph])
    # The modules that use them import cleanly too.
    pytest.importorskip("chatterbox.mtl_tts")
    import chatterbox.models.s3gen.matcha.decoder  # noqa: F401
    import chatterbox.models.s3gen.matcha.transformer  # noqa: F401


def test_stable_audio_calls_match_installed_api(monkeypatch):
    pytest.importorskip("torch")
    diffusers = pytest.importorskip("diffusers")
    import torch

    from voxwell.features.sound import engine

    pipe = mock.create_autospec(diffusers.StableAudioPipeline, instance=True)
    pipe.vae = mock.Mock(sampling_rate=44100)
    pipe.to.return_value = pipe
    pipe.return_value = mock.Mock(audios=[torch.zeros(2, 44100 * 2)])
    loader = mock.create_autospec(diffusers.StableAudioPipeline.from_pretrained, return_value=pipe)
    monkeypatch.setattr(diffusers.StableAudioPipeline, "from_pretrained", loader)
    monkeypatch.setattr(engine, "_pipeline", None)
    monkeypatch.setattr(engine, "_pick_device", lambda: "cpu")

    assert engine.generate("rain", 1.0, 10, 7, "hf_token")[:4] == b"RIFF"
    assert loader.call_args.kwargs["token"] == "hf_token"


def test_voice_remix_s3gen_calls_match_installed_api():
    """Voice remix drives Chatterbox's S3Gen in steps (embed_ref, tokenizer, flow_inference, then
    hift_inference with S3Gen.inference's trim_fade), so those calls must not drift."""
    s3gen_module = pytest.importorskip("chatterbox.models.s3gen.s3gen")
    vc_module = pytest.importorskip("chatterbox.vc")
    import inspect

    embed = inspect.signature(s3gen_module.S3Token2Mel.embed_ref).parameters
    assert list(embed)[:3] == ["self", "ref_wav", "ref_sr"] and "device" in embed
    flow = inspect.signature(s3gen_module.S3Token2Wav.flow_inference).parameters
    assert list(flow)[:2] == ["self", "speech_tokens"] and {"ref_dict", "finalize"} <= set(flow)
    assert list(inspect.signature(s3gen_module.S3Token2Wav.hift_inference).parameters) == ["self", "speech_feat", "cache_source"]
    # Voice remix repeats what S3Gen.inference does between those two steps.
    assert "self.trim_fade" in inspect.getsource(s3gen_module.S3Token2Wav.inference)
    assert "self.tokenizer" in inspect.getsource(s3gen_module.S3Token2Mel.__init__)
    assert vc_module.ChatterboxVC.DEC_COND_LEN > 0
    assert "self.watermarker" in inspect.getsource(vc_module.ChatterboxVC.__init__)
