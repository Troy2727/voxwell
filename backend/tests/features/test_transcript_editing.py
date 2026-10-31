import pytest
from fastapi.testclient import TestClient

from voxwell.features.dictation.engine import Segment, Transcript
from voxwell.features.dictation import engine
from voxwell.features.tools import direction
from voxwell.features.transcription import editing, jobs
from voxwell.main import app

client = TestClient(app, base_url="http://127.0.0.1")


def fake_model(monkeypatch, reply=lambda chunk: chunk.upper()):
    """Replace the language model: it sees 'Instruction: ...\n\nText:\n<chunk>' and returns reply(chunk)."""
    calls = []

    def complete(system, user, max_new_tokens=80):
        chunk = user.split("\n\nText:\n", 1)[1]
        calls.append((user.split("\n", 1)[0], chunk, max_new_tokens))
        return reply(chunk)

    monkeypatch.setattr(direction, "complete", complete)
    return calls


# --- chunking ------------------------------------------------------------------------------


def test_sentences_are_packed_up_to_the_limit():
    text = "One two. Three four. Five six."
    assert editing.chunk_paragraph(text, 100) == [text]
    assert editing.chunk_paragraph(text, 20) == ["One two. Three four.", "Five six."]


def test_exact_limit_fits_and_one_over_splits():
    assert editing.chunk_paragraph("a" * 10, 10) == ["a" * 10]
    assert editing.chunk_paragraph("aaaa bbbb. cc", 13) == ["aaaa bbbb. cc"]
    assert editing.chunk_paragraph("aaaa bbbb. cc", 12) == ["aaaa bbbb.", "cc"]


def test_one_huge_sentence_is_cut_at_spaces():
    sentence = " ".join(["word"] * 50)  # 249 characters, no sentence end
    chunks = editing.chunk_paragraph(sentence, 40)
    assert all(0 < len(c) <= 40 for c in chunks) and " ".join(chunks) == sentence


def test_one_huge_word_is_cut_mid_word():
    chunks = editing.chunk_paragraph("x" * 25, 10)
    assert chunks == ["x" * 10, "x" * 10, "x" * 5]


def test_empty_paragraphs_and_whitespace_make_no_chunks():
    assert editing.chunk_text("") == [] and editing.chunk_text(" \n\n \n \n\n\t") == []
    assert editing.chunk_text("A.\n\n\n\n  \n\nB.\r\n\r\nC.") == [["A."], ["B."], ["C."]]


def test_no_chunk_is_ever_empty():
    text = "Hi.  \n \n" + "Long sentence here. " * 30 + "\n\n...\n\n? !"
    assert all(chunk.strip() and len(chunk) <= 50 for p in editing.chunk_text(text, 50) for chunk in p)


# --- editing -------------------------------------------------------------------------------


def test_paragraph_breaks_are_kept(monkeypatch):
    calls = fake_model(monkeypatch)
    result = editing.edit_text("First one. Second one.\n\n\n\nThird.", "shout it")
    assert result.text == "FIRST ONE. SECOND ONE.\n\nTHIRD." and (result.chunks, result.kept) == (2, 0)
    assert calls[0][0] == "Instruction: shout it"


def test_long_text_is_sent_in_chunks_and_rejoined(monkeypatch):
    calls = fake_model(monkeypatch, reply=lambda c: c)
    text = " ".join(f"Sentence number {i}." for i in range(100))
    result = editing.edit_text(text, "x", limit=200)
    assert len(calls) == result.chunks > 5 and all(0 < len(c[1]) <= 200 for c in calls)
    assert result.text == text


def test_the_output_budget_fits_a_whole_chunk_in_any_script(monkeypatch):
    # CJK text is about one token per character; a budget of half the characters cut the
    # edited chunk short and silently dropped the rest of it.
    calls = fake_model(monkeypatch, reply=lambda c: c)
    chunk = "今天天气很好。" * 200
    editing.edit_text(chunk, "Fix punctuation")
    assert calls and all(budget >= len(c) for _, c, budget in calls)


@pytest.mark.parametrize("bad", ["", "   \n", "...", "```\n```", "x" * 1000])
def test_unusable_reply_keeps_the_original_chunk(monkeypatch, bad):
    fake_model(monkeypatch, reply=lambda c: bad)
    result = editing.edit_text("Keep me as I am.", "x")
    assert result.text == "Keep me as I am." and (result.chunks, result.kept) == (1, 1)


def test_only_the_failed_chunk_falls_back(monkeypatch):
    fake_model(monkeypatch, reply=lambda c: "" if "Bad" in c else c.lower())
    result = editing.edit_text("Good one.\n\nBad one.", "x")
    assert result.text == "good one.\n\nBad one." and result.kept == 1


def test_code_fences_are_stripped(monkeypatch):
    fake_model(monkeypatch, reply=lambda c: "```\nCleaned text.\n```")
    assert editing.edit_text("dirty text", "x").text == "Cleaned text."


def test_empty_input_never_calls_the_model(monkeypatch):
    calls = fake_model(monkeypatch)
    assert editing.edit_text(" \n\n ", "x").text == "" and calls == []


# --- API -----------------------------------------------------------------------------------


def post(**body):
    return client.post("/api/transcription/edit", json=body)


def test_presets_listed():
    presets = client.get("/api/transcription/edit/presets").json()
    assert {p["id"] for p in presets} == set(editing.PRESETS) and all(p["label"] and p["instruction"] for p in presets)


def test_edit_text_with_preset_and_instruction(monkeypatch):
    calls = fake_model(monkeypatch)
    r = post(text="um hello there", preset="filler")
    assert r.status_code == 200 and r.json() == {"text": "UM HELLO THERE", "chunks": 1, "kept": 0}
    assert editing.PRESETS["filler"][1] in calls[0][0]
    assert post(text="hello", instruction="  make   it\nrhyme ").status_code == 200
    assert calls[1][0] == "Instruction: make it rhyme"


def test_edit_a_finished_transcription(monkeypatch):
    fake_model(monkeypatch)
    monkeypatch.setattr(engine, "transcribe", lambda p, language=None, on_progress=None: Transcript("Hello there.", "en", [Segment(0, 1, "Hello there.")]))
    monkeypatch.setattr(jobs, "start", jobs._work)
    jid = client.post("/api/transcription/jobs", files={"file": ("a.mp3", b"x", "audio/mpeg")}).json()["id"]
    assert post(job_id=jid, preset="formal").json()["text"] == "HELLO THERE."


def test_edit_needs_a_finished_known_transcription(monkeypatch):
    fake_model(monkeypatch)
    assert post(job_id="000000000000", preset="filler").status_code == 404
    assert post(job_id="../x", preset="filler").status_code == 404
    monkeypatch.setattr(jobs, "start", lambda job: None)
    jid = client.post("/api/transcription/jobs", files={"file": ("a.mp3", b"x", "audio/mpeg")}).json()["id"]
    assert post(job_id=jid, preset="filler").status_code == 409


@pytest.mark.parametrize("body", [
    {}, {"preset": "filler"}, {"text": "a"}, {"text": "a", "job_id": "000000000000", "preset": "filler"},
    {"text": "a", "preset": "filler", "instruction": "b"}, {"text": "a", "preset": "nope"},
    {"text": "a", "instruction": "   "}, {"text": "a", "instruction": "x" * 501},
    {"text": "  \n ", "preset": "filler"}, {"text": "a" * 200_001, "preset": "filler"},
])
def test_bad_requests(monkeypatch, body):
    calls = fake_model(monkeypatch)
    assert post(**body).status_code == 422 and calls == []


def test_model_failure_is_a_clear_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("out of memory")

    monkeypatch.setattr(direction, "complete", boom)
    r = post(text="a", preset="filler")
    assert r.status_code == 500 and r.json()["detail"] == "The AI editor failed; see the Voxwell log."
