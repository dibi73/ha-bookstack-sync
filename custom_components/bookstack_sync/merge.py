"""
Marker-block aware merge logic.

A synced page is structured as::

    <!-- BEGIN AUTO-GENERATED -->
    ... regenerated every sync ...
    <!-- END AUTO-GENERATED -->

    <!-- BEGIN MANUAL -->
    ... user-edited, never overwritten ...
    <!-- END MANUAL -->

The merge keeps the existing MANUAL block verbatim and replaces the AUTO block.
A hash comparison detects the case where the user edited inside the AUTO block:
if the live AUTO block doesn't match the hash we stored after the last write,
something or someone changed it -> we log and skip rather than clobber.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

from .const import (
    AUTO_BEGIN_MARKER,
    AUTO_END_MARKER,
    MANUAL_BEGIN_MARKER,
    MANUAL_END_MARKER,
)

_AUTO_RE = re.compile(
    re.escape(AUTO_BEGIN_MARKER) + r"(.*?)" + re.escape(AUTO_END_MARKER),
    re.DOTALL,
)
_MANUAL_RE = re.compile(
    re.escape(MANUAL_BEGIN_MARKER) + r"(.*?)" + re.escape(MANUAL_END_MARKER),
    re.DOTALL,
)

_FALLBACK_MANUAL_BODY = (
    "\n\n_Notizen, die du hier zwischen den Markern einträgst, "
    "bleiben beim Sync erhalten._\n\n"
)


@dataclass
class MergeResult:
    """Outcome of merging a freshly rendered AUTO block with an existing page."""

    body: str
    auto_hash: str
    auto_block_changed: bool
    manual_block_tampered: bool


def _normalise_for_hash(auto_body: str) -> str:
    r"""
    Aggressively normalise the AUTO body before hashing.

    Sequence (each step is invariant against a known BookStack-side
    normalisation pass that historically broke our tampering detection):

    1. Newline normalisation: ``\r\n`` and bare ``\r`` → ``\n``.
       BookStack stores LF internally on Linux, but on some setups the
       reverse-proxy layer or the markdown editor injects CRLF, and our
       prior strip-only hash treated LF and CRLF as different content,
       producing 260+ false-positive tampering reports per sync.

    2. Unicode NFC: ``é`` (U+00E9) and ``é`` (U+0065 + U+0301) collapse
       to one form. BookStack's editor normalises to NFC; HA renderers
       sometimes produce NFD via the underlying string sources.

    3. Trailing/leading whitespace: ``strip()``. ``build_page_body``
       writes through ``auto_body.strip()`` and ``extract_auto_block``
       reads via ``.strip('\n')``, so the hash must match either side.
    """
    text = auto_body.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFC", text)
    return text.strip()


def hash_auto_block(auto_body: str) -> str:
    """Compute the whitespace+unicode-normalised hash of the AUTO body."""
    return hashlib.sha256(_normalise_for_hash(auto_body).encode("utf-8")).hexdigest()


def _legacy_unstripped_hash(auto_body: str) -> str:
    """
    Bug-bug-compatible hash from v0.1.x that didn't strip trailing whitespace.

    Only used to recognise mappings written before the v0.2.1 fix so we
    don't falsely flag them as tampered. New writes always use the stripped
    hash above.
    """
    return hashlib.sha256(auto_body.encode("utf-8")).hexdigest()


def extract_auto_block(page_markdown: str | None) -> str | None:
    """Return the body of the AUTO marker block, or None if absent."""
    if not page_markdown:
        return None
    match = _AUTO_RE.search(page_markdown)
    return match.group(1).strip("\n") if match else None


def extract_manual_block(page_markdown: str | None) -> str | None:
    """Return the body of the MANUAL marker block, or None if absent."""
    if not page_markdown:
        return None
    match = _MANUAL_RE.search(page_markdown)
    return match.group(1).strip("\n") if match else None


def split_blocks(page_markdown: str | None) -> tuple[str, str]:
    """
    Split a page into ``(auto_body, manual_body)`` for the export (issue #61).

    Marker comments are stripped. Missing block → empty string for that side.
    Combines the two existing extractors so the export writer doesn't need
    to call both separately.
    """
    auto = extract_auto_block(page_markdown) or ""
    manual = extract_manual_block(page_markdown) or ""
    return auto, manual


def build_page_body(auto_body: str, manual_body: str) -> str:
    """Compose the full markdown body with both marker blocks."""
    return (
        f"{AUTO_BEGIN_MARKER}\n"
        f"{auto_body.strip()}\n"
        f"{AUTO_END_MARKER}\n"
        f"\n"
        f"{MANUAL_BEGIN_MARKER}\n"
        f"{manual_body.strip()}\n"
        f"{MANUAL_END_MARKER}\n"
    )


def merge_page(
    new_auto_body: str,
    existing_markdown: str | None,
    last_known_auto_hash: str | None,
    default_manual_body: str | None = None,
) -> MergeResult:
    """
    Combine the new AUTO block with an existing page's MANUAL block.

    Detects manual-block tampering inside the AUTO area by comparing the
    existing AUTO block against the hash we stored after the previous write.

    ``default_manual_body`` is the placeholder we drop into the manual
    block on first write, so users see a hint about where to put their
    notes. Callers should pass the localised version from ``_strings``;
    the hardcoded fallback is German for backward compatibility with
    pre-i18n stores.
    """
    new_hash = hash_auto_block(new_auto_body)

    existing_auto = extract_auto_block(existing_markdown)
    existing_manual = extract_manual_block(existing_markdown)

    placeholder = default_manual_body or _FALLBACK_MANUAL_BODY
    manual_body = existing_manual if existing_manual is not None else placeholder

    tampered = (
        existing_auto is not None
        and bool(last_known_auto_hash)
        and hash_auto_block(existing_auto) != last_known_auto_hash
        # Migration tolerance: v0.1.x stored hashes of unstripped bodies.
        # Accept either the new (stripped) or legacy (unstripped + "\n")
        # variant so existing setups don't show a wave of false conflicts
        # on the first v0.2.1 sync. New writes always use the stripped
        # variant, so the legacy check naturally goes away.
        and _legacy_unstripped_hash(existing_auto + "\n") != last_known_auto_hash
        and _legacy_unstripped_hash(existing_auto) != last_known_auto_hash
    )

    auto_changed = existing_auto is None or hash_auto_block(existing_auto) != new_hash

    return MergeResult(
        body=build_page_body(new_auto_body, manual_body),
        auto_hash=new_hash,
        auto_block_changed=auto_changed,
        manual_block_tampered=tampered,
    )
