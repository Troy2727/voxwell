"""Free the GPU: the saved preference, and when the speech models move to system RAM and back."""

import inspect

import numpy as np
import pytest
from fastapi.testclient import TestClient

from voxwell.features.voice_cloning import engine, gpu
from voxwell.main import app
from voxwell.paths import data_dir

client = TestClient(app, base_url="http://127.0.0.1")


class Part:
    """One of a model's networks (or its voice conditionals): remembers where it was moved."""

    def __init__(self):
        self.device = "cuda"
        self.moves = []
        self.refuse = None  # a device this part can't move to, like a full GPU

    def to(self, device):
        if device == self.refuse:
            raise RuntimeError("CUDA out of memory")
        self.moves.append(device)
        self.device = device
        return self


class FakeModel:
    sr = 24000

    def __init__(self):
        self.device = "cuda"
        self.t3, self.s3gen, self.ve, self.conds = Part(), Part(), Part(), Part()
        self.voxwell_default_conds = self.conds
        self.spoken_on = []

    def generate(self, text, **kwargs):
        self.spoken_on.append(self.t3.device)
        return np.zeros(2400, dtype=np.float32)


class FakeTimer:
    def __init__(self, seconds, fn):
        self.seconds, self.fn, self.cancelled, self.daemon = seconds, fn, False, False

    def start(self):
        TIMERS.append(self)

    def cancel(self):
        self.cancelled = True


TIMERS: list[FakeTimer] = []


@pytest.fixture(autouse=True)
def no_real_timers(monkeypatch):
    TIMERS.clear()
    monkeypatch.setattr(gpu.threading, "Timer", FakeTimer)
    monkeypatch.setattr(gpu, "_timer", None)
    monkeypatch.setattr(gpu, "_empty_cache", lambda: None)


@pytest.fixture
def model(monkeypatch):
    m = FakeModel()
    monkeypatch.setattr(engine, "_model", m)
    monkeypatch.setattr(engine, "_turbo", None)
    monkeypatch.setattr(engine, "_load_model", lambda: m)
    return m


def moved_to_ram(m):
    return m.device == "cpu" and all(p.device == "cpu" for p in (m.t3, m.s3gen, m.ve, m.conds))


def test_off_by_default_and_reports_the_device(monkeypatch):
    monkeypatch.setattr(engine, "_pick_device", lambda: "cuda")
    assert client.get("/api/voice_cloning/free-the-gpu").json() == {"enabled": False, "device": "cuda"}
    monkeypatch.setattr(engine, "_pick_device", lambda: "cpu")
    assert client.get("/api/voice_cloning/free-the-gpu").json()["device"] == "cpu"

    def no_torch():
        raise ImportError("torch")

    monkeypatch.setattr(engine, "_pick_device", no_torch)
    assert client.get("/api/voice_cloning/free-the-gpu").json()["device"] == "cpu"


def test_saved_setting_reads_back_outside_the_history_folder():
    history = set(data_dir("voice_cloning").glob("*.json"))
    r = client.put("/api/voice_cloning/free-the-gpu", json={"enabled": True})
    assert r.status_code == 200 and r.json()["enabled"] is True
    assert client.get("/api/voice_cloning/free-the-gpu").json()["enabled"] is True
    assert (data_dir("free_the_gpu") / "config.json").exists()
    assert set(data_dir("voice_cloning").glob("*.json")) == history  # the history reads every *.json there
    for bad in ("yes", 1, None):
        assert client.put("/api/voice_cloning/free-the-gpu", json={"enabled": bad}).status_code == 422


def test_a_broken_file_reads_as_off():
    (data_dir("free_the_gpu") / "config.json").write_text("{not json", encoding="utf-8")
    assert gpu.enabled() is False
    (data_dir("free_the_gpu") / "config.json").write_text("[1]", encoding="utf-8")
    assert gpu.enabled() is False


def test_a_failed_save_is_a_plain_500(monkeypatch):
    def full(value):
        raise OSError("No space left on C:/Users/someone/secret")

    monkeypatch.setattr(gpu, "set_enabled", full)
    r = client.put("/api/voice_cloning/free-the-gpu", json={"enabled": True})
    assert r.status_code == 500 and r.json() == {"detail": "Couldn't save this setting."}


def test_an_idle_model_moves_to_system_ram_once(model):
    gpu.set_enabled(True)
    engine.synthesize("Hello there.", "en")
    assert model.device == "cuda"  # nothing moves straight after a take
    assert len(TIMERS) == 1 and TIMERS[0].seconds == gpu.IDLE_SECONDS
    TIMERS[0].fn()
    assert moved_to_ram(model) and model.voxwell_moved_from == "cuda"
    TIMERS[0].fn()
    assert model.t3.moves == ["cpu"]


def test_off_means_nothing_moves(model):
    engine.synthesize("Hello there.", "en")
    assert TIMERS == []
    gpu.fire()
    assert model.device == "cuda" and model.t3.moves == []


def test_nothing_moves_while_speech_work_runs_or_holds_the_model(model):
    gpu.set_enabled(True)
    with gpu.working():
        gpu.fire()
    assert model.t3.moves == []
    TIMERS.clear()
    with engine._lock:
        gpu.fire()
    assert model.t3.moves == []


def test_the_next_take_moves_it_back_before_speaking(model):
    gpu.set_enabled(True)
    engine.synthesize("Hello there.", "en")
    TIMERS[-1].fn()
    engine.synthesize("Hello again.", "en")
    assert model.spoken_on == ["cuda", "cuda"]
    assert model.device == "cuda" and not hasattr(model, "voxwell_moved_from")


def test_a_failed_move_back_still_speaks_on_the_processor(model):
    gpu.set_enabled(True)
    engine.synthesize("Hello there.", "en")
    TIMERS[-1].fn()
    model.s3gen.refuse = "cuda"  # graphics memory filled up meanwhile
    assert engine.synthesize("Hello again.", "en")
    assert model.spoken_on[-1] == "cpu" and moved_to_ram(model)
    assert model.voxwell_moved_from == "cuda"  # the next take tries again


def test_a_failed_move_to_ram_leaves_the_model_where_it_was(model):
    gpu.set_enabled(True)
    model.ve.refuse = "cpu"
    gpu.fire()
    assert model.device == "cuda" and model.t3.device == "cuda"
    assert not hasattr(model, "voxwell_moved_from")


def test_a_new_model_never_inherits_a_move(model, monkeypatch):
    gpu.set_enabled(True)
    gpu.fire()
    fresh = FakeModel()
    gpu.restore_if_needed(fresh)
    assert fresh.t3.moves == []


def test_back_to_back_takes_leave_one_countdown(model):
    gpu.set_enabled(True)
    engine.synthesize("One.", "en")
    engine.synthesize("Two.", "en")
    assert len([t for t in TIMERS if not t.cancelled]) == 1


def test_turning_it_off_cancels_a_pending_move(model):
    gpu.set_enabled(True)
    engine.synthesize("One.", "en")
    client.put("/api/voice_cloning/free-the-gpu", json={"enabled": False})
    assert all(t.cancelled for t in TIMERS)


def test_synthesize_keeps_its_signature():
    params = list(inspect.signature(engine.synthesize).parameters)
    assert params == ["text", "language", "reference_audio", "exaggeration", "cfg_weight", "effects", "cues"]
