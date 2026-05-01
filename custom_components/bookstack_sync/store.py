"""Persistent mapping between HA objects and BookStack pages."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY_FMT, STORAGE_VERSION

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


@dataclass
class PageMapping:
    """
    Tracks one synced page so we can update instead of duplicate.

    ``hash_origin`` (issue #58) is ``"write"`` for hashes computed from
    what we sent to BookStack and ``"bookstack"`` for hashes computed
    from what BookStack returned in the create/update response. Round-
    trip hashes survive BookStack's markdown normalisation; write-side
    hashes can drift when BookStack normalises whitespace / line endings
    / Unicode and produce false-positive tampering reports.

    Migration: existing entries default to ``"write"``. The next sync
    suppresses tampering detection on these and stores a
    ``"bookstack"``-origin hash, settling the mapping into the new
    regime within one sync cycle.
    """

    page_id: int
    auto_block_hash: str = ""
    last_seen: str | None = None  # ISO timestamp of last successful sync
    tombstoned_at: str | None = None  # ISO timestamp; set when soft-deleted
    hash_origin: str = "write"  # "write" (legacy) or "bookstack" (round-trip)


@dataclass
class StoredState:
    """Whole persisted state per config entry."""

    pages: dict[str, PageMapping] = field(default_factory=dict)
    chapters: dict[str, int] = field(default_factory=dict)


class BookStackSyncStore:
    """
    Thin async wrapper around HA's Store helper.

    Mapping key format: ``{kind}:{stable_id}`` (e.g. ``device:abc123``,
    ``area:living_room``, ``overview:_``). Values carry the BookStack page id
    plus the hash of the auto-block we last wrote to detect manual edits.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialise the per-entry storage handle."""
        self._store: Store[dict] = Store(
            hass,
            STORAGE_VERSION,
            STORAGE_KEY_FMT.format(entry_id=entry_id),
        )
        self._state: StoredState = StoredState()
        self._loaded = False

    async def async_load(self) -> None:
        """Load mappings from disk on first call; no-op afterwards."""
        if self._loaded:
            return
        raw = await self._store.async_load() or {}
        pages_raw = raw.get("pages", {}) or {}
        chapters_raw = raw.get("chapters", {}) or {}
        # Migration: pre-v0.11 storage doesn't have ``hash_origin``.
        # Drop unknown fields gracefully (forward-compat too).
        known_fields = set(PageMapping.__dataclass_fields__)
        pages: dict[str, PageMapping] = {}
        for key, value in pages_raw.items():
            filtered = {k: v for k, v in value.items() if k in known_fields}
            pages[key] = PageMapping(**filtered)
        self._state = StoredState(
            pages=pages,
            chapters={key: int(value) for key, value in chapters_raw.items()},
        )
        self._loaded = True

    async def async_save(self) -> None:
        """Persist the current mapping state."""
        await self._store.async_save(
            {
                "pages": {
                    key: asdict(value) for key, value in self._state.pages.items()
                },
                "chapters": dict(self._state.chapters),
            },
        )

    def get(self, key: str) -> PageMapping | None:
        """Return the mapping for ``key`` or None if unknown."""
        return self._state.pages.get(key)

    def set(self, key: str, mapping: PageMapping) -> None:
        """Insert or replace a mapping in-memory (call async_save to persist)."""
        self._state.pages[key] = mapping

    def all(self) -> dict[str, PageMapping]:
        """Return a shallow copy of all known mappings."""
        return dict(self._state.pages)

    def get_chapter(self, key: str) -> int | None:
        """Return the BookStack chapter id for ``key`` (e.g. ``areas``)."""
        return self._state.chapters.get(key)

    def set_chapter(self, key: str, chapter_id: int) -> None:
        """Insert or replace the chapter id for ``key`` (call async_save to persist)."""
        self._state.chapters[key] = chapter_id

    def all_chapters(self) -> dict[str, int]:
        """Return a shallow copy of the persisted chapter map."""
        return dict(self._state.chapters)
