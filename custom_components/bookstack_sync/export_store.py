"""
Persistent state for the markdown back-export (issue #61, A4).

Disjoint from the sync mapping store: the export tracks one entry per
HA object id (``device:UUID``, ``area:UUID``, …) recording which file we
wrote, when, and the SHA-256 of the full file content. The hash powers
idempotency — the second export run re-skips every file whose content
has not changed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

from homeassistant.helpers.storage import Store

from .const import EXPORT_STORAGE_KEY_FMT, STORAGE_VERSION

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


@dataclass
class ExportEntry:
    """One exported page's storage row."""

    page_id: int
    filename: str  # path relative to the configured export root
    content_hash: str  # SHA-256 of the full written file (frontmatter + body)
    last_exported: str  # ISO-8601


@dataclass
class ExportState:
    """The whole persisted state for one config entry."""

    exports: dict[str, ExportEntry] = field(default_factory=dict)


class BookStackSyncExportStore:
    """Thin async wrapper around HA's Store helper, mirroring BookStackSyncStore."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialise the per-entry storage handle."""
        self._store: Store[dict] = Store(
            hass,
            STORAGE_VERSION,
            EXPORT_STORAGE_KEY_FMT.format(entry_id=entry_id),
        )
        self._state: ExportState = ExportState()
        self._loaded = False

    async def async_load(self) -> None:
        """Load the export ledger from disk on first call; no-op afterwards."""
        if self._loaded:
            return
        raw = await self._store.async_load() or {}
        exports_raw = raw.get("exports", {}) or {}
        known = set(ExportEntry.__dataclass_fields__)
        exports: dict[str, ExportEntry] = {}
        for key, value in exports_raw.items():
            filtered = {k: v for k, v in value.items() if k in known}
            try:
                exports[key] = ExportEntry(**filtered)
            except TypeError:
                # Forward-compat: skip rows we can't deserialise rather
                # than abort the whole export.
                continue
        self._state = ExportState(exports=exports)
        self._loaded = True

    async def async_save(self) -> None:
        """Persist the current ledger."""
        await self._store.async_save(
            {
                "exports": {
                    key: asdict(value) for key, value in self._state.exports.items()
                },
            },
        )

    def get(self, key: str) -> ExportEntry | None:
        """Return the entry for ``key`` or None if unknown."""
        return self._state.exports.get(key)

    def set(self, key: str, entry: ExportEntry) -> None:
        """Insert or replace an entry in-memory (call async_save to persist)."""
        self._state.exports[key] = entry

    def remove(self, key: str) -> None:
        """Drop an entry from the ledger (call async_save to persist)."""
        self._state.exports.pop(key, None)

    def all(self) -> dict[str, ExportEntry]:
        """Return a shallow copy of all known entries."""
        return dict(self._state.exports)
