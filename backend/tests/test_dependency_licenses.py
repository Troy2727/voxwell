"""Voxwell is MIT: no installed dependency may be GPL/AGPL or non-commercial.

LGPL is allowed for packages Python loads as separate, replaceable libraries; each one is
listed explicitly so a new LGPL dependency still needs a deliberate decision.
"""

import importlib.metadata as md
import re
from pathlib import Path

LGPL_ALLOWED = {"soxr"}

_FORBIDDEN = re.compile(r"\b(A?GPL|GNU (Affero )?General Public)|non.?commercial|CC-BY-NC", re.I)
_LGPL = re.compile(r"LGPL|Lesser General Public", re.I)


def _license_text(dist) -> str:
    meta = dist.metadata
    classifiers = [c for c in meta.get_all("Classifier") or [] if c.startswith("License")]
    declared = list(filter(None, [meta.get("License-Expression"), *classifiers]))
    # The free-text License field often embeds a full license that mentions the GPL in
    # passing (e.g. matplotlib), so only read it when nothing structured is declared.
    return " | ".join(declared) if declared else meta.get("License") or ""


def test_no_copyleft_or_noncommercial_dependencies():
    offenders = []
    for dist in md.distributions():
        # Copies bundled inside another package (setuptools/_vendor) belong to that package and are
        # not installed dependencies; they only appear on sys.path once something imports
        # pkg_resources (chatterbox does), which made this check depend on test order.
        if "_vendor" in Path(str(dist.locate_file(""))).parts:
            continue
        name = dist.metadata["Name"].lower().replace("_", "-")
        text = _license_text(dist)
        if _LGPL.search(text):
            if name not in LGPL_ALLOWED:
                offenders.append(f"{name}: {text}")
        elif _FORBIDDEN.search(text):
            offenders.append(f"{name}: {text}")
    assert not offenders, "Dependencies incompatible with MIT distribution:\n" + "\n".join(offenders)
