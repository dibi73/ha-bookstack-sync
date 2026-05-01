"""Unit tests for the frontmatter builder (issue #61, A3)."""

from __future__ import annotations

import yaml

from custom_components.bookstack_sync.frontmatter import (
    ExportFrontmatter,
    build,
    parse_mapping_key,
    to_yaml,
)


class TestParseMappingKey:
    """The mapping-key parser splits ``device:UUID`` and friends."""

    def test_device_key(self) -> None:
        """Device keys keep both halves."""
        assert parse_mapping_key("device:abc123") == ("device", "abc123")

    def test_overview_underscore_key(self) -> None:
        """``overview:_`` collapses the placeholder id to None."""
        assert parse_mapping_key("overview:_") == ("overview", None)

    def test_bundle_key(self) -> None:
        """Bundle keys carry a string id."""
        assert parse_mapping_key("bundle:automations") == (
            "bundle",
            "automations",
        )

    def test_no_colon_returns_kind_and_none(self) -> None:
        """A bare key (no colon) gets a None id."""
        assert parse_mapping_key("standalone") == ("standalone", None)


class TestBuild:
    """The frontmatter builder pulls fields from a BookStack page response."""

    def _sample_page(self) -> dict:
        return {
            "id": 142,
            "name": "Bewegungsmelder Gang",
            "chapter_id": 200,
            "tags": [
                {"name": "bookstack_sync", "value": "managed"},
                {"name": "user_topic", "value": "sicherheit"},
                {"name": "user_topic", "value": "zigbee"},
            ],
            "created_at": "2026-04-15T09:00:00+00:00",
            "updated_at": "2026-04-28T19:42:00+00:00",
        }

    def test_typical_device_page(self) -> None:
        """All expected fields are populated."""
        fm = build(
            mapping_key="device:abc123",
            bookstack_page=self._sample_page(),
            book_id=1,
            chapter_lookup={200: "Devices"},
            tombstoned=False,
            last_synced="2026-05-01T03:00:00+00:00",
        )
        assert fm.title == "Bewegungsmelder Gang"
        assert fm.bookstack_page_id == 142
        assert fm.bookstack_book_id == 1
        assert fm.bookstack_chapter_id == 200
        assert fm.bookstack_chapter == "Devices"
        # The internal bookstack_sync tag is stripped; user tags remain.
        assert fm.bookstack_tags == ["sicherheit", "zigbee"]
        assert fm.ha_object_kind == "device"
        assert fm.ha_object_id == "abc123"
        assert fm.tombstoned is False

    def test_overview_page(self) -> None:
        """Book-level pages have None for chapter id and chapter name."""
        page = self._sample_page()
        page["chapter_id"] = 0  # BookStack uses 0 / null for book-level
        fm = build(
            mapping_key="overview:_",
            bookstack_page=page,
            book_id=1,
            chapter_lookup={},
            tombstoned=False,
            last_synced="2026-05-01T03:00:00+00:00",
        )
        assert fm.bookstack_chapter_id is None
        assert fm.bookstack_chapter is None
        assert fm.ha_object_kind == "overview"
        assert fm.ha_object_id is None

    def test_tombstoned_page(self) -> None:
        """Tombstone state is propagated to the frontmatter."""
        fm = build(
            mapping_key="device:abc",
            bookstack_page=self._sample_page(),
            book_id=1,
            chapter_lookup={200: "Devices"},
            tombstoned=True,
            last_synced="2026-05-01T03:00:00+00:00",
        )
        assert fm.tombstoned is True


class TestToYaml:
    """``to_yaml`` is deterministic and round-trips through ``yaml.safe_load``."""

    def _fm(self) -> ExportFrontmatter:
        return ExportFrontmatter(
            title="Bewegungsmelder Gang",
            bookstack_page_id=142,
            bookstack_book_id=1,
            bookstack_chapter_id=200,
            bookstack_chapter="Devices",
            bookstack_tags=["sicherheit", "zigbee"],
            bookstack_created_at="2026-04-15T09:00:00+00:00",
            bookstack_updated_at="2026-04-28T19:42:00+00:00",
            ha_object_kind="device",
            ha_object_id="abc123",
            last_synced="2026-05-01T03:00:00+00:00",
            tombstoned=False,
        )

    def test_deterministic(self) -> None:
        """Same input → byte-identical output."""
        fm = self._fm()
        first = to_yaml(fm, "deadbeef")
        second = to_yaml(fm, "deadbeef")
        assert first == second

    def test_round_trip(self) -> None:
        """``yaml.safe_load(to_yaml(fm))`` reconstructs the same dict."""
        fm = self._fm()
        out = to_yaml(fm, "deadbeef")
        loaded = yaml.safe_load(out)
        assert loaded["title"] == "Bewegungsmelder Gang"
        assert loaded["bookstack_page_id"] == 142
        assert loaded["bookstack_tags"] == ["sicherheit", "zigbee"]
        assert loaded["ha_object_kind"] == "device"
        assert loaded["content_hash"] == "deadbeef"
        assert loaded["tombstoned"] is False

    def test_unicode_preserved(self) -> None:
        """Umlauts stay as umlauts (allow_unicode=True)."""
        fm = self._fm()
        fm = ExportFrontmatter(
            **{**fm.__dict__, "title": "Büro Wärmesensor"},
        )
        out = to_yaml(fm, "x")
        assert "Büro Wärmesensor" in out
