import hashlib
import io
import os
import pickle
import shutil
import subprocess
import time
import wave

import pytest
from fastapi.testclient import TestClient

from voxwell import voices
from voxwell.features.tools import engine, htdemucs, isolation
from voxwell.features.tools.router import MAX_ISOLATE_SECONDS
from voxwell.features.voice_cloning import engine as cloning_engine
from voxwell.main import app

client = TestClient(app, base_url="http://127.0.0.1")
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


def wav_bytes(seconds: float, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x10\x00\xf0\xff" * int(seconds * rate / 2))
    return buf.getvalue()


def duration(data: bytes) -> float:
    with wave.open(io.BytesIO(data)) as w:
        return w.getnframes() / w.getframerate()


def test_status():
    body = client.get("/api/tools/status").json()
    assert isinstance(body["ready"], bool) and isinstance(body["ffmpeg"], bool)


# --- speech-rate fit -----------------------------------------------------------------------


@pytest.mark.parametrize("tempo,chain", [
    (1.25, "atempo=1.250000"),
    (3.0, "atempo=2.000000,atempo=1.500000"),
    (0.3, "atempo=0.500000,atempo=0.600000"),
])
def test_atempo_chain(tempo, chain):
    assert engine._atempo_chain(tempo) == chain


@needs_ffmpeg
def test_fit_stretches_to_the_target_length():
    r = client.post("/api/tools/fit", files={"file": ("a.wav", wav_bytes(2.0))}, data={"target_seconds": "1.0"})
    assert r.status_code == 200 and r.json()["original_seconds"] == 2.0
    assert duration(client.get(r.json()["url"]).content) == pytest.approx(1.0, abs=0.05)


@pytest.mark.parametrize("target,status", [("0.2", 422), ("20", 422), ("0", 422), ("9999", 422)])
def test_fit_rejects_extreme_changes(target, status):
    r = client.post("/api/tools/fit", files={"file": ("a.wav", wav_bytes(2.0))}, data={"target_seconds": target})
    assert r.status_code == status


def test_fit_rejects_non_audio():
    r = client.post("/api/tools/fit", files={"file": ("a.wav", b"nope")}, data={"target_seconds": "1"})
    assert r.status_code == 422


# --- file info -----------------------------------------------------------------------------


@needs_ffmpeg
def test_probe_audio():
    info = client.post("/api/tools/probe", files={"file": ("a.wav", wav_bytes(1.5, 22050))}).json()
    assert info["duration"] == pytest.approx(1.5, abs=0.01)
    assert info["streams"] == [{"type": "audio", "codec": "PCM signed 16-bit little-endian", "sample_rate": 22050, "channels": 1}]


@needs_ffmpeg
def test_probe_video(tmp_path):
    video = tmp_path / "v.mp4"
    subprocess.run([shutil.which("ffmpeg"), "-loglevel", "error", "-f", "lavfi", "-i", "color=s=320x240:d=1:r=25",
                    "-pix_fmt", "yuv420p", str(video)], check=True)
    info = client.post("/api/tools/probe", files={"file": ("clip.mp4", video.read_bytes())}).json()
    assert {"type": "video", "width": 320, "height": 240, "fps": 25.0}.items() <= info["streams"][0].items()
    assert "language" not in info["streams"][0]  # ffmpeg tags it "und" (undetermined); not worth showing


@needs_ffmpeg
def test_probe_rejects_non_media():
    assert client.post("/api/tools/probe", files={"file": ("x.mp4", b"not a video")}).status_code == 422


def test_probe_never_uses_the_client_file_name(monkeypatch):
    seen = []
    monkeypatch.setattr(engine, "probe", lambda path: seen.append(path.name) or {})
    client.post("/api/tools/probe", files={"file": ("../../evil name.mp4", b"x")})
    client.post("/api/tools/probe", files={"file": ("weird.<>|", b"x")})
    client.post("/api/tools/probe", files={"file": ("list.m3u8", b"x")})  # a playlist name would pick the HLS demuxer
    assert seen == ["input", "input", "input"]


# --- voice conversion ----------------------------------------------------------------------


def test_convert(monkeypatch):
    voice = voices.save_voice("Target", wav_bytes(1), "upload")
    calls = []

    def fake_convert(source, target):
        calls.append((duration(source.read_bytes()), target.stem))
        return wav_bytes(0.5)

    monkeypatch.setattr(engine, "convert", fake_convert)
    r = client.post("/api/tools/convert", files={"file": ("me.wav", wav_bytes(1.0))}, data={"voice_id": voice.id})
    assert r.status_code == 200 and calls == [(1.0, voice.id)]
    assert duration(client.get(r.json()["url"]).content) == 0.5


def test_convert_needs_a_voice_and_audio(monkeypatch):
    monkeypatch.setattr(engine, "convert", lambda s, t: b"")
    voice = voices.save_voice("Target", wav_bytes(1), "upload")
    assert client.post("/api/tools/convert", files={"file": ("a.wav", wav_bytes(1))}, data={"voice_id": "000000000000"}).status_code == 422
    assert client.post("/api/tools/convert", files={"file": ("a.wav", b"nope")}, data={"voice_id": voice.id}).status_code == 422


def test_convert_engine_error(monkeypatch):
    def boom(*a):
        raise RuntimeError("download failed")

    monkeypatch.setattr(engine, "convert", boom)
    voice = voices.save_voice("Target", wav_bytes(1), "upload")
    r = client.post("/api/tools/convert", files={"file": ("a.wav", wav_bytes(1))}, data={"voice_id": voice.id})
    assert r.status_code == 500 and "download failed" not in r.json()["detail"] and r.json()["detail"].endswith("see the Voxwell log.")


# --- voice isolation -----------------------------------------------------------------------


def test_isolate_returns_voice_and_background(monkeypatch):
    calls = []

    def fake_isolate(source, voice_out, background_out):
        calls.append(duration(source.read_bytes()))
        voice_out.write_bytes(wav_bytes(1.0))
        background_out.write_bytes(wav_bytes(1.0))
        return 1.0

    monkeypatch.setattr(isolation, "isolate", fake_isolate)
    r = client.post("/api/tools/isolate", files={"file": ("song.wav", wav_bytes(1.0))})
    body = r.json()
    assert r.status_code == 200 and calls == [1.0] and body["seconds"] == 1.0
    assert body["voice"]["url"] != body["background"]["url"]
    for part in ("voice", "background"):
        assert duration(client.get(body[part]["url"]).content) == 1.0


def test_isolate_keeps_the_level_of_a_float_wav(monkeypatch):
    # Music apps, Voxwell's own music engine included, write 32-bit float WAVs; they must not arrive silent.
    sf = pytest.importorskip("soundfile")
    np = pytest.importorskip("numpy")
    peaks = []

    def fake_isolate(source, voice_out, background_out):
        peaks.append(int(np.abs(sf.read(str(source), dtype="int16")[0]).max()))
        voice_out.write_bytes(wav_bytes(1.0))
        background_out.write_bytes(wav_bytes(1.0))
        return 1.0

    monkeypatch.setattr(isolation, "isolate", fake_isolate)
    buf = io.BytesIO()
    sf.write(buf, 0.5 * np.sin(np.linspace(0, 2000, 16000)), 16000, format="WAV", subtype="FLOAT")
    assert client.post("/api/tools/isolate", files={"file": ("song.wav", buf.getvalue())}).status_code == 200
    assert 16000 < peaks[0] < 16500  # half of full scale, as sent


def test_isolate_rejects_bad_input(monkeypatch):
    monkeypatch.setattr(isolation, "isolate", lambda *a: pytest.fail("must not run"))
    assert client.post("/api/tools/isolate", files={"file": ("a.wav", b"nope")}).status_code == 422
    too_long = wav_bytes(MAX_ISOLATE_SECONDS + 1, rate=1000)
    r = client.post("/api/tools/isolate", files={"file": ("long.wav", too_long)})
    assert r.status_code == 422 and "10 minutes" in r.json()["detail"]


@pytest.mark.parametrize("error,status", [
    (isolation.IsolationError("Could not download the voice isolation model: offline"), 422),
    (RuntimeError("out of memory"), 500),
])
def test_isolate_errors(monkeypatch, error, status):
    def fail(*a):
        raise error

    monkeypatch.setattr(isolation, "isolate", fail)
    r = client.post("/api/tools/isolate", files={"file": ("a.wav", wav_bytes(1))})
    assert r.status_code == status and (str(error) in r.json()["detail"]) == (status == 422)  # only IsolationError text is for the user


def test_separate_windows_line_up_with_the_audio(monkeypatch):
    """A stand-in model that gives each stem a quarter of its input: the stems must add back up
    to the input for clips shorter than, as long as and longer than one window."""
    torch = pytest.importorskip("torch")
    monkeypatch.setattr(htdemucs, "SEGMENT", 1000)

    class Quarter(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.anchor = torch.nn.Parameter(torch.zeros(1))  # separate() reads the device from it

        def forward(self, x):
            return x[:, None].expand(-1, 4, -1, -1) / 4

    for length in (300, 1000, 2600):
        mix = torch.randn(2, length)
        mix -= mix.mean()
        stems = isolation.separate(mix, Quarter())
        assert stems.shape == (4, 2, length)
        assert torch.allclose(stems.sum(0), mix, atol=1e-5)


def test_corrupted_download_is_rejected(monkeypatch, isolated_data_dir):
    monkeypatch.setattr(isolation.urllib.request, "urlopen", lambda url, timeout: io.BytesIO(b"not the model"))
    with pytest.raises(isolation.IsolationError, match="corrupted"):
        isolation.weights_path()
    assert not any((isolated_data_dir / "models" / "isolation").iterdir())


class _RunsCode:
    def __reduce__(self):
        return (print, ("this must never run",))


def test_model_file_cannot_run_code(tmp_path):
    torch = pytest.importorskip("torch")
    path = tmp_path / "bad.th"
    torch.save({"kwargs": {"sources": list(htdemucs.SOURCES)}, "state": {}, "extra": _RunsCode()}, path)
    with pytest.raises(pickle.UnpicklingError):
        isolation.load_state(path)


def test_htdemucs_layout_matches_the_published_weights():
    """Any change to a module name or shape would stop Meta's checkpoint from loading. The
    signature was computed from the real checkpoint (955717e8): 533 tensors, 41,984,456 parameters."""
    torch = pytest.importorskip("torch")
    model = htdemucs.HTDemucs()
    state = model.state_dict()
    layout = "".join(f"{k}:{tuple(v.shape)};" for k, v in sorted(state.items()))
    assert len(state) == 533 and sum(p.numel() for p in model.parameters()) == 41_984_456
    assert hashlib.sha256(layout.encode()).hexdigest() == "5ad203e8cbb0f8a07dd38b67346453283f3e520913220d7976ee095daad59c52"
    with torch.no_grad():
        out = model.eval()(torch.randn(1, 2, htdemucs.SEGMENT))
    assert out.shape == (1, 4, 2, htdemucs.SEGMENT) and torch.isfinite(out).all()


# --- compare voices ------------------------------------------------------------------------


def test_speak_for_comparison_is_kept_out_of_projects(monkeypatch):
    calls = []
    monkeypatch.setattr(cloning_engine, "synthesize", lambda t, l, r=None: calls.append((t, l, r and r.stem)) or wav_bytes(1))
    voice = voices.save_voice("A", wav_bytes(1), "upload")
    for voice_id in (voice.id, None):
        r = client.post("/api/tools/speak", json={"text": "Hello", "language": "es", "voice_id": voice_id})
        assert client.get(r.json()["url"]).status_code == 200
    assert calls == [("Hello", "es", voice.id), ("Hello", "es", None)]
    assert client.get("/api/projects/items").json() == []


@pytest.mark.parametrize("body", [
    {"text": ""}, {"text": "x" * 301}, {"text": "Hi", "language": "xx"}, {"text": "Hi", "voice_id": "000000000000"},
])
def test_speak_rejects(monkeypatch, body):
    monkeypatch.setattr(cloning_engine, "synthesize", lambda *a: wav_bytes(1))
    assert client.post("/api/tools/speak", json=body).status_code == 422


# --- results -------------------------------------------------------------------------------


def test_old_results_are_cleaned_up(monkeypatch, isolated_data_dir):
    monkeypatch.setattr(cloning_engine, "synthesize", lambda *a: wav_bytes(1))
    first = client.post("/api/tools/speak", json={"text": "Hi"}).json()["url"]
    old = isolated_data_dir / "tools" / (first.rsplit("/", 1)[1] + ".wav")
    os.utime(old, (time.time() - 2 * 86400,) * 2)
    client.post("/api/tools/speak", json={"text": "Hi again"})
    assert not old.exists()


@pytest.mark.parametrize("bad", ["0" * 32, "..", "%2e%2e%2fsecret"])
def test_unknown_results(bad):
    assert client.get(f"/api/tools/audio/{bad}").status_code in (404, 405)


# --- Convert video ---------------------------------------------------------------------------------

from voxwell.features.dubbing.ffmpeg import DubbingError  # noqa: E402
from voxwell.features.tools import router as tools_router  # noqa: E402


def stereo_wav(seconds: float, level: float = 0.1, rate: int = 44100) -> bytes:
    import numpy as np
    import soundfile as sf

    t = np.arange(int(seconds * rate)) / rate
    tone = (level * np.sin(2 * np.pi * 220 * t)).astype("float32")
    buf = io.BytesIO()
    sf.write(buf, np.stack([tone, tone], axis=1), rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


@pytest.fixture
def fake_video(monkeypatch):
    """Everything around the models faked: a 2 s video with sound, isolation and conversion."""
    calls = {"convert": [], "isolate": 0, "rebuild": 0}
    monkeypatch.setattr(engine, "video_streams", lambda path: (0, True))
    monkeypatch.setattr(engine, "extract_soundtrack", lambda video, out, limit: out.write_bytes(stereo_wav(2)))

    def fake_isolate(source, voice_out, background_out):
        calls["isolate"] += 1
        voice_out.write_bytes(stereo_wav(2, 0.2))
        background_out.write_bytes(stereo_wav(2, 0.05))
        return 2.0

    def fake_convert(source, target):
        calls["convert"].append(duration(source.read_bytes()))
        return wav_bytes(duration(source.read_bytes()), 24000)

    def fake_rebuild(video, track, out, picture):
        calls["rebuild"] += 1
        out.write_bytes(b"an mp4")

    monkeypatch.setattr(isolation, "isolate", fake_isolate)
    monkeypatch.setattr(engine, "convert", fake_convert)
    monkeypatch.setattr(engine, "rebuild_video", fake_rebuild)
    return calls


def convert_video(voice_id, data=b"\x00\x00\x00\x18ftypmp42 a video"):
    return client.post("/api/tools/convert-video", files={"file": ("clip.mp4", data)}, data={"voice_id": voice_id})


def test_piece_bounds_cut_long_speech_in_its_quiet_moments():
    import numpy as np

    rate = 1000
    track = np.ones(60 * rate, dtype="float32")
    for gap in (22, 44):  # a quiet moment in the last 5 s of each 25 s stretch
        track[gap * rate : gap * rate + 100] = 0
    bounds = engine.piece_bounds(track, rate)
    assert len(bounds) == 3 and all(end - start <= 25 * rate for start, end in bounds)
    assert bounds[0][0] == 0 and bounds[-1][1] == len(track)
    assert all(a[1] == b[0] for a, b in zip(bounds, bounds[1:]))  # nothing lost or repeated
    assert all(track[start] == 0 for start, _ in bounds[1:])  # every cut is in a quiet moment
    assert engine.piece_bounds(np.ones(20 * rate), rate) == [(0, 20 * rate)]
    assert engine.piece_bounds(np.ones(25 * rate), rate) == [(0, 25 * rate)]


def test_mixing_keeps_the_background_level_and_never_clips(tmp_path):
    import numpy as np
    import soundfile as sf

    bed = tmp_path / "bed.wav"
    bed.write_bytes(stereo_wav(1, 0.1))
    out = tmp_path / "mix.wav"
    engine.mix_voice(bed, np.zeros(24000, dtype="float32"), 24000, out)
    mixed, rate = sf.read(str(out), dtype="float32")
    original, _ = sf.read(str(bed), dtype="float32")
    assert rate == 44100 and mixed.shape == original.shape
    assert abs(20 * np.log10(np.abs(mixed).max() / np.abs(original).max())) < 1
    engine.mix_voice(bed, np.ones(24000, dtype="float32"), 24000, out)
    assert np.abs(sf.read(str(out), dtype="float32")[0]).max() <= engine.MIX_CEILING + 1e-3
    # A loud voice doesn't turn the background down where the voice is silent.
    voice = np.zeros(44100, dtype="float32")
    voice[:4410] = 1.0
    engine.mix_voice(bed, voice, 44100, out)
    tail = sf.read(str(out), dtype="float32")[0][22050:]
    np.testing.assert_allclose(tail, original[22050:], atol=1e-3)


def test_convert_video_swaps_the_voice_and_keeps_the_picture(fake_video):
    voice = voices.save_voice("Target", wav_bytes(1), "upload")
    r = convert_video(voice.id)
    body = r.json()
    assert r.status_code == 200, body
    assert body["notes"] == [] and body["video_url"].startswith("/api/tools/video/")
    assert client.get(body["video_url"]).content == b"an mp4"
    assert duration(client.get(body["url"]).content) == pytest.approx(2, abs=0.01)
    assert fake_video["convert"] == [pytest.approx(2, abs=0.01)]  # a short track is one call, like Convert voice


def test_without_isolation_the_whole_soundtrack_is_converted(fake_video, monkeypatch):
    def offline(*a):
        raise isolation.IsolationError("Could not download the voice isolation model: offline")

    monkeypatch.setattr(isolation, "isolate", offline)
    body = convert_video(voices.save_voice("Target", wav_bytes(1), "upload").id).json()
    assert body["notes"] == [tools_router.NOTE_WHOLE_SOUNDTRACK] and body["video_url"]
    assert len(fake_video["convert"]) == 1


@pytest.mark.parametrize("error", [DubbingError("ffmpeg could not process the file; see the Voxwell log."), OSError("disk full")])
def test_a_video_that_cannot_be_rebuilt_comes_back_as_audio(fake_video, monkeypatch, error):
    def cannot(*a):
        raise error

    monkeypatch.setattr(engine, "rebuild_video", cannot)
    body = convert_video(voices.save_voice("Target", wav_bytes(1), "upload").id).json()
    assert body["video_url"] is None and body["notes"] == [tools_router.NOTE_AUDIO_ONLY]
    assert duration(client.get(body["url"]).content) > 0


def test_convert_video_refusals(fake_video, monkeypatch):
    voice = voices.save_voice("Target", wav_bytes(1), "upload").id
    assert convert_video("000000000000").json() == {"detail": "Pick a saved voice."}
    monkeypatch.setattr(engine, "video_streams", lambda path: (None, True))
    assert convert_video(voice).json()["detail"] == "This file has no video picture. Use Convert voice for audio files."
    monkeypatch.setattr(engine, "video_streams", lambda path: (0, False))
    assert convert_video(voice).json()["detail"] == "This video has no audio track to convert."
    monkeypatch.setattr(engine, "video_streams", lambda path: (0, True))
    monkeypatch.setattr(tools_router, "MAX_ISOLATE_SECONDS", 1)
    assert convert_video(voice).json()["detail"] == "Use a video of up to 0 minutes."
    monkeypatch.setattr(tools_router, "MAX_ISOLATE_SECONDS", 600)
    monkeypatch.setattr(isolation, "isolate", lambda s, v, b: (v.write_bytes(stereo_wav(2, 0)), b.write_bytes(stereo_wav(2, 0))))
    r = convert_video(voice)
    assert (r.status_code, r.json()["detail"]) == (422, "No speech was found, so there is nothing to convert.")
    monkeypatch.setattr(tools_router, "MAX_VIDEO_UPLOAD", 10)
    assert convert_video(voice, b"\x00" * 100).status_code == 413


def test_text_is_never_read_as_a_video(fake_video, monkeypatch, tmp_path):
    monkeypatch.undo()  # the real stream check
    secret = tmp_path / "secret.ts"
    secret.write_bytes(b"\x00" * 10)
    playlist = f"#EXTM3U\n#EXTINF:1,\n{secret}\n#EXT-X-ENDLIST\n".encode()
    voice = voices.save_voice("Target", wav_bytes(1), "upload").id
    for data in (playlist, b"ffconcat version 1.0\nfile 'x.mp4'\n", b""):
        r = convert_video(voice, data)
        assert (r.status_code, r.json()["detail"]) == (422, engine.NOT_A_VIDEO)


def test_a_conversion_error_is_a_plain_500(fake_video, monkeypatch):
    def boom(*a):
        raise RuntimeError("weights at C:/secret")

    monkeypatch.setattr(engine, "convert", boom)
    r = convert_video(voices.save_voice("Target", wav_bytes(1), "upload").id)
    assert r.status_code == 500 and r.json()["detail"] == "Voice conversion failed; see the Voxwell log."


def test_old_videos_are_cleaned_up(fake_video, isolated_data_dir):
    old = isolated_data_dir / "tools" / ("a" * 32 + ".mp4")
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_bytes(b"old")
    os.utime(old, (time.time() - 2 * 86400,) * 2)
    convert_video(voices.save_voice("Target", wav_bytes(1), "upload").id)
    assert not old.exists()


@pytest.mark.parametrize("bad", ["0" * 32, "..", "%2e%2e%2fsecret"])
def test_unknown_videos(bad):
    assert client.get(f"/api/tools/video/{bad}").status_code in (404, 405)


@needs_ffmpeg
def test_convert_video_with_real_ffmpeg(monkeypatch, tmp_path):
    video = tmp_path / "talk.mp4"
    subprocess.run([shutil.which("ffmpeg"), "-loglevel", "error", "-f", "lavfi", "-i", "color=s=160x120:d=2:r=10",
                    "-f", "lavfi", "-i", "sine=frequency=300:duration=2", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video)], check=True)

    def fake_isolate(source, voice_out, background_out):
        data = source.read_bytes()
        voice_out.write_bytes(data)
        background_out.write_bytes(data)
        return 2.0

    monkeypatch.setattr(isolation, "isolate", fake_isolate)
    monkeypatch.setattr(engine, "convert", lambda source, target: wav_bytes(duration(source.read_bytes()), 24000))
    body = convert_video(voices.save_voice("Target", wav_bytes(1), "upload").id, video.read_bytes()).json()
    assert body["notes"] == [] and body["video_url"]
    out = tmp_path / "out.mp4"
    out.write_bytes(client.get(body["video_url"]).content)
    streams = engine.probe(out)["streams"]
    assert [s["type"] for s in streams] == ["video", "audio"] and "AAC" in streams[1]["codec"]
    audio_only = tmp_path / "a.wav"
    audio_only.write_bytes(wav_bytes(1))
    r = convert_video(voices.save_voice("Other", wav_bytes(1), "upload").id, audio_only.read_bytes())
    assert r.json()["detail"] == "This file has no video picture. Use Convert voice for audio files."
