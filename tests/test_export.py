"""End-to-end tests for the markdown back-export (issue #61, A4/A6/A10).

We mock the BookStack API client at the surface level and use the real
sync + export stores so the idempotency and rename paths exercise the
actual storage helpers.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bookstack_sync.api import (
    BookStackApiCommunicationError,
)
from custom_components.bookstack_sync.const import (
    AUTO_BEGIN_MARKER,
    AUTO_END_MARKER,
    CONF_BASE_URL,
    CONF_BOOK_ID,
    CONF_TOKEN_ID,
    CONF_TOKEN_SECRET,
    CONF_VERIFY_SSL,
    DOMAIN,
    MANUAL_BEGIN_MARKER,
    MANUAL_END_MARKER,
    TAG_NAME,
    TAG_VALUE_MANAGED,
    TAG_VALUE_ORPHANED,
)
from custom_components.bookstack_sync.export import export
from custom_components.bookstack_sync.export_store import BookStackSyncExportStore
from custom_components.bookstack_sync.store import BookStackSyncStore, PageMapping

if TYPE_CHECKING:
    from pathlib import Path

    from homeassistant.core import HomeAssistant


def _make_page(  # noqa: PLR0913 - test helper; explicit args beat **kwargs for readability
    page_id: int,
    name: str,
    auto_body: str,
    manual_body: str = "",
    *,
    chapter_id: int | None = 200,
    tags: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build a fake BookStack page response with proper marker blocks."""
    if tags is None:
        tags = [{"name": TAG_NAME, "value": TAG_VALUE_MANAGED}]
    md = (
        f"{AUTO_BEGIN_MARKER}\n{auto_body}\n{AUTO_END_MARKER}\n\n"
        f"{MANUAL_BEGIN_MARKER}\n{manual_body}\n{MANUAL_END_MARKER}\n"
    )
    return {
        "id": page_id,
        "name": name,
        "chapter_id": chapter_id,
        "tags": tags,
        "markdown": md,
        "created_at": "2026-04-15T09:00:00+00:00",
        "updated_at": "2026-04-28T19:42:00+00:00",
    }


@pytest.fixture
def fake_client_state() -> dict[str, Any]:
    """Mutable state seeded into the fake client."""
    return {
        "pages": {},  # page_id -> page dict
        "chapters": [{"id": 200, "name": "Devices"}, {"id": 201, "name": "Areas"}],
        "page_errors": {},  # page_id -> Exception to raise on get_page
    }


@pytest.fixture
def fake_client(fake_client_state: dict[str, Any]) -> MagicMock:
    """A MagicMock mimicking BookStackApiClient.get_page + list_chapters."""
    state = fake_client_state

    async def list_chapters(_book_id: int) -> list[dict[str, Any]]:
        return list(state["chapters"])

    async def get_page(page_id: int) -> dict[str, Any]:
        err = state["page_errors"].get(page_id)
        if err is not None:
            raise err
        return state["pages"][page_id]

    client = MagicMock()
    client.list_chapters = AsyncMock(side_effect=list_chapters)
    client.get_page = AsyncMock(side_effect=get_page)
    return client


@pytest.fixture
async def export_entry(
    hass: HomeAssistant,
    fake_client: MagicMock,
) -> tuple[MockConfigEntry, BookStackSyncStore, BookStackSyncExportStore]:
    """A MockConfigEntry with runtime_data wired up for the export module."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="BookStack: test",
        unique_id="http://bookstack.local",
        data={
            CONF_BASE_URL: "http://bookstack.local",
            CONF_TOKEN_ID: "tid",
            CONF_TOKEN_SECRET: "tsec",
            CONF_BOOK_ID: 1,
            CONF_VERIFY_SSL: True,
        },
        options={},
    )
    entry.add_to_hass(hass)
    sync_store = BookStackSyncStore(hass, entry.entry_id)
    await sync_store.async_load()
    export_store = BookStackSyncExportStore(hass, entry.entry_id)
    await export_store.async_load()
    runtime = SimpleNamespace(
        client=fake_client,
        store=sync_store,
        export_store=export_store,
    )
    entry.runtime_data = runtime
    return entry, sync_store, export_store


def _seed_managed_page(  # noqa: PLR0913 - test helper, keyword-only beyond positional (state, store)
    state: dict[str, Any],
    sync_store: BookStackSyncStore,
    *,
    mapping_key: str,
    page_id: int,
    name: str,
    auto_body: str = "Auto content here",
    manual_body: str = "User notes",
    chapter_id: int | None = 200,
    tombstoned_at: str | None = None,
    tag_value: str = TAG_VALUE_MANAGED,
) -> None:
    """Convenience: register one page in both the fake client and the sync store."""
    state["pages"][page_id] = _make_page(
        page_id,
        name,
        auto_body,
        manual_body,
        chapter_id=chapter_id,
        tags=[{"name": TAG_NAME, "value": tag_value}],
    )
    sync_store.set(
        mapping_key,
        PageMapping(
            page_id=page_id,
            auto_block_hash="x",
            last_seen="2026-05-01T03:00:00+00:00",
            tombstoned_at=tombstoned_at,
            hash_origin="bookstack",
        ),
    )


async def test_happy_path_writes_three_files(
    hass: HomeAssistant,
    tmp_path: Path,
    fake_client_state: dict[str, Any],
    export_entry: tuple[MockConfigEntry, BookStackSyncStore, BookStackSyncExportStore],
) -> None:
    """Three managed pages → three files with frontmatter + body + index."""
    entry, sync_store, _ = export_entry
    _seed_managed_page(
        fake_client_state,
        sync_store,
        mapping_key="device:a",
        page_id=10,
        name="Light Living Room",
    )
    _seed_managed_page(
        fake_client_state,
        sync_store,
        mapping_key="device:b",
        page_id=11,
        name="Sensor Hallway",
    )
    _seed_managed_page(
        fake_client_state,
        sync_store,
        mapping_key="area:living_room",
        page_id=12,
        name="Living Room",
        chapter_id=201,
    )

    result = await export(hass, entry, output_path=tmp_path)

    assert result.written == 3
    assert result.unchanged == 0
    assert result.errors == 0
    devices_dir = tmp_path / "devices"
    areas_dir = tmp_path / "areas"
    assert (devices_dir / "light-living-room.md").exists()
    assert (devices_dir / "sensor-hallway.md").exists()
    assert (areas_dir / "living-room.md").exists()
    assert (tmp_path / "_index.md").exists()
    # Frontmatter present, body separator present.
    body = (devices_dir / "light-living-room.md").read_text(encoding="utf-8")
    assert body.startswith("---\n")
    assert "title: Light Living Room" in body
    assert "tombstoned: false" in body
    assert "Auto content here" in body
    assert "User notes" in body


async def test_idempotency_second_run_writes_nothing(
    hass: HomeAssistant,
    tmp_path: Path,
    fake_client_state: dict[str, Any],
    export_entry: tuple[MockConfigEntry, BookStackSyncStore, BookStackSyncExportStore],
) -> None:
    """Second export with no changes → 0 written, all unchanged."""
    entry, sync_store, _ = export_entry
    _seed_managed_page(
        fake_client_state,
        sync_store,
        mapping_key="device:a",
        page_id=10,
        name="Light",
    )

    first = await export(hass, entry, output_path=tmp_path)
    assert first.written == 1

    second = await export(hass, entry, output_path=tmp_path)
    assert second.written == 0
    assert second.unchanged == 1


async def test_manual_block_change_rewrites_file(
    hass: HomeAssistant,
    tmp_path: Path,
    fake_client_state: dict[str, Any],
    export_entry: tuple[MockConfigEntry, BookStackSyncStore, BookStackSyncExportStore],
) -> None:
    """User-edited MANUAL block → file rewritten on next export."""
    entry, sync_store, _ = export_entry
    _seed_managed_page(
        fake_client_state,
        sync_store,
        mapping_key="device:a",
        page_id=10,
        name="Light",
        manual_body="Initial notes",
    )
    await export(hass, entry, output_path=tmp_path)

    # User edits MANUAL block in BookStack — fake client's page now has
    # different markdown.
    fake_client_state["pages"][10] = _make_page(
        10,
        "Light",
        "Auto content here",
        "Updated notes after user edit",
    )

    second = await export(hass, entry, output_path=tmp_path)
    assert second.written == 1
    assert second.unchanged == 0
    body = (tmp_path / "devices" / "light.md").read_text(encoding="utf-8")
    assert "Updated notes after user edit" in body
    assert "Initial notes" not in body


async def test_page_rename_writes_new_deletes_old(
    hass: HomeAssistant,
    tmp_path: Path,
    fake_client_state: dict[str, Any],
    export_entry: tuple[MockConfigEntry, BookStackSyncStore, BookStackSyncExportStore],
) -> None:
    """Page renamed in BookStack → new filename, old file removed."""
    entry, sync_store, _ = export_entry
    _seed_managed_page(
        fake_client_state,
        sync_store,
        mapping_key="device:a",
        page_id=10,
        name="Light",
    )
    await export(hass, entry, output_path=tmp_path)
    old_path = tmp_path / "devices" / "light.md"
    assert old_path.exists()

    # Rename in BookStack.
    fake_client_state["pages"][10]["name"] = "Ceiling Lamp"

    second = await export(hass, entry, output_path=tmp_path)
    assert second.written == 1
    assert second.deleted_old == 1
    assert not old_path.exists()
    assert (tmp_path / "devices" / "ceiling-lamp.md").exists()


async def test_slug_collision_uses_suffix(
    hass: HomeAssistant,
    tmp_path: Path,
    fake_client_state: dict[str, Any],
    export_entry: tuple[MockConfigEntry, BookStackSyncStore, BookStackSyncExportStore],
) -> None:
    """Two devices titled ``Light`` → ``light.md`` and ``light-2.md``."""
    entry, sync_store, _ = export_entry
    _seed_managed_page(
        fake_client_state,
        sync_store,
        mapping_key="device:a",
        page_id=10,
        name="Light",
    )
    _seed_managed_page(
        fake_client_state,
        sync_store,
        mapping_key="device:b",
        page_id=11,
        name="Light",
    )

    await export(hass, entry, output_path=tmp_path)

    devices = tmp_path / "devices"
    assert (devices / "light.md").exists()
    assert (devices / "light-2.md").exists()


async def test_special_chars_in_title_produce_ascii_filename(
    hass: HomeAssistant,
    tmp_path: Path,
    fake_client_state: dict[str, Any],
    export_entry: tuple[MockConfigEntry, BookStackSyncStore, BookStackSyncExportStore],
) -> None:
    """Umlauts + emoji + slashes → ASCII filename."""
    entry, sync_store, _ = export_entry
    _seed_managed_page(
        fake_client_state,
        sync_store,
        mapping_key="device:a",
        page_id=10,
        name="Büro/Wärmesensor 💡",
    )
    await export(hass, entry, output_path=tmp_path)
    assert (tmp_path / "devices" / "buero-waermesensor.md").exists()


async def test_tombstoned_page_is_exported_with_flag(
    hass: HomeAssistant,
    tmp_path: Path,
    fake_client_state: dict[str, Any],
    export_entry: tuple[MockConfigEntry, BookStackSyncStore, BookStackSyncExportStore],
) -> None:
    """Soft-deleted pages get ``tombstoned: true`` and stay at their old filename."""
    entry, sync_store, _ = export_entry
    _seed_managed_page(
        fake_client_state,
        sync_store,
        mapping_key="device:a",
        page_id=10,
        name="Light",
    )
    await export(hass, entry, output_path=tmp_path)
    pre_tombstone = (tmp_path / "devices" / "light.md").read_text(encoding="utf-8")
    assert "tombstoned: false" in pre_tombstone

    # Mark as tombstoned in both stores: tag flips, mapping carries timestamp.
    fake_client_state["pages"][10]["tags"] = [
        {"name": TAG_NAME, "value": TAG_VALUE_ORPHANED},
    ]
    sync_store.set(
        "device:a",
        PageMapping(
            page_id=10,
            auto_block_hash="x",
            last_seen="2026-05-01T03:00:00+00:00",
            tombstoned_at="2026-05-01T04:00:00+00:00",
            hash_origin="bookstack",
        ),
    )
    second = await export(hass, entry, output_path=tmp_path)
    assert second.written == 1
    post = (tmp_path / "devices" / "light.md").read_text(encoding="utf-8")
    assert "tombstoned: true" in post
    # Filename did not change.
    assert (tmp_path / "devices" / "light.md").exists()


async def test_partial_failure_continues_with_others(
    hass: HomeAssistant,
    tmp_path: Path,
    fake_client_state: dict[str, Any],
    export_entry: tuple[MockConfigEntry, BookStackSyncStore, BookStackSyncExportStore],
) -> None:
    """One get_page raises → other pages still exported, error counter==1."""
    entry, sync_store, _ = export_entry
    _seed_managed_page(
        fake_client_state,
        sync_store,
        mapping_key="device:a",
        page_id=10,
        name="Light",
    )
    _seed_managed_page(
        fake_client_state,
        sync_store,
        mapping_key="device:b",
        page_id=11,
        name="Sensor",
    )
    fake_client_state["page_errors"][11] = BookStackApiCommunicationError("oops")

    result = await export(hass, entry, output_path=tmp_path)
    assert result.written == 1
    assert result.errors == 1
    assert (tmp_path / "devices" / "light.md").exists()
    assert not (tmp_path / "devices" / "sensor.md").exists()


async def test_foreign_pages_are_skipped(
    hass: HomeAssistant,
    tmp_path: Path,
    fake_client_state: dict[str, Any],
    export_entry: tuple[MockConfigEntry, BookStackSyncStore, BookStackSyncExportStore],
) -> None:
    """Pages without bookstack_sync=managed/orphaned tag are ignored."""
    entry, sync_store, _ = export_entry
    fake_client_state["pages"][10] = _make_page(
        10,
        "Foreign page",
        "Some content",
        "Some manual content",
        chapter_id=200,
        tags=[{"name": "user_topic", "value": "random"}],
    )
    sync_store.set(
        "device:foreign",
        PageMapping(
            page_id=10,
            auto_block_hash="x",
            hash_origin="bookstack",
        ),
    )
    result = await export(hass, entry, output_path=tmp_path)
    assert result.written == 0
    devices_dir = tmp_path / "devices"
    assert not devices_dir.exists() or not list(devices_dir.glob("*.md"))


async def test_dry_run_writes_nothing_to_disk(
    hass: HomeAssistant,
    tmp_path: Path,
    fake_client_state: dict[str, Any],
    export_entry: tuple[MockConfigEntry, BookStackSyncStore, BookStackSyncExportStore],
) -> None:
    """``dry_run=True`` reports counts but creates no files."""
    entry, sync_store, _ = export_entry
    _seed_managed_page(
        fake_client_state,
        sync_store,
        mapping_key="device:a",
        page_id=10,
        name="Light",
    )

    result = await export(hass, entry, output_path=tmp_path, dry_run=True)
    assert result.written == 1
    # tmp_path itself exists (pytest fixture) but no files were created.
    assert not list(tmp_path.rglob("*.md"))  # noqa: ASYNC240 - test-only filesystem assertion
