"""Voice remix: make a new voice from a saved one and a description of the voice you want.

1. Voice design (Parler-TTS) speaks the script in a voice that matches the description. That take
   carries the description's pitch, pace, accent, style and recording quality.
2. Chatterbox's voice-conversion decoder (S3Gen) re-voices that take twice from the same speech
   tokens: once in the original voice, once in the designed one. The two mel spectrograms are
   aligned frame for frame (their length depends only on the tokens), so they are blended by the
   strength and turned into audio once. At "max" the designed take is used as it is.

The result is a new reference clip for the voice library; the original voice is not changed.
"""

import tempfile
from pathlib import Path

from voxwell.features.tools import engine as tools
from voxwell.features.voice_cloning import engine as cloning
from voxwell.features.voice_design import engine as design

# Share of the designed voice in the blend. Measured on two voice pairs with Chatterbox's speaker
# encoder (2026-10-31): similarity to the designed voice rose 0.74-0.78 (none of it) -> 0.78-0.81
# (low) -> 0.84-0.87 (medium) -> 0.95 (high) -> 0.97-0.98 (all of it), while similarity to the
# original fell 0.88-0.89 -> 0.83 -> 0.71 -> 0.72-0.74. Blending the speaker conditioning instead
# (prompt or x-vector) jumped from one voice to the other with no middle setting.
STRENGTHS = {"low": 0.25, "medium": 0.5, "high": 0.75, "max": 1.0}
# Parler-TTS mispronounced "this is a preview of my remixed voice" in every test take, so the
# default script (which becomes the new voice's reference clip) avoids it.
DEFAULT_SCRIPT = "Hi there! I can read you a bedtime story, narrate a documentary, or tell you the evening news."


def _ref(s3gen, path: Path, max_samples: int, device: str) -> dict:
    import librosa
    from chatterbox.models.s3gen import S3GEN_SR

    wav, _ = librosa.load(str(path), sr=S3GEN_SR)
    return s3gen.embed_ref(wav[:max_samples], S3GEN_SR, device=device)


def blend(original_mel, designed_mel, weight: float):
    """Mel spectrogram `weight` of the way from the original voice's render to the designed one's.
    The renders can differ by a frame at the end (S3Gen trims its prompt by rounding), so the
    longer one is cut to the shorter."""
    frames = min(original_mel.shape[-1], designed_mel.shape[-1])
    return (1 - weight) * original_mel[..., :frames] + weight * designed_mel[..., :frames]


def remix(source_voice: Path, prompt: str, strength: str, script: str) -> bytes:
    """WAV bytes of `script` spoken by `source_voice` remixed toward the voice `prompt` describes."""
    import librosa
    import torch
    from chatterbox.models.s3tokenizer import S3_SR

    weight = STRENGTHS[strength]
    designed_wav = design.design(prompt, script)
    vc = tools._load_vc()
    if weight >= 1.0:
        # The designed take as it is, but marked as AI-made like every other remix.
        import io

        import soundfile as sf

        samples, rate = sf.read(io.BytesIO(designed_wav), dtype="float32")
        return cloning._to_wav(torch.from_numpy(vc.watermarker.apply_watermark(samples, sample_rate=rate)), rate)

    with tempfile.TemporaryDirectory() as tmp:
        designed = Path(tmp) / "designed.wav"
        designed.write_bytes(designed_wav)
        with tools._lock, torch.inference_mode():
            s3gen = vc.s3gen
            audio_16k, _ = librosa.load(str(designed), sr=S3_SR)
            tokens, _ = s3gen.tokenizer(torch.from_numpy(audio_16k).float()[None].to(vc.device))
            original_mel = s3gen.flow_inference(tokens, ref_dict=_ref(s3gen, source_voice, vc.DEC_COND_LEN, vc.device), finalize=True)
            designed_mel = s3gen.flow_inference(tokens, ref_dict=_ref(s3gen, designed, vc.DEC_COND_LEN, vc.device), finalize=True)
            mel = blend(original_mel, designed_mel, weight).to(dtype=s3gen.dtype)
            wav, _ = s3gen.hift_inference(mel, None)
            wav[:, : len(s3gen.trim_fade)] *= s3gen.trim_fade  # as S3Gen.inference does: no spill-over from the reference
            samples = wav.squeeze(0).detach().cpu().numpy()
            # Mark the output as AI-made, as Chatterbox's own voice conversion does.
            samples = vc.watermarker.apply_watermark(samples, sample_rate=vc.sr)
    return cloning._to_wav(torch.from_numpy(samples), vc.sr)
