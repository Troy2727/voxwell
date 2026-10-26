"""Turn an uploaded book (EPUB, or plain text / Markdown) into a title and a list of chapters.

EPUB is read with the standard library only (zipfile + ElementTree + html.parser): popular
EPUB packages are AGPL, which Voxwell (MIT) cannot use.
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


# --- shared --------------------------------------------------------------------------------


def _check(chapters: list[Chapter]) -> list[Chapter]:
    if not chapters:
        raise ImportError_("No readable text was found in the book.")
    if len(chapters) > MAX_CHAPTERS:
        raise ImportError_(f"The book has too many chapters ({MAX_CHAPTERS} max).")
    return chapters


def import_book(data: bytes, filename_stem: str, ext: str) -> tuple[str, list[Chapter]]:
    """Return (title, chapters) for an uploaded .epub, .txt or .md file."""
    fallback = filename_stem.strip()[:100] or "Untitled book"
    if ext == ".epub":
        return from_epub(data, fallback)
    if ext in (".txt", ".md"):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1252", errors="replace")  # common for older Windows text files
        return from_text(text, fallback)
    raise ImportError_("Use an EPUB, TXT or Markdown (.md) file.")
