"""Custom types for bookstack_sync."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.loader import Integration

    from .api import BookStackApiClient
    from .coordinator import BookStackSyncCoordinator
    from .store import BookStackSyncStore


type BookStackSyncConfigEntry = ConfigEntry[BookStackSyncData]


@dataclass
class BookStackSyncData:
    """Runtime data for the BookStack Sync integration."""

    client: BookStackApiClient
    coordinator: BookStackSyncCoordinator
    integration: Integration
    store: BookStackSyncStore
