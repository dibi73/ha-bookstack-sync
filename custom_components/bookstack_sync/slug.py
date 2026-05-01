"""Filename slug helpers for the markdown back-export (issue #61, A5)."""

from __future__ import annotations

import re
import unicodedata

_UMLAUTS = str.maketrans(
    {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
        "Ä": "ae",
        "Ö": "oe",
        "Ü": "ue",
        "ẞ": "ss",
    },
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_MAX_LEN = 80
_MAX_COLLISION_SUFFIX = 10000


def slugify(name: str) -> str:
    """
    Return a stable, lowercase ASCII slug suitable for cross-platform filenames.

    Rules: NFKD-normalise → manual umlaut map (German first, before NFKD eats
    them) → ASCII-fold → lowercase → collapse non-alphanumerics to ``-`` →
    trim → cap at 80 chars → fall back to ``"untitled"`` if everything was
    stripped.
    """
    text = name.translate(_UMLAUTS)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = _NON_ALNUM.sub("-", text)
    text = text.strip("-")
    if not text:
        return "untitled"
    return text[:_MAX_LEN].rstrip("-") or "untitled"


def make_unique_slug(base: str, taken: set[str]) -> str:
    """
    Append ``-2``, ``-3``, … to ``base`` until the result is not in ``taken``.

    Why: BookStack accepts duplicate page titles; the filesystem does not.
    Stable: as long as ``taken`` is iterated in insertion order across runs,
    the same title set produces the same slug-to-filename map.
    """
    if base not in taken:
        return base
    for i in range(2, _MAX_COLLISION_SUFFIX):
        candidate = f"{base}-{i}"
        if candidate not in taken:
            return candidate
    msg = f"Cannot create unique slug for {base!r} after {_MAX_COLLISION_SUFFIX} tries"
    raise RuntimeError(msg)
