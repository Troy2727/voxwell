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
