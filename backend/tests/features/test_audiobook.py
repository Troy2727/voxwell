import io
import wave
import zipfile

import pytest
from fastapi.testclient import TestClient

from voxwell import voices
from voxwell.features.audiobook import books
from voxwell.features.audiobook.chunking import MAX_CHARS, chapter_chunks, chunks
from voxwell.features.audiobook.importer import ImportError_, import_book
from voxwell.features.voice_cloning import engine
from voxwell.main import app

client = TestClient(app)
RATE = 24000


def wav_bytes(seconds: float = 0.5) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"\x01\x00" * int(seconds * RATE))
    return buf.getvalue()


def make_epub(title="The Lighthouse") -> bytes:
    """A minimal but realistic EPUB 3: OEBPS folder, image-only cover, nav doc, two chapters."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>""")
        z.writestr("OEBPS/content.opf", f"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{title}</dc:title></metadata>
  <manifest>
    <item id="cover" href="text/cover.xhtml" media-type="application/xhtml+xml"/>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="c1" href="text/ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="text/ch2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="cover"/><itemref idref="nav" linear="no"/><itemref idref="c1"/><itemref idref="c2"/></spine>
</package>""")
        z.writestr("OEBPS/text/cover.xhtml", '<html><body><img src="cover.jpg"/></body></html>')
        z.writestr("OEBPS/nav.xhtml", "<html><body><nav><ol><li>Contents</li></ol></nav></body></html>")
        z.writestr("OEBPS/text/ch1.xhtml", """<html><head><title>x</title><style>p {}</style></head><body>
<h1>Chapter One: <em>Arrival</em></h1><p>The keeper climbed the stairs.</p><p>It was cold &amp; dark.</p></body></html>""")
        z.writestr("OEBPS/text/ch2.xhtml", "<html><body><h2>The Storm</h2><p>Waves hit the rocks.</p></body></html>")
    return buf.getvalue()


@pytest.fixture
def fake(monkeypatch):
    calls = []

    def synth(text, language, reference_audio=None):
        calls.append((text, language, reference_audio.stem if reference_audio else None))
        return wav_bytes()

    monkeypatch.setattr(engine, "synthesize", synth)
    monkeypatch.setattr(books, "start", lambda book: (setattr(book, "state", "queued"), books._work(book)))
    return calls


def upload(data=None, name="lighthouse.epub"):
    return client.post("/api/audiobook/books", files={"file": (name, make_epub() if data is None else data, "application/epub+zip")})


# --- importing ----------------------------------------------------------------------------


def test_epub_reading_order_titles_and_text():
    title, chapters = import_book(make_epub(), "file", ".epub")
    assert title == "The Lighthouse"
    assert [c.title for c in chapters] == ["Chapter One: Arrival", "The Storm"]  # cover/nav skipped
    assert chapters[0].text == "Chapter One: Arrival\n\nThe keeper climbed the stairs.\n\nIt was cold & dark."


def test_text_with_chapter_headings():
    text = "Intro words.\n\nCHAPTER 1\nFirst line.\nSame paragraph.\n\nNew paragraph.\n\n# Part Two: Home\nEnd."
    title, chapters = import_book(text.encode(), "My Book", ".txt")
    assert title == "My Book"
    assert [c.title for c in chapters] == ["Chapter 1", "CHAPTER 1", "Part Two: Home"]
    assert chapters[1].text == "First line. Same paragraph.\n\nNew paragraph."


def test_text_without_headings_is_one_chapter():
    _, chapters = import_book(b"Just a short story.", "x", ".md")
    assert [(c.title, c.text) for c in chapters] == [("Chapter 1", "Just a short story.")]


def test_windows_text_files_still_import():
    _, chapters = import_book("Café au lait.".encode("cp1252"), "x", ".txt")
    assert chapters[0].text == "Café au lait."


@pytest.mark.parametrize("data,ext,message", [
    (b"", ".txt", "No readable text"),
    (b"not a zip", ".epub", "not a valid EPUB"),
    (b"x", ".pdf", "EPUB, TXT or Markdown"),
])
def test_import_errors(data, ext, message):
    with pytest.raises(ImportError_, match=message):
        import_book(data, "x", ext)


def test_damaged_epub():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
    with pytest.raises(ImportError_, match="damaged"):
        import_book(buf.getvalue(), "x", ".epub")


# --- chunking ------------------------------------------------------------------------------


def test_short_sentences_are_merged_and_quotes_kept():
    assert chunks('He said "Hi." She smiled. Then they left!') == ['He said "Hi." She smiled. Then they left!']


def test_long_text_is_split_without_losing_words():
    sentence = "word " * 120  # 600 characters, no punctuation
    text = f"First sentence here. {sentence.strip()}. Last one, with a comma, and more words."
    parts = chunks(text)
    assert all(len(p) <= MAX_CHARS for p in parts)
    assert " ".join(parts).split() == text.split()


def test_paragraphs_stay_separate():
    one, two = "The keeper climbed the long stairs slowly.", "Below him the sea was quiet and very dark."
    assert chapter_chunks(f"{one}\n\n{two}") == [[one], [two]]


def test_short_headings_are_spoken_with_the_next_paragraph():
    """Alone, title-like phrases make Chatterbox loop ("The ship. The ship.")."""
    text = "Chapter 3\n\nThe Ship\n\nFar out, a small ship fought the wind all night long."
    assert chapter_chunks(text) == [["Chapter 3. The Ship. Far out, a small ship fought the wind all night long."]]


def test_a_short_last_paragraph_is_still_spoken():
    long = "The keeper climbed the long stairs slowly."
    assert chapter_chunks(f"{long}\n\nThe End") == [[long], ["The End."]]


def test_pauses_between_sentences_and_paragraphs(fake):
    audio = books.render_text([["a", "b"], ["c"]], "en", None)
    with wave.open(io.BytesIO(audio)) as w:
        seconds = w.getnframes() / w.getframerate()
    assert seconds == pytest.approx(3 * 0.5 + books.SENTENCE_PAUSE + books.PARAGRAPH_PAUSE, abs=0.01)


# --- the API -------------------------------------------------------------------------------


def test_import_and_render_selected_chapters(fake):
    book = upload().json()
    assert book["title"] == "The Lighthouse" and book["state"] == "draft"
    assert [c["title"] for c in book["chapters"]] == ["Chapter One: Arrival", "The Storm"]

    narrator = voices.save_voice("Narrator", wav_bytes(), "upload")
    r = client.patch(f"/api/audiobook/books/{book['id']}", json={
        "language": "fr", "voice": narrator.id, "chapters": [{"include": False}, {"include": True}],
    })
    assert r.status_code == 200
    done = client.post(f"/api/audiobook/books/{book['id']}/render").json()
    assert done["state"] == "done" and done["percent"] == 100
    assert [c["status"] for c in done["chapters"]] == ["pending", "done"]
    assert fake == [("The Storm. Waves hit the rocks.", "fr", narrator.id)]  # heading joined
    assert client.get(done["chapters"][1]["audio_url"]).content[:4] == b"RIFF"


def test_resume_after_voxwell_closed(fake, monkeypatch):
    book = upload().json()
    real_synth = engine.synthesize

    def crash_in_chapter_two(text, language, reference_audio=None):
        if text.startswith("The Storm"):
            raise KeyboardInterrupt  # stands in for the app closing mid-render
        return real_synth(text, language, reference_audio)

    monkeypatch.setattr(engine, "synthesize", crash_in_chapter_two)
    with pytest.raises(KeyboardInterrupt):
        client.post(f"/api/audiobook/books/{book['id']}/render")
    monkeypatch.setattr(books, "_books", {})  # restart
    paused = client.get(f"/api/audiobook/books/{book['id']}").json()
    assert paused["state"] == "paused" and "Resume" in paused["error"]
    assert [c["status"] for c in paused["chapters"]] == ["done", "pending"]

    monkeypatch.setattr(engine, "synthesize", real_synth)
    fake.clear()
    resumed = client.post(f"/api/audiobook/books/{book['id']}/render").json()
    assert resumed["state"] == "done"
    assert [c[0] for c in fake] == ["The Storm. Waves hit the rocks."]  # chapter one not redone


def test_changing_voice_rerenders_everything(fake):
    book = upload().json()
    client.post(f"/api/audiobook/books/{book['id']}/render")
    changed = client.patch(f"/api/audiobook/books/{book['id']}", json={"language": "de"}).json()
    assert changed["state"] == "draft" and {c["status"] for c in changed["chapters"]} == {"pending"}
    assert client.get(f"/api/audiobook/books/{book['id']}/chapters/0/audio").status_code == 409


def test_download_zip(fake):
    book = upload().json()
    assert client.get(f"/api/audiobook/books/{book['id']}/download").status_code == 409
    client.post(f"/api/audiobook/books/{book['id']}/render")
    r = client.get(f"/api/audiobook/books/{book['id']}/download")
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert names == ["001 - Chapter One Arrival.wav", "002 - The Storm.wav"]


def test_preview(fake):
    book = upload().json()
    r = client.post(f"/api/audiobook/books/{book['id']}/preview", json={"chapter": 0})
    assert r.status_code == 200 and client.get(r.json()["url"]).content[:4] == b"RIFF"
    assert [c[0] for c in fake] == ["Chapter One: Arrival. The keeper climbed the stairs.", "It was cold & dark."]
    assert client.post(f"/api/audiobook/books/{book['id']}/preview", json={"chapter": 9}).status_code == 404


def test_chapter_text(fake):
    book = upload().json()
    assert client.get(f"/api/audiobook/books/{book['id']}/chapters/1/text").json() == {"text": "The Storm\n\nWaves hit the rocks."}


def test_deleted_narrator_voice(fake):
    narrator = voices.save_voice("Narrator", wav_bytes(), "upload")
    book = upload().json()
    client.patch(f"/api/audiobook/books/{book['id']}", json={"voice": narrator.id})
    voices.delete_voice(narrator.id)
    result = client.post(f"/api/audiobook/books/{book['id']}/render").json()
    assert result["state"] == "error" and "deleted" in result["error"]


@pytest.mark.parametrize("body", [{"language": "xx"}, {"voice": "000000000000"}, {"chapters": [{"include": True}]}])
def test_rejects_bad_settings(fake, body):
    book = upload().json()
    assert client.patch(f"/api/audiobook/books/{book['id']}", json=body).status_code == 422


def test_needs_a_chapter(fake):
    book = upload().json()
    client.patch(f"/api/audiobook/books/{book['id']}", json={"chapters": [{"include": False}, {"include": False}]})
    assert client.post(f"/api/audiobook/books/{book['id']}/render").status_code == 422


def test_settings_locked_while_rendering(fake, monkeypatch):
    monkeypatch.setattr(books, "start", lambda book: (setattr(book, "state", "queued"), books.save(book)))
    book = upload().json()
    client.post(f"/api/audiobook/books/{book['id']}/render")
    assert client.patch(f"/api/audiobook/books/{book['id']}", json={"language": "de"}).status_code == 409
    assert client.post(f"/api/audiobook/books/{book['id']}/render").status_code == 409
    assert client.delete(f"/api/projects/items/audiobook/{book['id']}").status_code == 409


def test_bad_uploads():
    assert upload(b"x", "book.pdf").status_code == 422
    assert upload(b"not a zip").status_code == 422


@pytest.mark.parametrize("bad", ["000000000000", "ABCDEF123456", ".."])
def test_unknown_ids(bad):
    assert client.get(f"/api/audiobook/books/{bad}").status_code in (404, 405)
    assert client.get(f"/api/audiobook/previews/{bad}").status_code in (404, 405)


def test_projects_list_rename_delete(fake):
    book = upload().json()
    client.post(f"/api/audiobook/books/{book['id']}/render")
    item = client.get("/api/projects/items").json()[0]
    assert item["kind"] == "audiobook" and item["chapters_done"] == 2 and item["voice"] == "Default voice"
    path = f"/api/projects/items/audiobook/{book['id']}"
    assert client.patch(path, json={"title": "Keeper"}).json()["title"] == "Keeper"
    assert client.delete(path).status_code == 200
    assert client.get("/api/projects/items").json() == []
