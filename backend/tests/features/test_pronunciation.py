import io
import json
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient

from voxwell import cli
from voxwell.features.integrations import mcp_server
from voxwell.features.pronunciation import store
from voxwell.features.pronunciation.store import Entry
from voxwell.features.voice_cloning import engine
from voxwell.main import app

client = TestClient(app, base_url="http://127.0.0.1")


def entry(word, respelling, case_sensitive=False, whole_word=True):
    return Entry("x", word, respelling, case_sensitive, whole_word)


def rewrite(text, *entries):
    return store.rewrite(text, list(entries))


# --- replacement rules -------------------------------------------------------------------------


def test_whole_word_is_the_default():
    assert rewrite("cat concat cats cat.", entry("cat", "kitty")) == "kitty concat cats kitty."


def test_partial_matches_inside_words():
    assert rewrite("concat cats", entry("cat", "kit", whole_word=False)) == "conkit kits"


def test_case_insensitive_by_default_and_case_sensitive_on_request():
    assert rewrite("Nguyen NGUYEN nguyen", entry("Nguyen", "win")) == "win win win"
    assert rewrite("Nguyen NGUYEN nguyen", entry("Nguyen", "win", case_sensitive=True)) == "win NGUYEN nguyen"


@pytest.mark.parametrize("text, expected", [
    ("(SQL)", "(sequel)"),
    ("SQL, SQL; SQL!", "sequel, sequel; sequel!"),
    ("\"SQL\" and 'SQL'", "\"sequel\" and 'sequel'"),
    ("SQL-based", "sequel-based"),
    ("NoSQL", "NoSQL"),
    ("SQL2", "SQL2"),
])
def test_punctuation_counts_as_a_boundary(text, expected):
    assert rewrite(text, entry("SQL", "sequel")) == expected


def test_words_with_symbols():
    assert rewrite("I like C++ and C#.", entry("C++", "see plus plus"), entry("C#", "see sharp")) == "I like see plus plus and see sharp."


def test_longest_match_wins():
    entries = [entry("New", "nu"), entry("New York", "noo york"), entry("New York City", "the big apple")]
    assert rewrite("New York City, New York, New Jersey", *entries) == "the big apple, noo york, nu Jersey"


def test_replacement_text_is_never_rewritten():
    assert rewrite("a b", entry("a", "b"), entry("b", "a")) == "b a"
    assert rewrite("cat", entry("cat", "cat cat")) == "cat cat"


def test_regex_characters_in_a_word_are_literal():
    assert rewrite("a.b axb", entry("a.b", "dot")) == "dot axb"


def test_unicode_words():
    assert rewrite("Zoë und Zoëtrope", entry("Zoë", "zo-ee")) == "zo-ee und Zoëtrope"


def test_no_entries_returns_the_text():
    assert store.apply("Hello there", "en") == "Hello there"


# --- the store ---------------------------------------------------------------------------------


def test_entries_are_per_language_and_persist(isolated_data_dir):
    store.add_entry("en", "Nguyen", "win")
    store.add_entry("es", "Nguyen", "nuyen")
    assert store.apply("Hi Nguyen", "en") == "Hi win"
    assert store.apply("Hola Nguyen", "es") == "Hola nuyen"
    assert (isolated_data_dir / "pronunciation" / "en.json").exists()
    assert not list((isolated_data_dir / "pronunciation").glob("*.tmp"))


def test_a_corrupt_file_is_treated_as_empty(isolated_data_dir):
    (isolated_data_dir / "pronunciation").mkdir()
    (isolated_data_dir / "pronunciation" / "en.json").write_text("{not json", encoding="utf-8")
    assert store.apply("Hello", "en") == "Hello"


def test_language_cannot_be_a_path():
    with pytest.raises(ValueError):
        store.list_entries("../evil")


# --- synthesize() ------------------------------------------------------------------------------


def test_synthesize_sends_the_rewritten_text_to_the_model(monkeypatch):
    seen = []

    class Model:
        sr = 24000

        def generate(self, text, **kwargs):
            seen.append((text, kwargs["language_id"]))
            return np.zeros(10, dtype="float32")

    monkeypatch.setattr(engine, "_load_model", lambda: Model())
    store.add_entry("en", "Nguyen", "win")
    assert engine.synthesize("Ask Nguyen.", "en")[:4] == b"RIFF"
    engine.synthesize("Ask Nguyen.", "es")  # another language's list does not apply
    assert seen == [("Ask win.", "en"), ("Ask Nguyen.", "es")]


def test_voice_design_speaks_the_rewritten_sample(monkeypatch):
    from voxwell.features.voice_design import engine as design_engine

    seen = []

    class Ids:
        def to(self, device):
            return self

    class Tok:
        def __call__(self, text, return_tensors):
            seen.append(text)
            return type("Enc", (), {"input_ids": Ids()})()

    class Model:
        config = type("Config", (), {"sampling_rate": 24000})()

        def generate(self, **kwargs):
            return type("Out", (), {"cpu": lambda self: self, "numpy": lambda self: np.zeros(10, dtype="float32")})()

    monkeypatch.setattr(design_engine, "_load", lambda: {"device": "cpu", "model": Model(), "tokenizer": Tok()})
    store.add_entry("en", "Nguyen", "win")
    assert design_engine.design("A calm voice.", "Ask Nguyen.")[:4] == b"RIFF"
    assert seen == ["A calm voice.", "Ask win."]


# --- API ---------------------------------------------------------------------------------------


def post(**body):
    return client.post("/api/pronunciation/entries", json={"word": "Nguyen", "respelling": "win", **body})


def test_crud():
    created = post()
    assert created.status_code == 200
    item = created.json()
    assert item["word"] == "Nguyen" and item["whole_word"] is True and item["case_sensitive"] is False
    assert client.get("/api/pronunciation/entries").json() == [item]
    assert client.get("/api/pronunciation/entries?language=es").json() == []

    updated = client.put(f"/api/pronunciation/entries/{item['id']}", json={
        "word": "Nguyen", "respelling": "nwin", "case_sensitive": True, "whole_word": False})
    assert updated.status_code == 200 and updated.json()["respelling"] == "nwin" and updated.json()["case_sensitive"] is True
    assert client.get("/api/pronunciation/entries").json()[0]["whole_word"] is False

    assert client.delete(f"/api/pronunciation/entries/{item['id']}").status_code == 200
    assert client.get("/api/pronunciation/entries").json() == []
    assert client.delete(f"/api/pronunciation/entries/{item['id']}").status_code == 404


def test_validation_and_duplicates():
    assert post(word="  ").status_code == 422
    assert post(respelling="").status_code == 422
    assert post(word="x" * 101).status_code == 422
    assert post(language="xx").status_code == 422
    assert post(language="../x").status_code == 422
    assert client.get("/api/pronunciation/entries?language=xx").status_code == 422
    assert post().status_code == 200
    assert post(word="nguyen").status_code == 409
    other = post(word="Tran").json()
    assert client.put(f"/api/pronunciation/entries/{other['id']}", json={"word": "NGUYEN", "respelling": "a"}).status_code == 409
    assert client.put("/api/pronunciation/entries/nope", json={"word": "a", "respelling": "b"}).status_code == 404


def test_preview_returns_the_rewritten_text():
    post()
    r = client.post("/api/pronunciation/preview", json={"text": "Dear Nguyen, hello nguyen.", "language": "en"})
    assert r.json() == {"text": "Dear win, hello win."}
    assert client.post("/api/pronunciation/preview", json={"text": "Nguyen", "language": "es"}).json() == {"text": "Nguyen"}
    assert client.post("/api/pronunciation/preview", json={"text": "x" * 2001}).status_code == 422


def test_the_openai_compatible_api_applies_the_dictionary(monkeypatch):
    seen = []

    class Model:
        sr = 24000

        def generate(self, text, **kwargs):
            seen.append(text)
            return np.zeros(2400, dtype="float32")

    monkeypatch.setattr(engine, "_load_model", lambda: Model())
    post()
    r = client.post("/v1/audio/speech", json={"input": "Hi Nguyen.", "voice": "default", "response_format": "wav"})
    assert r.status_code == 200 and seen == ["Hi win."]


# --- CLI and MCP -------------------------------------------------------------------------------


class AppClient(cli.Client):
    def __init__(self):
        super().__init__("http://testserver")
        self.http = TestClient(app, base_url="http://127.0.0.1")

    def request(self, method, path, body=None, headers=None):
        res = self.http.request(method, path, content=body, headers=headers)
        if res.status_code >= 400:
            raise cli.CliError(cli._error_message(res.content, res.reason_phrase))
        return res.content


def run(capsys, *argv):
    code = cli.main(list(argv), client=AppClient())
    out, err = capsys.readouterr()
    return code, out, err


def test_cli_list_add_update_remove(capsys):
    assert run(capsys, "pronounce", "list", "--json")[1].strip() == '{"entries": []}'
    code, out, _ = run(capsys, "pronounce", "add", "Nguyen", "win", "--json")
    assert code == 0 and json.loads(out)["respelling"] == "win"
    run(capsys, "pronounce", "add", "nguyen", "nwin")  # same word: updates it
    entries = json.loads(run(capsys, "pronounce", "list", "--json")[1])["entries"]
    assert [(e["word"], e["respelling"]) for e in entries] == [("nguyen", "nwin")]
    code, out, _ = run(capsys, "pronounce", "list")
    assert "nguyen -> nwin" in out
    assert run(capsys, "pronounce", "remove", "NGUYEN")[0] == 0
    assert store.list_entries("en") == []
    code, _, err = run(capsys, "pronounce", "remove", "Nguyen")
    assert code == 1 and "no pronunciation" in err
    assert run(capsys, "pronounce", "add", "Nguyen")[0] == 1


def test_mcp_tool(monkeypatch):
    monkeypatch.setattr(mcp_server, "_client", AppClient)

    def call(**arguments):
        return mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                  "params": {"name": "manage_pronunciations", "arguments": arguments}})["result"]

    assert call(action="add", word="SQL", respelling="sequel", whole_word=False)["isError"] is False
    assert store.list_entries("en")[0].whole_word is False
    assert "SQL -> sequel" in call(action="list")["content"][0]["text"]
    assert call(action="remove", word="SQL")["isError"] is False
    assert call(action="explode")["isError"] is True
