"""Tests for the service-handler helpers in services.py."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bookstack_sync.const import (
    CONF_BASE_URL,
    CONF_BOOK_ID,
    CONF_EXPORT_ENABLED,
    CONF_TOKEN_ID,
    CONF_TOKEN_SECRET,
    DOMAIN,
)
from custom_components.bookstack_sync.services import _coordinators

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def _make_runtime_data(label: str) -> MagicMock:
    """Stub runtime_data with a labelled coordinator marker."""
    coordinator = MagicMock()
    coordinator.label = label
    rd = MagicMock()
    rd.coordinator = coordinator
    return rd


async def test_coordinators_export_enabled_first(hass: HomeAssistant) -> None:
    """
    v0.14.2: when multiple BookStack instances are configured, the one
    with markdown export enabled MUST come out first.

    Otherwise its post-sync export would run while the other instances
    are still mid-sync, leaving the export folder with a stale snapshot.
    The order between non-export-enabled entries stays stable (config-
    entry creation order) thanks to Python's stable sort.
    """
    # Three entries: A (export OFF), B (export ON), C (export OFF).
    # Expected order out of _coordinators: B, A, C.
    for label, export_enabled in (("A", False), ("B", True), ("C", False)):
        entry = MockConfigEntry(
            domain=DOMAIN,
            title=f"BookStack: {label}",
            unique_id=f"http://bookstack-{label}.local",
            data={
                CONF_BASE_URL: f"http://bookstack-{label}.local",
                CONF_TOKEN_ID: "tid",
                CONF_TOKEN_SECRET: "tsec",
                CONF_BOOK_ID: 1,
            },
            options={CONF_EXPORT_ENABLED: export_enabled},
        )
        entry.add_to_hass(hass)
        entry.runtime_data = _make_runtime_data(label)

    coords = _coordinators(hass)
    labels = [c.label for c in coords]

    assert labels[0] == "B", f"export-enabled instance must come first, got {labels!r}"
    assert labels[1:] == ["A", "C"], (
        f"non-export entries must keep creation order, got {labels!r}"
    )


async def test_coordinators_no_export_enabled_keeps_natural_order(
    hass: HomeAssistant,
) -> None:
    """If no entry has the export enabled, the order is config-entry creation order."""
    for label in ("First", "Second", "Third"):
        entry = MockConfigEntry(
            domain=DOMAIN,
            title=f"BookStack: {label}",
            unique_id=f"http://bookstack-{label}.local",
            data={
                CONF_BASE_URL: f"http://bookstack-{label}.local",
                CONF_TOKEN_ID: "tid",
                CONF_TOKEN_SECRET: "tsec",
                CONF_BOOK_ID: 1,
            },
            options={},
        )
        entry.add_to_hass(hass)
        entry.runtime_data = _make_runtime_data(label)

    coords = _coordinators(hass)
    assert [c.label for c in coords] == ["First", "Second", "Third"]
