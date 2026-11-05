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

client = TestClient(app, base_url="http://127.0.0.1")
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
    (b"x", ".doc", "EPUB, PDF, Word"),
    (b"x", ".pdf", "damaged"),
    (b"not a zip", ".docx", "not a valid Word"),
])
def test_import_errors(data, ext, message):
    with pytest.raises(ImportError_, match=message):
        import_book(data, "x", ext)


def make_pdf(pages: list[list[str]], title: str = "") -> bytes:
    """A small real PDF: each page is a list of text lines."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", "", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for lines in pages:
        body = "BT /F1 12 Tf 72 720 Td " + " 0 -14 Td ".join(f"({line}) Tj" for line in lines) + " ET"
        kids.append(f"{len(objects) + 1} 0 R")
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {len(objects) + 2} 0 R /Resources << /Font << /F1 3 0 R >> >> >>")
        objects.append(f"<< /Length {len(body)} >>\nstream\n{body}\nendstream")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    info = f"{len(objects) + 1} 0 R"
    objects.append(f"<< /Title ({title}) >>")
    out = "%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{obj}\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010} 00000 n \n" for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info {info} >>\nstartxref\n{xref}\n%%EOF\n"
    return out.encode("latin-1")


def test_pdf_with_chapter_headings_and_its_title():
    pdf = make_pdf([["Chapter 1", "It was a dark and", "stormy night."], ["Chapter 2", "The sun came out."]], title="The Long Night")
    title, chapters = import_book(pdf, "file", ".pdf")
    assert title == "The Long Night"
    assert [c.title for c in chapters] == ["Chapter 1", "Chapter 2"]
    assert "dark and stormy night" in chapters[0].text
    assert chapters[1].text == "The sun came out."


def test_pdf_without_headings_is_one_chapter_named_after_the_file():
    title, chapters = import_book(make_pdf([["First page."], ["Second page."]]), "my notes", ".pdf")
    assert title == "my notes"
    assert len(chapters) == 1 and "First page." in chapters[0].text and "Second page." in chapters[0].text


def test_pdf_words_broken_across_lines_are_joined():
    _, chapters = import_book(make_pdf([["A wonder-", "ful day."]]), "x", ".pdf")
    assert "wonderful day" in chapters[0].text


def blank_pdf(password: str = "") -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    if password:
        writer.encrypt(password, algorithm="RC4-128")
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_a_scanned_pdf_says_why_it_cant_be_read():
    with pytest.raises(ImportError_, match="Scanned"):
        import_book(blank_pdf(), "x", ".pdf")


def test_a_password_protected_pdf_says_so():
    with pytest.raises(ImportError_, match="password"):
        import_book(blank_pdf("secret"), "x", ".pdf")


WORD_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def make_docx(paragraphs: list[tuple[str, str]], title: str = "") -> bytes:
    """A small real .docx. Its heading style has a Spanish id, as Spanish Word writes it."""
    body = "".join(
        f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr><w:r><w:t>{text}</w:t></w:r></w:p>' if style else f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
        for style, text in paragraphs
    )
    styles = (
        f'<w:styles {WORD_NS}><w:style w:styleId="Ttulo1"><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>'
        '<w:style w:styleId="Cita"><w:pPr/></w:style></w:styles>'
    )
    core = f'<cp:coreProperties xmlns:cp="urn:cp" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{title}</dc:title></cp:coreProperties>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", f"<w:document {WORD_NS}><w:body>{body}</w:body></w:document>")
        z.writestr("word/styles.xml", styles)
        z.writestr("docProps/core.xml", core)
    return buf.getvalue()


def test_word_headings_start_chapters_whatever_language_word_was_in():
    doc = make_docx([("Ttulo1", "La tormenta"), ("", "Llovió toda la noche."), ("Cita", "Una cita."), ("Ttulo1", "La mañana"), ("", "Salió el sol.")], title="Mi libro")
    title, chapters = import_book(doc, "file", ".docx")
    assert title == "Mi libro"
    assert [c.title for c in chapters] == ["La tormenta", "La mañana"]
    assert chapters[0].text == "Llovió toda la noche.\n\nUna cita."
    assert chapters[1].text == "Salió el sol."


def test_word_without_headings_or_title_uses_the_file_name():
    title, chapters = import_book(make_docx([("", "Just one paragraph.")]), "my doc", ".docx")
    assert title == "my doc" and [c.text for c in chapters] == ["Just one paragraph."]


def test_an_empty_word_file_has_no_readable_text():
    with pytest.raises(ImportError_, match="No readable text"):
        import_book(make_docx([]), "x", ".docx")


def test_a_zip_that_isnt_a_word_file_is_refused():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hello.txt", "hi")
    with pytest.raises(ImportError_, match="not a valid Word"):
        import_book(buf.getvalue(), "x", ".docx")


def test_a_word_file_that_unpacks_too_large_is_refused(monkeypatch):
    from voxwell.features.audiobook import importer

    monkeypatch.setattr(importer, "MAX_WORD_XML_BYTES", 10)
    with pytest.raises(ImportError_, match="too large"):
        import_book(make_docx([("", "Some text here.")]), "x", ".docx")


def test_pdf_and_word_upload_through_the_api():
    for name, data, heading in (("a.pdf", make_pdf([["Chapter 1", "Hello."]]), "Chapter 1"), ("b.docx", make_docx([("Ttulo1", "Uno"), ("", "Hola.")]), "Uno")):
        r = client.post("/api/audiobook/books", files={"file": (name, data)})
        assert r.status_code == 200, r.text
        assert r.json()["chapters"][0]["title"] == heading


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
