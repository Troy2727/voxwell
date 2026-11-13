import pytest

from voxwell.features.agents import mood
from voxwell.features.tools import direction


@pytest.mark.parametrize("raw, expected", [
    ("calm", "calm"), ("Calm.", "calm"), ('"upbeat"', "upbeat"), ("I think warm, maybe calm", "warm"),
    ("", "neutral"), ("angry", "neutral"), (None, "neutral"), ("the calmness", "neutral"),
])
def test_parse_mood(raw, expected):
    assert mood.parse_mood(raw) == expected


def test_choose_mood_never_raises(monkeypatch):
    def broken(system, user, max_new_tokens=80):
        raise RuntimeError("model gone")

    monkeypatch.setattr(direction, "complete", broken)
    assert mood.choose_mood("hi there") == "neutral"


def test_choose_mood_skips_empty_text_and_cuts_long_text(monkeypatch):
    seen = []
    monkeypatch.setattr(direction, "complete", lambda system, user, max_new_tokens=80: seen.append(user) or "upbeat")
    assert mood.choose_mood("   ") == "neutral" and seen == []
    assert mood.choose_mood("x" * 1000 + ' """ escape') == "upbeat"
    assert seen[0].count("x") == mood.MAX_INPUT and seen[0].count('"""') == 2


def test_the_table_keeps_its_promises():
    neutral = mood.delivery_for("neutral")
    assert (neutral.exaggeration, neutral.cfg_weight, neutral.tempo) == (0.5, 0.5, 1.0)  # the engine's defaults
    d = {m: mood.delivery_for(m) for m in mood.MOODS}
    assert d["upbeat"].exaggeration > d["warm"].exaggeration > d["neutral"].exaggeration > d["calm"].exaggeration
    for x in d.values():
        assert 0.25 <= x.exaggeration <= 1.0 and 0 <= x.cfg_weight <= 1 and 0.85 <= x.tempo <= 1.15
    assert mood.delivery_for("nonsense") == neutral


def test_out_of_range_values_are_clamped(monkeypatch):
    monkeypatch.setitem(mood.TABLE, "upbeat", (1.0, "fast"))  # exaggeration 1.4 before clamping
    assert mood.delivery_for("upbeat").exaggeration == 1.0


def test_warm_up_runs_once_and_never_raises(monkeypatch):
    import threading

    from voxwell.features.audio_effects import dsp

    calls, done = [], threading.Event()

    def broken(wav, fx):
        calls.append(fx.speed)
        done.set()
        raise RuntimeError("no audio library")

    monkeypatch.setattr(dsp, "apply_to_wav", broken)
    monkeypatch.setattr(mood, "_warmed", threading.Event())
    mood.warm_up()
    mood.warm_up()
    assert done.wait(2)
    assert calls == [1.1]


def test_a_mood_matched_live_session_warms_up(monkeypatch):
    from fastapi.testclient import TestClient

    from voxwell.main import app

    warmed = []
    monkeypatch.setattr(mood, "warm_up", lambda: warmed.append(True))
    client = TestClient(app, base_url="http://127.0.0.1")
    agent = client.post("/api/agents/agents", json={"name": "M", "mood_match": True}).json()
    with client.websocket_connect(f"ws://127.0.0.1/api/agents/agents/{agent['id']}/live") as ws:
        ws.send_json({"type": "start", "config": {"stream_reply": True}})
        assert ws.receive_json()["type"] == "ready"
    assert warmed == [True]


def test_quotes_in_the_message_never_touch_the_fences(monkeypatch):
    seen = []
    monkeypatch.setattr(direction, "complete", lambda system, user, max_new_tokens=80: seen.append(user) or "calm")
    mood.choose_mood('say "hi"')
    assert seen[0] == "\"\"\"say 'hi'\"\"\""
