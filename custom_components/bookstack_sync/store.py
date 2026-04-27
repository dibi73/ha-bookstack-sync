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
    """Tracks one synced page so we can update instead of duplicate."""

    page_id: int
    auto_block_hash: str = ""
    last_seen: str | None = None  # ISO timestamp of last successful sync
    tombstoned_at: str | None = None  # ISO timestamp; set when soft-deleted


@dataclass
class StoredState:
    """Whole persisted state per config entry."""

    pages: dict[str, PageMapping] = field(default_factory=dict)


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
        self._state = StoredState(
            pages={key: PageMapping(**value) for key, value in pages_raw.items()},
        )
        self._loaded = True

    async def async_save(self) -> None:
        """Persist the current mapping state."""
        await self._store.async_save(
            {"pages": {key: asdict(value) for key, value in self._state.pages.items()}},
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
