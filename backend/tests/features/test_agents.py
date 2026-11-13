import base64
import io
import json
import math
import time
import wave
from array import array

import pytest
from fastapi.testclient import TestClient

from voxwell import voices
from voxwell.features.agents import conversation, language, store
from voxwell.features.agents.language import choose
from voxwell.features.agents.tools import ToolError, calculate
from voxwell.features.dictation import engine as stt
from voxwell.features.voice_cloning import engine as tts
from voxwell.main import app
from voxwell.paths import data_dir

client = TestClient(app, base_url="http://127.0.0.1")


def wav_bytes(seconds: float = 0.5, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x10\x00" * int(seconds * rate))
    return buf.getvalue()


@pytest.fixture
def llm(monkeypatch):
    """A scripted model: `llm.replies` are returned in turn; `llm.seen` holds each chat it was given."""

    class Fake:
        replies: list[str] = []
        seen: list[list[dict]] = []
        offered: list = []

        def __call__(self, messages, tools=None):
            self.seen.append([dict(m) for m in messages])
            self.offered.append(tools)
            return self.replies.pop(0) if self.replies else "Done."

    fake = Fake()
    fake.replies, fake.seen, fake.offered = [], [], []
    monkeypatch.setattr(conversation, "_chat", fake)
    monkeypatch.setattr(tts, "synthesize", lambda text, language, reference=None, **k: wav_bytes())
    return fake


def make_agent(**overrides):
    body = {"name": "Helper", "system_prompt": "You help.", "tools": ["calculator", "current_time"], **overrides}
    r = client.post("/api/agents/agents", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def chat(agent_id, message, **extra):
    return client.post(f"/api/agents/agents/{agent_id}/chat", json={"message": message, **extra})


# --- saved agents -----------------------------------------------------------------------------


def test_crud():
    voice = voices.save_voice("Anna", wav_bytes(), "upload")
    agent = make_agent(voice=voice.id, language="es", tools=["list_voices", "calculator", "calculator"])
    assert agent["tools"] == ["calculator", "list_voices"]  # allowlist order, no duplicates
    assert (data_dir("agents") / f"{agent['id']}.json").exists()
    assert client.get("/api/agents/agents").json() == [agent]
    r = client.put(f"/api/agents/agents/{agent['id']}", json={**agent, "name": "Renamed", "tools": []})
    assert r.json()["name"] == "Renamed" and client.get(f"/api/agents/agents/{agent['id']}").json()["tools"] == []
    assert client.delete(f"/api/agents/agents/{agent['id']}").status_code == 200
    assert client.get("/api/agents/agents").json() == []
    assert client.get(f"/api/agents/agents/{agent['id']}").status_code == 404


@pytest.mark.parametrize(
    "body, message",
    [
        ({"name": " "}, "name"),
        ({"name": "x", "language": "ja"}, "Unsupported language"),
        ({"name": "x", "voice": "0123456789ab"}, "Unknown voice"),
        ({"name": "x", "tools": ["shell"]}, "Unknown tool 'shell'"),
        ({"name": "x", "system_prompt": "x" * 5000}, "too long"),
    ],
)
def test_invalid_agents_are_refused(body, message):
    r = client.post("/api/agents/agents", json=body)
    assert r.status_code == 422 and message in r.json()["detail"]


def test_ids_are_checked():
    assert client.get("/api/agents/agents/..%2F..%2Fsecret").status_code == 404
    assert client.delete("/api/agents/agents/0123456789ab").status_code == 404


# --- tool-call parsing ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reply, call",
    [
        ('{"tool": "calculator", "arguments": {"expression": "2+2"}}', {"tool": "calculator", "arguments": {"expression": "2+2"}}),
        ('Let me check.\n```json\n{"tool": "current_time", "arguments": {}}\n```', {"tool": "current_time", "arguments": {}}),
        ('{"tool": "lookup", "arguments": {"filter": {"tags": ["a", {"b": [1, 2]}]}, "text": "a } brace"}}',
         {"tool": "lookup", "arguments": {"filter": {"tags": ["a", {"b": [1, 2]}]}, "text": "a } brace"}}),
        ('{"note": {"x": 1}} then {"tool": "current_time"}', {"tool": "current_time", "arguments": {}}),
        # The model's own format (Qwen2.5): a <tool_call> block naming the tool with "name".
        ('<tool_call>\n{"name": "calculator", "arguments": {"expression": "17 * 23"}}\n</tool_call>',
         {"tool": "calculator", "arguments": {"expression": "17 * 23"}}),
    ],
)
def test_tool_calls_are_found(reply, call):
    assert conversation.parse_tool_call(reply) == (call, None)


def test_plain_answers_are_not_tool_calls():
    assert conversation.parse_tool_call("It is sunny. {not json} Have a nice day.") == (None, None)
    assert conversation.parse_tool_call('Here is data: {"a": 1}') == (None, None)
    assert conversation.parse_tool_call('My cat: {"name": "Tom"}') == (None, None)


@pytest.mark.parametrize("reply", ['{"tool": "calculator", "arguments": {"expression": "2+2"}', '{"tool": 5}'])
def test_malformed_tool_calls_are_reported(reply):
    call, problem = conversation.parse_tool_call(reply)
    assert call is None and problem


# --- calculator safety -------------------------------------------------------------------------------


@pytest.mark.parametrize("expression, result", [("2 + 3 * 4", "14"), ("(1 + 2) ** 3", "27"), ("7 / 2", "3.5"), ("2^10", "1024"),
                                                ("-5 // 2", "-3"), ("10 % 4", "2"), ("1.5 * 4", "6")])
def test_calculator(expression, result):
    assert calculate(expression) == result


@pytest.mark.parametrize(
    "expression",
    [
        "9 ** 9 ** 9 ** 9", "2 ** 100000", "(10 ** 600) * (10 ** 700)", "10 ** 1e6", "1e308 * 1e308",
        "__import__('os').system('echo hi')", "x + 1", "(1).real", "abs(-1)", "[1, 2]", "'a' * 3", "True + 1",
        "1 / 0", "(-8) ** 0.5", "lambda: 1", "1 if 1 else 2", "1; 2", "+".join("1" * 200),
    ],
)
def test_calculator_refuses_unsafe_or_huge_input_fast(expression):
    start = time.perf_counter()
    with pytest.raises(ToolError):
        calculate(expression)
    assert time.perf_counter() - start < 0.5


# --- the conversation loop ---------------------------------------------------------------------------


def test_tool_call_then_answer(llm):
    agent = make_agent()
    llm.replies = ['{"tool": "calculator", "arguments": {"expression": "6 * 7"}}', "It is 42."]
    body = chat(agent["id"], "What is six times seven?").json()
    assert body["reply"] == "It is 42." and base64.b64decode(body["audio"])[:4] == b"RIFF"
    assert body["tool_calls"] == [{"tool": "calculator", "arguments": {"expression": "6 * 7"}, "result": "42"}]
    assert llm.seen[1][-1] == {"role": "tool", "content": "42"}
    assert "You help." in llm.seen[0][0]["content"]


def test_tools_are_offered_in_the_models_own_format(llm):
    # Qwen2.5 follows tools passed to its chat template. A protocol described in the prompt was
    # ignored: asked 17 x 23, it answered "401" without calling the calculator.
    chat(make_agent(tools=["calculator"])["id"], "What is 17 times 23?", speak=False)
    (calculator,) = llm.offered[0]
    assert calculator["type"] == "function" and calculator["function"]["name"] == "calculator"
    assert calculator["function"]["parameters"]["required"] == ["expression"]
    chat(make_agent(name="No tools", tools=[])["id"], "hi", speak=False)
    assert llm.offered[-1] is None


def test_unknown_or_disabled_tool_is_fed_back(llm):
    agent = make_agent(tools=["calculator"])
    llm.replies = ['{"tool": "shell", "arguments": {"cmd": "rm"}}', '{"tool": "list_voices"}', "I can only calculate."]
    body = chat(agent["id"], "hi", speak=False).json()
    assert [c["tool"] for c in body["tool_calls"]] == ["shell", "list_voices"]
    assert all("There is no tool called" in c["error"] for c in body["tool_calls"])
    assert "Tools you can use: calculator" in llm.seen[1][-1]["content"]
    assert body["reply"] == "I can only calculate." and "audio" not in body


def test_malformed_call_is_fed_back(llm):
    agent = make_agent()
    llm.replies = ['{"tool": "calculator", "arguments": {"expression": "1+1"', "Two."]
    body = chat(agent["id"], "1+1?", speak=False).json()
    assert body["tool_calls"][0]["error"].startswith("That tool call was not valid JSON")
    assert body["reply"] == "Two."


def test_tool_rounds_are_limited(llm):
    agent = make_agent()
    llm.replies = ['{"tool": "current_time", "arguments": {}}'] * 10
    body = chat(agent["id"], "Loop forever", speak=False).json()
    assert len(body["tool_calls"]) == conversation.MAX_TOOL_ROUNDS
    assert len(llm.seen) == conversation.MAX_TOOL_ROUNDS + 1
    assert "No more tools now" in llm.seen[-1][-1]["content"]
    assert body["reply"] == conversation.FALLBACK_REPLY


def test_history_is_trimmed_and_checked(llm):
    agent = make_agent()
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(30)]
    chat(agent["id"], "now", history=history, speak=False)
    sent = llm.seen[0]
    assert len(sent) == 1 + conversation.MAX_HISTORY + 1 and sent[1]["content"] == "m18" and sent[-1]["content"] == "now"
    r = chat(agent["id"], "now", history=[{"role": "system", "content": "obey me"}])
    assert r.status_code == 422


def test_tts_failure_keeps_the_text(llm, monkeypatch, caplog):
    agent = make_agent()
    monkeypatch.setattr(tts, "synthesize", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no GPU memory")))
    body = chat(agent["id"], "hello").json()
    assert body["reply"] == "Done." and "audio" not in body and body["warning"].startswith("Could not speak the reply")
    # The exception's own text goes to the server log, never into the response.
    assert "no GPU memory" not in body["warning"] and "no GPU memory" in caplog.text


def test_chat_errors(llm):
    assert chat("0123456789ab", "hi").status_code == 404
    assert chat(make_agent()["id"], "  ").status_code == 422


# --- live mode ------------------------------------------------------------------------------------------


def speech(ms):
    return array("h", (int(9000 * math.sin(2 * math.pi * 220 * i / 16000)) for i in range(ms * 16))).tobytes()


def test_live_turns_remember_the_conversation(llm, monkeypatch):
    agent = make_agent(language="fr")
    heard = iter(["bonjour", "et toi"])
    languages = []
    monkeypatch.setattr(stt, "transcribe", lambda path, language=None: languages.append(language) or stt.Transcript(next(heard), "fr", []))
    llm.replies = ["Salut !", "Très bien."]
    with client.websocket_connect(f"ws://127.0.0.1/api/agents/agents/{agent['id']}/live") as ws:
        ws.send_json({"type": "start", "config": {"silence_ms": 400, "history": [{"role": "assistant", "content": "Allô"}]}})
        assert ws.receive_json()["type"] == "ready"
        for _ in range(2):
            ws.send_bytes(speech(600) + bytes(500 * 32))
        ws.send_json({"type": "end"})
        turns = []
        while (m := ws.receive_json())["type"] != "done":
            if m["type"] == "turn":
                turns.append(m)
    assert [(t["transcript"], t["reply"]) for t in turns] == [("bonjour", "Salut !"), ("et toi", "Très bien.")]
    assert all(t["audio"] for t in turns) and languages == ["fr", "fr"]
    second = [m["content"] for m in llm.seen[1][1:]]
    assert second == ["Allô", "bonjour", "Salut !", "et toi"]


def test_live_unknown_agent():
    with client.websocket_connect("ws://127.0.0.1/api/agents/agents/0123456789ab/live") as ws:
        ws.send_json({"type": "start", "config": {}})
        m = ws.receive_json()
        assert m == {"type": "error", "message": "Unknown agent."}


def test_status_lists_the_allowlist():
    body = client.get("/api/agents/status").json()
    assert [t["name"] for t in body["tools"]] == ["current_time", "calculator", "list_voices"]
    assert "ja" not in body["languages"]


def test_store_never_uses_names_as_paths():
    agent = store.create(name="../../evil", system_prompt="", voice="", language="en", tools=[])
    assert [p.name for p in data_dir("agents").iterdir()] == [f"{agent.id}.json"]
    assert json.loads((data_dir("agents") / f"{agent.id}.json").read_text(encoding="utf-8"))["name"] == "../../evil"


def test_a_tool_that_crashes_reports_a_fixed_message(llm, monkeypatch, caplog):
    from voxwell.features.agents import tools

    def crash(name, arguments, allowed):
        raise RuntimeError("secret detail C:/Users/someone/file")

    monkeypatch.setattr(tools, "run", crash)
    llm.replies = ['{"tool": "calculator", "arguments": {"expression": "1+1"}}', "Sorry."]
    body = chat(make_agent()["id"], "add").json()
    assert body["tool_calls"][0]["error"] == "The tool failed."
    assert "secret detail" not in str(body) and "secret detail" in caplog.text


def test_an_agent_crash_returns_a_fixed_500(llm, monkeypatch, caplog):
    def crash(*args, **kwargs):
        raise RuntimeError("secret detail at C:/internal/path")

    monkeypatch.setattr(conversation, "reply_and_speak", crash)
    r = chat(make_agent()["id"], "hello")
    assert r.status_code == 500 and "secret detail" not in r.text and "secret detail" in caplog.text


# --- language follow ------------------------------------------------------------------------------

CLEAR = (0.9, 3.0, "hola, ¿qué tal?")  # confidence, seconds, text of a turn clear enough to switch on


# --- the decision -------------------------------------------------------------------------------


def test_a_clear_turn_in_an_allowed_language_switches():
    assert choose(["en", "es"], "en", "es", *CLEAR) == "es"
    assert choose(["en", "es"], "es", "en", 0.9, 3.0, "back to english") == "en"


@pytest.mark.parametrize("confidence, seconds, text", [(0.5, 3.0, "hola, ¿qué tal?"), (0.9, 0.8, "hola, ¿qué tal?"), (0.9, 3.0, "sí")])
def test_unclear_turns_never_switch(confidence, seconds, text):
    assert choose(["en", "es"], "en", "es", confidence, seconds, text) == "en"
    assert choose(["en", "es"], "es", "en", confidence, seconds, text) == "es"


def test_other_languages_and_empty_turns_keep_the_current_one():
    assert choose(["en", "es"], "es", "fr", *CLEAR) == "es"
    assert choose(["en", "es"], "es", "en", 0.9, 3.0, "") == "es"
    assert choose(["en", "es"], "es", "es", *CLEAR) == "es"


def test_without_follow_languages_the_primary_always_wins():
    assert choose(["en"], "en", "es", *CLEAR) == "en"


def test_short_turns_never_move_it():
    current, seen = "en", []
    for detected, seconds, text in [("es", 3.0, "hola, ¿qué tal?"), ("en", 0.6, "ok"), ("es", 0.6, "sí"), ("en", 3.0, "thanks a lot")]:
        current = choose(["en", "es"], current, detected, 0.9, seconds, text)
        seen.append(current)
    assert seen == ["es", "es", "es", "en"]


# --- the store ----------------------------------------------------------------------------------


def test_old_and_newer_agent_files_load():
    folder = data_dir("agents")
    old = {"id": "0123456789ab", "name": "Old", "system_prompt": "", "voice": "", "language": "en", "tools": []}
    (folder / "0123456789ab.json").write_text(json.dumps(old), encoding="utf-8")
    (folder / "ba9876543210.json").write_text(json.dumps({**old, "id": "ba9876543210", "name": "New", "mood": "x"}), encoding="utf-8")
    assert store.get("0123456789ab").follow_languages == []
    assert [a.name for a in store.list_agents()] == ["New", "Old"]


def test_follow_languages_are_checked_and_tidied():
    r = client.post("/api/agents/agents", json={"name": "x", "follow_languages": ["es", "es", "xx"]})
    assert r.status_code == 422 and "'xx'" in r.json()["detail"]
    assert client.post("/api/agents/agents", json={"name": "x", "follow_languages": ["ja"]}).status_code == 422
    assert make_agent(follow_languages=["fr", "es", "es"])["follow_languages"] == ["es", "fr"]
    assert make_agent(language="es", follow_languages=["es", "fr"])["follow_languages"] == ["fr"]


def test_follow_languages_round_trip():
    agent = make_agent(follow_languages=["es"])
    assert client.get(f"/api/agents/agents/{agent['id']}").json()["follow_languages"] == ["es"]
    body = {k: v for k, v in agent.items() if k not in ("id", "follow_languages")}
    assert client.put(f"/api/agents/agents/{agent['id']}", json=body).json()["follow_languages"] == []


# --- live and chat ------------------------------------------------------------------------------


@pytest.fixture
def heard(monkeypatch):
    """A scripted Whisper: `heard.script` holds (detected, probability, text) per call; `heard.asked` the languages asked for."""

    class Fake:
        script: list = []
        asked: list = []

        def __call__(self, path, language=None):
            self.asked.append(language)
            detected, probability, text = self.script.pop(0)
            return stt.Transcript(text, language or detected, [], 1.0 if language else probability)

    fake = Fake()
    fake.script, fake.asked = [], []
    monkeypatch.setattr(stt, "transcribe", fake)
    return fake


@pytest.fixture
def spoken(monkeypatch):
    """The language each synthesis was asked for."""
    languages = []
    monkeypatch.setattr(tts, "synthesize", lambda text, language, reference=None, **k: languages.append(language) or wav_bytes())
    return languages


def live(agent_id, turns_ms, config=None):
    with client.websocket_connect(f"ws://127.0.0.1/api/agents/agents/{agent_id}/live") as ws:
        ws.send_json({"type": "start", "config": {"silence_ms": 400, **(config or {})}})
        assert ws.receive_json()["type"] == "ready"
        for ms in turns_ms:
            audio = speech(ms) + bytes(500 * 32)
            for i in range(0, len(audio), 32000):  # one message holds at most 2 s
                ws.send_bytes(audio[i : i + 32000])
        ws.send_json({"type": "end"})
        turns = []
        while (m := ws.receive_json())["type"] != "done":
            if m["type"] == "turn":
                turns.append(m)
    return turns


def test_live_without_follow_languages_stays_pinned(llm, heard, spoken):
    agent = make_agent(language="en")
    heard.script = [("fr", 0.99, "bonjour tout le monde")]
    [turn] = live(agent["id"], [2000])
    assert heard.asked == ["en"] and turn["language"] == "en" and spoken == ["en"]


def test_live_follows_a_clear_turn_in_the_same_voice(llm, heard, spoken):
    agent = make_agent(language="en", follow_languages=["es"])
    heard.script = [("es", 0.95, "hola, ¿cómo estás hoy?")]
    [turn] = live(agent["id"], [2000])
    assert heard.asked == [None] and turn["language"] == "es" and spoken == ["es"]
    assert "Spanish" in llm.seen[0][0]["content"]


def test_live_retranscribes_a_turn_it_does_not_follow(llm, heard, spoken):
    agent = make_agent(language="en", follow_languages=["es"])
    heard.script = [("fr", 0.95, "bonjour tout le monde"), ("en", 1.0, "bonjour tout le monde")]
    [turn] = live(agent["id"], [2000])
    assert heard.asked == [None, "en"] and turn["language"] == "en"


def test_live_short_turns_keep_the_language(llm, heard, spoken):
    agent = make_agent(language="en", follow_languages=["es"])
    heard.script = [("es", 0.95, "hola, ¿cómo estás hoy?"), ("en", 0.5, "ok"), ("es", 1.0, "ok"), ("en", 0.95, "thanks, that helps a lot")]
    turns = live(agent["id"], [2000, 600, 2000])
    assert [t["language"] for t in turns] == ["es", "es", "en"]


@pytest.mark.parametrize("start, expected", [("es", "es"), ("fr", "en"), ("xx", "en"), (5, "en")])
def test_live_session_starts_in_the_last_language(llm, heard, spoken, start, expected):
    agent = make_agent(language="en", follow_languages=["es"])
    heard.script = [("es", 0.4, "mmm vale"), (expected, 1.0, "mmm vale")] if expected == "en" else [("es", 0.4, "mmm vale")]
    [turn] = live(agent["id"], [2000], {"language": start})
    assert turn["language"] == expected


def test_chat_language(llm, spoken):
    agent = make_agent(language="en", follow_languages=["es"])
    r = chat(agent["id"], "hola", language="es")
    assert r.json()["language"] == "es" and spoken == ["es"] and "Spanish" in llm.seen[0][0]["content"]
    r = chat(agent["id"], "salut", language="fr")
    assert r.status_code == 422 and "en, es" in r.json()["detail"]
    assert chat(agent["id"], "hi").json()["language"] == "en"
    assert store.get(agent["id"]).follow_languages == ["es"]  # a switch never changes the saved agent


def test_allowed_puts_the_primary_first():
    assert language.allowed(store.Agent(id="x", name="x", system_prompt="", language="es", follow_languages=["en", "fr"])) == ["es", "en", "fr"]


def test_a_hand_edited_follow_list_repeating_the_primary_stays_off():
    agent = store.Agent(id="x", name="x", system_prompt="", language="en", follow_languages=["en", "en"])
    assert language.allowed(agent) == ["en"]


def test_live_an_empty_retranscription_keeps_the_turn(llm, heard, spoken):
    agent = make_agent(language="en", follow_languages=["es"])
    heard.script = [("fr", 0.95, "bonjour tout le monde"), ("en", 1.0, "")]
    [turn] = live(agent["id"], [2000])
    assert turn["transcript"] == "bonjour tout le monde" and turn["language"] == "en"


def test_allowed_ignores_languages_the_engine_does_not_speak():
    agent = store.Agent(id="x", name="x", system_prompt="", language="en", follow_languages=["ja", "es", "zz"])
    assert language.allowed(agent) == ["en", "es"]
