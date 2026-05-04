"""Tests for the marker-block merge logic.

These exercise the bug paths we hit in v0.2.0 / v0.2.1 (false-positive
tampering due to hash asymmetry) plus the round-trip property: rendering
through ``build_page_body`` and reading back via ``extract_auto_block``
must produce a string whose hash matches the stored hash.
"""

from __future__ import annotations

from custom_components.bookstack_sync.const import (
    AUTO_BEGIN_MARKER,
    AUTO_END_MARKER,
    MANUAL_BEGIN_MARKER,
    MANUAL_END_MARKER,
)
from custom_components.bookstack_sync.merge import (
    _legacy_unstripped_hash,
    build_page_body,
    extract_auto_block,
    extract_manual_block,
    hash_auto_block,
    merge_page,
)


class TestHashAutoBlock:
    """Hash must be whitespace-normalised (write/read symmetric)."""

    def test_hash_is_strip_invariant(self) -> None:
        # Regression: this was the v0.2.0 bug. Renderer output ended with
        # "\n", build_page_body stripped it. Hashes were computed over
        # different bytes -> false tampering.
        assert hash_auto_block("hello") == hash_auto_block("hello\n")
        assert hash_auto_block("hello") == hash_auto_block("\n\nhello\n\n")
        assert hash_auto_block("hello") == hash_auto_block("hello   ")

    def test_different_content_hashes_differently(self) -> None:
        assert hash_auto_block("hello") != hash_auto_block("world")

    def test_empty_string_is_stable(self) -> None:
        assert hash_auto_block("") == hash_auto_block("\n")
        assert hash_auto_block("") == hash_auto_block("   ")

    def test_crlf_vs_lf_invariant(self) -> None:
        """v0.13.3: BookStack stores CRLF, HA writes LF — hashes must match.

        Regression for the 260+ false-positive tampering reports the user
        hit on every sync after v0.13.0. ``\\r\\n`` and bare ``\\r`` are
        normalised to ``\\n`` before hashing, otherwise every page would
        be re-flagged as tampered on each sync.
        """
        assert hash_auto_block("LineA\nLineB") == hash_auto_block("LineA\r\nLineB")
        assert hash_auto_block("LineA\nLineB") == hash_auto_block("LineA\rLineB")
        assert hash_auto_block("a\nb\nc") == hash_auto_block("a\r\nb\r\nc")

    def test_unicode_nfc_vs_nfd_invariant(self) -> None:
        """v0.13.3: NFC and NFD-encoded umlauts hash identically.

        BookStack's editor normalises to NFC. HA's render output sometimes
        carries NFD-encoded characters from underlying registry strings;
        without NFC normalisation in the hash, those pages would
        false-positive on every sync.
        """
        # "é" as a single NFC code point vs "e" + combining acute accent.
        nfc = "Café"
        nfd = "Café"
        assert nfc != nfd  # raw bytes differ
        assert hash_auto_block(nfc) == hash_auto_block(nfd)


class TestRoundTrip:
    """build_page_body + extract_auto_block must round-trip the AUTO body."""

    def test_basic_round_trip(self) -> None:
        body = "Some markdown content\nwith two lines"
        full = build_page_body(body, "")
        extracted = extract_auto_block(full)
        assert extracted == body

    def test_round_trip_preserves_hash(self) -> None:
        # Regression v0.2.1: the hash computed at write time must match the
        # hash computed when reading back from the same page body.
        body = "Auto content\nwith trailing newline\n"
        full = build_page_body(body, "")
        extracted = extract_auto_block(full)
        assert hash_auto_block(body) == hash_auto_block(extracted)

    def test_manual_block_preserved(self) -> None:
        manual = "User notes\n- bullet\n- another"
        full = build_page_body("auto", manual)
        assert extract_manual_block(full) == manual

    def test_extract_returns_none_when_marker_missing(self) -> None:
        assert extract_auto_block("no markers here") is None
        assert extract_manual_block("no markers here") is None

    def test_extract_returns_none_for_empty_input(self) -> None:
        assert extract_auto_block(None) is None
        assert extract_auto_block("") is None
        assert extract_manual_block(None) is None
        assert extract_manual_block("") is None


class TestMergePage:
    """End-to-end merge behaviour."""

    def test_first_write_yields_default_manual(self) -> None:
        # No existing markdown means new page; default manual is generated.
        result = merge_page(
            "auto body", existing_markdown=None, last_known_auto_hash=None
        )
        assert AUTO_BEGIN_MARKER in result.body
        assert AUTO_END_MARKER in result.body
        assert MANUAL_BEGIN_MARKER in result.body
        assert MANUAL_END_MARKER in result.body
        assert "auto body" in result.body
        assert result.manual_block_tampered is False
        assert result.auto_block_changed is True

    def test_unchanged_auto_with_matching_hash(self) -> None:
        body = "auto content"
        existing_full = build_page_body(body, "user notes")
        result = merge_page(
            new_auto_body=body,
            existing_markdown=existing_full,
            last_known_auto_hash=hash_auto_block(body),
        )
        assert result.manual_block_tampered is False
        assert result.auto_block_changed is False
        # Manual block must survive verbatim
        assert "user notes" in result.body

    def test_tampered_when_existing_auto_modified(self) -> None:
        original = "v1 auto content"
        tampered = "MAN-EDITED auto content"
        existing_full = build_page_body(tampered, "user notes")
        result = merge_page(
            new_auto_body="v2 auto content",
            existing_markdown=existing_full,
            # last_known_hash is for the original (v1), not the tampered version
            last_known_auto_hash=hash_auto_block(original),
        )
        assert result.manual_block_tampered is True

    def test_legacy_unstripped_hash_does_not_trigger_tampered(self) -> None:
        # Regression v0.2.1: setups upgrading from v0.1.x have stored hashes
        # of unstripped bodies. The new tampered check must accept the legacy
        # variant so existing pages don't show as tampered after upgrade.
        body = "auto with trailing\n"
        existing_full = build_page_body(body, "user notes")
        legacy_hash = _legacy_unstripped_hash(body)
        result = merge_page(
            new_auto_body=body,
            existing_markdown=existing_full,
            last_known_auto_hash=legacy_hash,
        )
        assert result.manual_block_tampered is False

    def test_legacy_unstripped_no_newline_variant_also_accepted(self) -> None:
        # Some renderers (the v0.1.x overview) produced output WITHOUT a
        # trailing newline. Their stored legacy hash is just hash(body).
        body = "auto without trailing"
        existing_full = build_page_body(body, "user notes")
        legacy_hash = _legacy_unstripped_hash(body)
        result = merge_page(
            new_auto_body=body,
            existing_markdown=existing_full,
            last_known_auto_hash=legacy_hash,
        )
        assert result.manual_block_tampered is False

    def test_no_last_known_hash_means_not_tampered(self) -> None:
        # First sync: no last_known_hash, can't be tampered.
        existing_full = build_page_body("auto", "user notes")
        result = merge_page(
            new_auto_body="auto",
            existing_markdown=existing_full,
            last_known_auto_hash=None,
        )
        assert result.manual_block_tampered is False


class TestMarkersMissing:
    """v0.14.9: WYSIWYG-toggle round-trip drops the marker comments.

    BookStack's TinyMCE editor converts Markdown to HTML when toggled on
    and back to Markdown when toggled off; HTML comments
    (``<!-- BEGIN AUTO-GENERATED -->`` etc) get stripped in that
    round-trip. The next sync would otherwise overwrite the user's
    edits with a fresh AUTO+placeholder MANUAL pair. ``markers_missing``
    detects that and lets the caller skip + raise a repair issue.
    """

    def test_both_markers_present_means_not_missing(self) -> None:
        existing_full = build_page_body("auto", "user notes")
        result = merge_page(
            new_auto_body="auto",
            existing_markdown=existing_full,
            last_known_auto_hash=hash_auto_block("auto"),
        )
        assert result.markers_missing is False

    def test_no_markers_with_known_hash_flags_missing(self) -> None:
        # Page has content but no markers anywhere — typical WYSIWYG
        # round-trip output.
        result = merge_page(
            new_auto_body="auto fresh",
            existing_markdown="Just plain text\n\nfrom WYSIWYG round-trip",
            last_known_auto_hash="some-old-hash",
        )
        assert result.markers_missing is True

    def test_only_auto_marker_missing_flags_missing(self) -> None:
        # Partial damage: MANUAL block survived, AUTO didn't.
        existing = (
            "Just plain text from WYSIWYG\n\n"
            f"{MANUAL_BEGIN_MARKER}\nuser notes\n{MANUAL_END_MARKER}\n"
        )
        result = merge_page(
            new_auto_body="auto fresh",
            existing_markdown=existing,
            last_known_auto_hash="some-old-hash",
        )
        assert result.markers_missing is True

    def test_only_manual_marker_missing_flags_missing(self) -> None:
        # Partial damage: AUTO block survived, MANUAL didn't.
        existing = (
            f"{AUTO_BEGIN_MARKER}\nauto stuff\n{AUTO_END_MARKER}\n\n"
            "Just plain text from WYSIWYG\n"
        )
        result = merge_page(
            new_auto_body="auto stuff",
            existing_markdown=existing,
            last_known_auto_hash=hash_auto_block("auto stuff"),
        )
        assert result.markers_missing is True

    def test_no_markers_without_known_hash_does_not_flag(self) -> None:
        # No stored hash means this is a brand-new page (or first-ever
        # sync against an existing BookStack page with random content).
        # Don't false-flag those — the caller will create or merge in
        # the regular path.
        result = merge_page(
            new_auto_body="auto",
            existing_markdown="some pre-existing text",
            last_known_auto_hash=None,
        )
        assert result.markers_missing is False

    def test_empty_existing_markdown_does_not_flag(self) -> None:
        # New page (no body yet) is not "markers missing" — it's "no page".
        result = merge_page(
            new_auto_body="auto",
            existing_markdown="",
            last_known_auto_hash="some-hash",
        )
        assert result.markers_missing is False
        result_none = merge_page(
            new_auto_body="auto",
            existing_markdown=None,
            last_known_auto_hash="some-hash",
        )
        assert result_none.markers_missing is False
