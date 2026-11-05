"""Turn an uploaded book (EPUB, PDF, Word, or plain text / Markdown) into a title and a list of chapters.

EPUB and Word are read with the standard library only (zipfile + ElementTree + html.parser):
popular EPUB packages are AGPL, which Voxwell (MIT) cannot use. PDF uses pypdf (BSD-3-Clause).
"""

import posixpath
import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from xml.etree import ElementTree

MAX_CHAPTERS = 500
MIN_CHAPTER_CHARS = 1  # skip documents with no text at all (covers, image-only pages)
MAX_WORD_XML_BYTES = 200 * 1024 * 1024  # unpacked; a small file can claim to unpack to far more


class ImportError_(ValueError):
    """The file is not a book Voxwell can read; the message says why."""


@dataclass
class Chapter:
    title: str
    text: str  # paragraphs separated by blank lines


# --- plain text / Markdown -----------------------------------------------------------------

# "# Title" / "## Title" (Markdown) or "Chapter 1", "CHAPTER IV: The Storm", "Part Two" lines.
_HEADING = re.compile(r"^\s*(?:#{1,3}\s+(.+?)|((?:chapter|part|book)\s+[\w-]+.*?))\s*#*\s*$", re.I)


def from_text(text: str, fallback_title: str) -> tuple[str, list[Chapter]]:
    chapters: list[Chapter] = []
    title, body = None, []
    for raw in text.replace("\r\n", "\n").split("\n"):
        m = _HEADING.match(raw) if len(raw) < 120 else None
        if m:
            if body and "".join(body).strip():
                chapters.append(Chapter(title or f"Chapter {len(chapters) + 1}", _paragraphs("\n".join(body))))
            title, body = (m.group(1) or m.group(2)).strip(), []
        else:
            body.append(raw)
    if "".join(body).strip():
        chapters.append(Chapter(title or f"Chapter {len(chapters) + 1}", _paragraphs("\n".join(body))))
    return fallback_title, _check(chapters)


def _paragraphs(text: str) -> str:
    """Normalize to paragraphs separated by one blank line, with single spaces inside."""
    paras = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text)]
    return "\n\n".join(p for p in paras if p)


# --- EPUB ----------------------------------------------------------------------------------

_BLOCKS = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "tr", "section"}
_SKIP = {"script", "style", "head", "nav"}


class _Text(HTMLParser):
    """Collect readable text; block elements become paragraph breaks; first heading is the title."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.heading: str | None = None
        self._in_heading = False
        self._heading_text: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self._skip += 1
        elif tag in _BLOCKS:
            self.parts.append("\n\n")
        if tag in ("h1", "h2") and self.heading is None:
            self._in_heading = True

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCKS:
            self.parts.append("\n\n")
        if tag in ("h1", "h2") and self._in_heading:
            self._in_heading = False
            self.heading = " ".join("".join(self._heading_text).split()) or None

    def handle_data(self, data):
        if self._skip:
            return
        self.parts.append(data)
        if self._in_heading:
            self._heading_text.append(data)


def _xml(zf: zipfile.ZipFile, name: str) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(zf.read(name))
    except (KeyError, ElementTree.ParseError) as exc:
        raise ImportError_(f"The EPUB is damaged ({name}).") from exc


def from_epub(data: bytes, fallback_title: str) -> tuple[str, list[Chapter]]:
    try:
        zf = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ImportError_("This is not a valid EPUB file.") from exc
    with zf:
        container = _xml(zf, "META-INF/container.xml")
        rootfile = next((el.get("full-path") for el in container.iter() if el.tag.endswith("rootfile")), None)
        if not rootfile:
            raise ImportError_("The EPUB has no package file.")
        opf = _xml(zf, rootfile)
        base = posixpath.dirname(rootfile)

        title = next((el.text.strip() for el in opf.iter() if el.tag.endswith("}title") and el.text and el.text.strip()), None)
        manifest = {el.get("id"): el.get("href") for el in opf.iter() if el.tag.endswith("}item")}
        spine = [el.get("idref") for el in opf.iter() if el.tag.endswith("}itemref") and el.get("linear") != "no"]

        chapters = []
        for idref in spine:
            href = manifest.get(idref)
            if not href:
                continue
            name = posixpath.normpath(posixpath.join(base, href.split("#")[0]))
            try:
                html = zf.read(name).decode("utf-8", errors="replace")
            except KeyError:
                continue  # a broken link in the spine; skip that document
            parser = _Text()
            parser.feed(html)
            text = _paragraphs("".join(parser.parts))
            if len(text) >= MIN_CHAPTER_CHARS:
                chapters.append(Chapter(parser.heading or f"Chapter {len(chapters) + 1}", text))
    return title or fallback_title, _check(chapters)


# --- Word ----------------------------------------------------------------------------------

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _word_xml(zf: zipfile.ZipFile, name: str) -> ElementTree.Element | None:
    """A part of the .docx, or None if the file doesn't have it."""
    try:
        if zf.getinfo(name).file_size > MAX_WORD_XML_BYTES:
            raise ImportError_("The Word file is too large.")
        return ElementTree.fromstring(zf.read(name))
    except KeyError:
        return None
    except ElementTree.ParseError as exc:
        raise ImportError_(f"The Word file is damaged ({name}).") from exc


def _word_heading_styles(styles: ElementTree.Element | None) -> set[str]:
    """Top-level heading styles. Their ids are translated in non-English Word, but the outline level isn't."""
    found = set()
    for style in () if styles is None else styles.iter(f"{_W}style"):
        level = style.find(f"{_W}pPr/{_W}outlineLvl")
        if level is not None and level.get(f"{_W}val") in ("0", "1"):
            found.add(style.get(f"{_W}styleId"))
    return found


def _word_paragraph_text(paragraph: ElementTree.Element) -> str:
    parts = []
    for el in paragraph.iter():
        if el.tag == f"{_W}t":
            parts.append(el.text or "")
        elif el.tag in (f"{_W}tab", f"{_W}br"):
            parts.append(" ")
    return "".join(parts).strip()


def from_docx(data: bytes, fallback_title: str) -> tuple[str, list[Chapter]]:
    try:
        zf = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ImportError_("This is not a valid Word file. Older .doc files need saving as .docx first.") from exc
    with zf:
        document = _word_xml(zf, "word/document.xml")
        if document is None:
            raise ImportError_("This is not a valid Word file.")
        headings = _word_heading_styles(_word_xml(zf, "word/styles.xml"))
        core = _word_xml(zf, "docProps/core.xml")
    lines = []
    for paragraph in document.iter(f"{_W}p"):
        text = _word_paragraph_text(paragraph)
        if not text:
            continue
        style = paragraph.find(f"{_W}pPr/{_W}pStyle")
        heading = style is not None and style.get(f"{_W}val") in headings
        lines.append(f"# {text}" if heading else text)
    title = None if core is None else next((el.text.strip() for el in core.iter() if el.tag.endswith("}title") and el.text and el.text.strip()), None)
    _, chapters = from_text("\n\n".join(lines), fallback_title)
    return title or fallback_title, chapters


# --- PDF -----------------------------------------------------------------------------------

_SPLIT_WORD = re.compile(r"(\w)-\n(\w)")  # a word broken across two lines


def from_pdf(data: bytes, fallback_title: str) -> tuple[str, list[Chapter]]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ImportError_("This PDF is locked with a password. Remove the password and try again.")
        pages = [page.extract_text() or "" for page in reader.pages]
        title = reader.metadata.title if reader.metadata else None
    except ImportError_:
        raise
    except Exception as exc:  # pypdf raises many types on damaged files, and this is the user's own upload
        raise ImportError_("This PDF is damaged or can't be read.") from exc
    text = "\n\n".join(_SPLIT_WORD.sub(r"\1\2", page) for page in pages if page.strip())
    if not text:
        raise ImportError_("No text was found in this PDF. Scanned pages are pictures, which can't be read.")
    _, chapters = from_text(text, fallback_title)
    return (title or "").strip() or fallback_title, chapters


# --- shared --------------------------------------------------------------------------------


def _check(chapters: list[Chapter]) -> list[Chapter]:
    if not chapters:
        raise ImportError_("No readable text was found in the book.")
    if len(chapters) > MAX_CHAPTERS:
        raise ImportError_(f"The book has too many chapters ({MAX_CHAPTERS} max).")
    return chapters


def import_book(data: bytes, filename_stem: str, ext: str) -> tuple[str, list[Chapter]]:
    """Return (title, chapters) for an uploaded .epub, .pdf, .docx, .txt or .md file."""
    fallback = filename_stem.strip()[:100] or "Untitled book"
    if ext == ".epub":
        return from_epub(data, fallback)
    if ext == ".pdf":
        return from_pdf(data, fallback)
    if ext == ".docx":
        return from_docx(data, fallback)
    if ext in (".txt", ".md"):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1252", errors="replace")  # common for older Windows text files
        return from_text(text, fallback)
    raise ImportError_("Use an EPUB, PDF, Word (.docx), TXT or Markdown (.md) file.")
