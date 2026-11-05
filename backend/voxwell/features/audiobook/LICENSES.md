# Audiobook: licenses

Audiobooks are spoken with the voice cloning model (`voxwell.features.voice_cloning.engine`); see `../voice_cloning/LICENSES.md`. No other models.

EPUB and Word files are read with the Python standard library only (`zipfile`, `xml.etree`, `html.parser`). The common EPUB packages (e.g. EbookLib) are AGPL and must not be added. PDF files are read with pypdf (BSD-3-Clause).
