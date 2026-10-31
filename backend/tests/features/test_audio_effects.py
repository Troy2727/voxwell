import io
import json
import math
import wave

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from voxwell import cli
from voxwell.features.audio_effects import dsp
from voxwell.features.audio_effects.dsp import CEILING, Effects
from voxwell.features.integrations import mcp_server
from voxwell.features.stories import jobs
from voxwell.features.voice_cloning import engine
from voxwell.main import app

client = TestClient(app, base_url="http://127.0.0.1")
RATE = 16000


def speechlike(seconds=1.0, amplitude=0.3, tail=0.0):
    """A voiced, wobbling harmonic tone (plus `tail` seconds of silence): enough structure to measure."""
    t = np.arange(int(seconds * RATE)) / RATE
    f0 = 140 + 20 * np.sin(2 * math.pi * 3 * t)
    phase = 2 * math.pi * np.cumsum(f0) / RATE
    x = sum(np.sin(h * phase) / h for h in range(1, 12)) * (0.6 + 0.4 * np.sin(2 * math.pi * 4 * t))
    x = amplitude * x / np.max(np.abs(x))
    return np.concatenate([x, np.zeros(int(tail * RATE))])


def rms(x):
    return float(np.sqrt(np.mean(np.square(x))))


def centroid(x, rate=RATE):
    spectrum = np.abs(np.fft.rfft(x))
    return float(np.sum(np.fft.rfftfreq(len(x), 1 / rate) * spectrum) / np.sum(spectrum))


def wav_bytes(samples, rate=RATE):
    buf = io.BytesIO()
    sf.write(buf, samples, rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


# --- DSP ---------------------------------------------------------------------------------------


def test_neutral_settings_return_the_input_unchanged():
    x = speechlike()
    assert Effects().is_neutral
    assert dsp.process(x, RATE, Effects()) is x
    wav = wav_bytes(x)
    assert dsp.apply_to_wav(wav, Effects()) == wav


def test_reverb_adds_a_tail_and_keeps_the_voice():
    x = speechlike(1.0)
    y = dsp.process(x, RATE, Effects(reverb=1.0))
    assert y.ndim == 1 and len(y) > len(x)
    assert rms(y[len(x):]) > 0.01 * rms(x)  # energy after the voice ended
    more = dsp.process(x, RATE, Effects(reverb=0.3))
    assert rms(y[len(x):]) > rms(more[len(x):]) > 0


def test_reverb_is_deterministic():
    x = speechlike()
    assert np.array_equal(dsp.process(x, RATE, Effects(reverb=0.5)), dsp.process(x, RATE, Effects(reverb=0.5)))


def test_distance_is_duller_and_quieter():
    x = speechlike(1.0)
    near, far = dsp.process(x, RATE, Effects(distance=0.05))[: len(x)], dsp.process(x, RATE, Effects(distance=1.0))[: len(x)]
    assert centroid(far) < 0.8 * centroid(near) < centroid(x) * 1.01
    assert rms(far) < 0.5 * rms(x)


def test_distance_adds_reverberation():
    x = speechlike(1.0)
    y = dsp.process(x, RATE, Effects(distance=1.0))
    assert len(y) > len(x) and rms(y[len(x):]) > 0


def test_noise_bed_fills_silence_deterministically():
    x = speechlike(0.5, tail=0.5)
    y = dsp.process(x, RATE, Effects(noise=0.5))
    assert len(y) == len(x)
    assert rms(y[-RATE // 4:]) > 0 and rms(x[-RATE // 4:]) == 0
    assert np.array_equal(y, dsp.process(x, RATE, Effects(noise=0.5)))
    louder = dsp.process(x, RATE, Effects(noise=1.0))
    assert rms(louder[-RATE // 4:]) > 3 * rms(y[-RATE // 4:])
    assert rms(louder[-RATE // 4:]) < rms(x[: RATE // 2])  # still under the voice


def test_brown_noise_is_darker_than_pink():
    silence = np.zeros(RATE * 2)
    silence[:100] = 0.1  # something to scale the noise against
    pink = dsp.process(silence, RATE, Effects(noise=1.0, noise_color="pink"))[RATE:]
    brown = dsp.process(silence, RATE, Effects(noise=1.0, noise_color="brown"))[RATE:]
    assert centroid(brown) < centroid(pink)


def test_pan_makes_constant_power_stereo():
    x = speechlike()
    left, right = dsp.process(x, RATE, Effects(pan=-1.0)), dsp.process(x, RATE, Effects(pan=1.0))
    mid = dsp.process(x, RATE, Effects(pan=0.5))
    assert left.shape == right.shape == mid.shape == (len(x), 2)
    assert rms(left[:, 0]) > 100 * rms(left[:, 1])
    assert rms(right[:, 1]) > 100 * rms(right[:, 0])
    assert rms(mid[:, 1]) > rms(mid[:, 0]) > 0
    for pan in (-1.0, -0.4, 0.3, 1.0):
        y = dsp.process(x, RATE, Effects(pan=pan))
        assert np.sum(y**2) == pytest.approx(np.sum(x**2), rel=1e-6)


def test_stereo_input_is_kept_stereo_for_other_effects():
    x = np.stack([speechlike(), speechlike() * 0.5], axis=1)
    y = dsp.process(x, RATE, Effects(distance=0.5))
    assert y.ndim == 2 and y.shape[1] == 2 and len(y) > len(x)


def test_output_never_clips():
    x = speechlike(1.0, amplitude=1.0)
    for fx in (Effects(reverb=1.0), Effects(noise=1.0), Effects(pan=0.2), Effects(reverb=1.0, distance=0.0, noise=1.0, pan=-0.7)):
        assert np.max(np.abs(dsp.process(x, RATE, fx))) <= CEILING + 1e-9
    out, _ = sf.read(io.BytesIO(dsp.apply_to_wav(wav_bytes(x), Effects(reverb=1.0, noise=1.0))), dtype="int16")
    assert np.max(np.abs(out.astype(int))) < 32767


@pytest.mark.parametrize("bad", [{"reverb": 1.5}, {"distance": -0.1}, {"noise": 2}, {"pan": 1.1}, {"noise_color": "blue"}])
def test_invalid_settings_are_rejected(bad):
    with pytest.raises(ValueError):
        Effects(**bad)


# --- synthesize() ------------------------------------------------------------------------------


@pytest.fixture
def model(monkeypatch):
    class Model:
        sr = 24000

        def generate(self, text, **kwargs):
            return speechlike(0.5).astype("float32")

    monkeypatch.setattr(engine, "_load_model", lambda: Model())


def test_default_output_is_byte_identical(model):
    plain = engine.synthesize("Hello", "en")
    assert engine.synthesize("Hello", "en", effects=None) == plain
    assert engine.synthesize("Hello", "en", effects=Effects()) == plain
    assert engine.synthesize("Hello", "en", effects=Effects(reverb=0.5)) != plain


def test_synthesize_pans_to_stereo(model):
    data, _ = sf.read(io.BytesIO(engine.synthesize("Hello", "en", effects=Effects(pan=-1))))
    assert data.ndim == 2 and rms(data[:, 0]) > 10 * rms(data[:, 1])


# --- API ---------------------------------------------------------------------------------------


def test_voice_cloning_passes_effects_only_when_asked(monkeypatch):
    calls = []

    def fake(text, language, reference_audio=None, **kwargs):
        calls.append(kwargs)
        return wav_bytes(speechlike(0.2))

    monkeypatch.setattr(engine, "synthesize", fake)
    assert client.post("/api/voice_cloning/synthesize", json={"text": "Hi"}).status_code == 200
    r = client.post("/api/voice_cloning/synthesize", json={"text": "Hi", "effects": {"reverb": 0.4, "pan": -0.5}})
    assert r.status_code == 200
    assert calls[0] == {} and calls[1]["effects"] == Effects(reverb=0.4, pan=-0.5)
    assert client.post("/api/voice_cloning/synthesize", json={"text": "Hi", "effects": {"reverb": 3}}).status_code == 422


def test_stories_apply_effects_to_the_finished_audio(monkeypatch):
    monkeypatch.setattr(engine, "synthesize", lambda text, language, reference_audio=None: wav_bytes(speechlike(0.3)))
    monkeypatch.setattr(jobs, "start", jobs._work)  # run synchronously

    def story(**body):
        job_id = client.post("/api/stories/jobs", json={"script": "Anna: Hi there", "language": "en", **body}).json()["id"]
        return sf.read(io.BytesIO(client.get(f"/api/stories/jobs/{job_id}/audio").content))[0]

    plain, panned = story(), story(effects={"pan": 1.0})
    assert plain.ndim == 1 and panned.shape == (len(plain), 2)
    assert rms(panned[:, 1]) > 10 * rms(panned[:, 0])


def apply(samples=None, fields=None, data=None, name="a.wav"):
    data = data if data is not None else wav_bytes(speechlike() if samples is None else samples)
    return client.post("/api/audio_effects/apply", data=fields or {}, files={"file": (name, data, "audio/wav")})


def fetch(response):
    assert response.status_code == 200, response.text
    audio = client.get(response.json()["url"])
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/wav"
    return sf.read(io.BytesIO(audio.content), dtype="float64")


def test_upload_path_applies_effects():
    x = speechlike()
    plain, rate = fetch(apply(x))
    assert rate == RATE and plain.ndim == 1 and len(plain) == len(x)
    wet, _ = fetch(apply(x, {"reverb": "1"}))
    assert len(wet) > len(x)
    panned, _ = fetch(apply(x, {"pan": "-1"}))
    assert panned.shape == (len(x), 2) and rms(panned[:, 0]) > 10 * rms(panned[:, 1])
    brown, _ = fetch(apply(x, {"noise": "0.8", "noise_color": "brown"}))
    assert rms(brown - plain) > 0


def test_upload_processing_runs_off_the_event_loop(monkeypatch):
    # Decoding and DSP on a long file take seconds; on the loop they would stall every request.
    import asyncio

    from voxwell.features.audio_effects import router as fx_router

    on_loop = []

    def probe(fn):
        def wrapped(*args, **kwargs):
            try:
                asyncio.get_running_loop()
                on_loop.append(fn.__name__)
            except RuntimeError:
                pass
            return fn(*args, **kwargs)

        return wrapped

    for name in ("decode", "process", "encode_wav"):
        monkeypatch.setattr(fx_router.dsp, name, probe(getattr(dsp, name)))
    fetch(apply(speechlike(), {"reverb": "1"}))
    assert on_loop == []


def test_upload_errors():
    assert apply(data=b"not audio").status_code == 422
    assert apply(fields={"reverb": "2"}).status_code == 422
    assert apply(fields={"noise_color": "blue"}).status_code == 422
    assert client.get("/api/audio_effects/audio/nope").status_code == 404
    assert client.get("/api/audio_effects/audio/" + "0" * 32).status_code == 404


# --- CLI and MCP -------------------------------------------------------------------------------


class AppClient(cli.Client):
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


def test_cli_effects(capsys, tmp_path):
    source = tmp_path / "talk.wav"
    source.write_bytes(wav_bytes(speechlike()))
    out = tmp_path / "out.wav"
    code = cli.main(["effects", str(source), "--pan", "1", "--reverb", "0.3", "-o", str(out), "--json"], client=AppClient())
    assert code == 0 and json.loads(capsys.readouterr().out)["path"] == str(out)
    audio, _ = sf.read(out)
    assert audio.ndim == 2
    assert cli.main(["effects", str(source), "--pan", "5"], client=AppClient()) == 1
    assert "pan" in capsys.readouterr().err


def test_mcp_apply_effects(monkeypatch, tmp_path):
    monkeypatch.setattr(mcp_server, "_client", AppClient)
    source, out = tmp_path / "talk.wav", tmp_path / "out.wav"
    source.write_bytes(wav_bytes(speechlike()))
    reply = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "apply_effects", "arguments": {"file_path": str(source), "reverb": 0.5, "output_path": str(out)}}})
    assert reply["result"]["isError"] is False and sf.read(out)[0].ndim == 1
    bad = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "apply_effects", "arguments": {"file_path": str(source), "pan": "left"}}})
    assert bad["result"]["isError"] is True
