"""
Tests for the sync/preview buttons (#57, availability fix #208).

#208: ``available`` no longer follows ``coordinator.is_syncing`` - that
caused phantom "pressed" Logbook entries on every sync start/end (HA's
Logbook narrates any unavailable->available transition on a button as
a press, regardless of whether the press-timestamp actually changed).
These tests lock in that ``is_syncing`` no longer affects availability,
and that pressing still delegates to the coordinator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

from custom_components.bookstack_sync.button import (
    BookStackSyncPreviewButton,
    BookStackSyncRunNowButton,
)
from custom_components.bookstack_sync.coordinator import BookStackSyncCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


def _make_coordinator(
    hass: HomeAssistant,
    entry: MockConfigEntry,
) -> BookStackSyncCoordinator:
    return BookStackSyncCoordinator(hass, entry)


async def test_run_now_button_available_regardless_of_is_syncing(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """#208: a sync in flight must not flip the button's availability."""
    config_entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, config_entry)
    button = BookStackSyncRunNowButton(coordinator)

    coordinator.is_syncing = False
    assert button.available is True

    coordinator.is_syncing = True
    assert button.available is True


async def test_preview_button_available_regardless_of_is_syncing(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """#208: same guarantee for the dry-run/preview button."""
    config_entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, config_entry)
    button = BookStackSyncPreviewButton(coordinator)

    coordinator.is_syncing = True
    assert button.available is True


async def test_run_now_button_press_triggers_full_sync(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """Pressing still delegates to the coordinator, unaffected by #208."""
    config_entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, config_entry)
    coordinator.async_run_sync = AsyncMock()  # type: ignore[method-assign]
    button = BookStackSyncRunNowButton(coordinator)

    await button.async_press()

    coordinator.async_run_sync.assert_awaited_once_with(dry_run=False)


async def test_preview_button_press_triggers_dry_run(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """Pressing the preview button runs a dry-run sync."""
    config_entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, config_entry)
    coordinator.async_run_sync = AsyncMock()  # type: ignore[method-assign]
    button = BookStackSyncPreviewButton(coordinator)

    await button.async_press()

    coordinator.async_run_sync.assert_awaited_once_with(dry_run=True)
