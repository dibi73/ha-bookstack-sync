"""End-to-end tests for the sync orchestrator.

We mock the BookStackApiClient (not the lower aiohttp layer) so these
tests focus on the orchestration: chapter creation, two-pass overview
rendering, tombstoning, page mapping persistence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.helpers import (
    area_registry as ar,
)

from custom_components.bookstack_sync.const import (
    CHAPTER_KEY_AREAS,
    CHAPTER_KEY_DEVICES,
    CHAPTER_TITLE_AREAS,
    CHAPTER_TITLE_DEVICES,
)
from custom_components.bookstack_sync.store import BookStackSyncStore
from custom_components.bookstack_sync.sync import run_sync

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def _fake_client_with_state(state: dict[str, Any]) -> MagicMock:
    """A MagicMock that mimics BookStackApiClient and tracks created pages.

    state['next_id'] is incremented on every page/chapter create so we
    hand out unique IDs without colliding.
    """
    state.setdefault("pages", {})  # id -> {markdown, chapter_id, name}
    state.setdefault("chapters", {})  # id -> name
    state.setdefault("next_id", 100)

    client = MagicMock()

    async def list_chapters(book_id: int) -> list[dict[str, Any]]:
        return [{"id": cid, "name": name} for cid, name in state["chapters"].items()]

    async def create_chapter(
        book_id: int,
        name: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        cid = state["next_id"]
        state["next_id"] += 1
        state["chapters"][cid] = name
        return {"id": cid, "name": name}

    async def create_page(
        name: str,
        markdown: str,
        *,
        book_id: int | None = None,
        chapter_id: int | None = None,
    ) -> dict[str, Any]:
        pid = state["next_id"]
        state["next_id"] += 1
        state["pages"][pid] = {
            "id": pid,
            "name": name,
            "markdown": markdown,
            "chapter_id": chapter_id,
            "book_id": book_id,
        }
        return state["pages"][pid]

    async def get_page(page_id: int) -> dict[str, Any]:
        return state["pages"][page_id]

    async def update_page(
        page_id: int,
        name: str,
        markdown: str,
        *,
        chapter_id: int | None = None,
    ) -> dict[str, Any]:
        state["pages"][page_id]["name"] = name
        state["pages"][page_id]["markdown"] = markdown
        if chapter_id is not None:
            state["pages"][page_id]["chapter_id"] = chapter_id
        return state["pages"][page_id]

    client.list_chapters = AsyncMock(side_effect=list_chapters)
    client.create_chapter = AsyncMock(side_effect=create_chapter)
    client.create_page = AsyncMock(side_effect=create_page)
    client.get_page = AsyncMock(side_effect=get_page)
    client.update_page = AsyncMock(side_effect=update_page)
    return client


@pytest.fixture
async def store(hass: HomeAssistant) -> BookStackSyncStore:
    s = BookStackSyncStore(hass, entry_id="testentry")
    await s.async_load()
    return s


async def test_first_sync_creates_chapters_and_pages(
    hass: HomeAssistant,
    store: BookStackSyncStore,
) -> None:
    state: dict[str, Any] = {}
    client = _fake_client_with_state(state)

    # Seed minimal HA state
    area_reg = ar.async_get(hass)
    area_reg.async_create("Living Room")

    report = await run_sync(hass, client, store, book_id=1)

    # Both chapters auto-created
    assert CHAPTER_TITLE_AREAS in state["chapters"].values()
    assert CHAPTER_TITLE_DEVICES in state["chapters"].values()
    assert store.get_chapter(CHAPTER_KEY_AREAS) is not None
    assert store.get_chapter(CHAPTER_KEY_DEVICES) is not None

    # At least the overview + the four bundle pages + the area page were created
    assert len(report.created) >= 6
    assert report.errors == []


async def test_second_sync_with_unchanged_data_makes_no_changes(
    hass: HomeAssistant,
    store: BookStackSyncStore,
) -> None:
    state: dict[str, Any] = {}
    client = _fake_client_with_state(state)
    area_reg = ar.async_get(hass)
    area_reg.async_create("Living Room")

    # First sync: creates everything
    await run_sync(hass, client, store, book_id=1)

    # Second sync should be all-unchanged (this is the regression hot spot
    # we just fixed in v0.2.1: false-positive tampering after first write).
    report2 = await run_sync(hass, client, store, book_id=1)
    assert report2.created == []
    assert report2.skipped_conflict == []  # NO false positives
    assert report2.errors == []


async def test_dry_run_does_not_call_writes(
    hass: HomeAssistant,
    store: BookStackSyncStore,
) -> None:
    state: dict[str, Any] = {}
    client = _fake_client_with_state(state)

    report = await run_sync(hass, client, store, book_id=1, dry_run=True)
    assert report.dry_run is True
    client.create_page.assert_not_called()
    client.update_page.assert_not_called()
    client.create_chapter.assert_not_called()


async def test_chapter_reused_when_already_present(
    hass: HomeAssistant,
    store: BookStackSyncStore,
) -> None:
    # Seed BookStack with an existing "Räume" chapter from a previous setup.
    state: dict[str, Any] = {
        "chapters": {500: CHAPTER_TITLE_AREAS},
        "next_id": 600,
    }
    client = _fake_client_with_state(state)

    await run_sync(hass, client, store, book_id=1)

    # We must NOT have created a duplicate "Räume" chapter — only
    # "Geräte" was missing.
    chapter_titles = list(state["chapters"].values())
    assert chapter_titles.count(CHAPTER_TITLE_AREAS) == 1
    assert chapter_titles.count(CHAPTER_TITLE_DEVICES) == 1
    # Stored mapping points at the pre-existing chapter id (500), not a new one.
    assert store.get_chapter(CHAPTER_KEY_AREAS) == 500
