"""Tests for the service-handler helpers in services.py."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bookstack_sync.api import (
    BookStackApiAuthError,
    BookStackApiCommunicationError,
)
from custom_components.bookstack_sync.const import (
    CONF_BASE_URL,
    CONF_BOOK_ID,
    CONF_EXPORT_ENABLED,
    CONF_TOKEN_ID,
    CONF_TOKEN_SECRET,
    DOMAIN,
)
from custom_components.bookstack_sync.services import (
    BookStackSyncAuthFailedError,
    BookStackUnreachableError,
    _coordinators,
    _run_all_entries,
)

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


def _make_coordinator(
    title: str,
    *,
    run_sync_side_effect: Exception | None = None,
    report: MagicMock | None = None,
) -> MagicMock:
    """Stub coordinator whose ``async_run_sync`` either raises or returns ``report``."""
    coordinator = MagicMock()
    coordinator.config_entry.title = title
    coordinator.async_run_sync = AsyncMock(
        side_effect=run_sync_side_effect,
        return_value=report,
    )
    return coordinator


async def test_run_all_entries_isolates_failures_and_still_calls_every_coordinator(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    A communication failure on one entry must not stop the others (#133).

    Real-world case (2026-08-26): two configured BookStack instances, one
    target unreachable. Before this fix, ``run_now``/``preview`` looped
    over ``_coordinators(hass)`` with no per-iteration error handling, so
    the first entry's exception aborted the whole service call with an
    HTTP 500 — a perfectly healthy SECOND instance never got synced
    either, in the same call. Every configured entry must now get a
    chance regardless of an earlier entry's failure.
    """
    failing = _make_coordinator(
        "Broken",
        run_sync_side_effect=BookStackApiCommunicationError("boom"),
    )
    healthy = _make_coordinator("Healthy")
    monkeypatch.setattr(
        "custom_components.bookstack_sync.services._coordinators",
        lambda hass: [failing, healthy],
    )

    with pytest.raises(BookStackUnreachableError):
        await _run_all_entries(hass, dry_run=False, force=False, log_prefix="test")

    failing.async_run_sync.assert_awaited_once()
    healthy.async_run_sync.assert_awaited_once()


async def test_run_all_entries_auth_failure_takes_priority_over_unreachable(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Mixed failure kinds across entries: auth rejection is the one surfaced.

    An auth failure needs the user to act (renew the token / reauth-flow)
    — more actionable than "check the log for connectivity issues" if a
    single run happens to hit both problems on different entries.
    """
    auth_broken = _make_coordinator(
        "AuthBroken",
        run_sync_side_effect=BookStackApiAuthError("rejected"),
    )
    unreachable = _make_coordinator(
        "Unreachable",
        run_sync_side_effect=BookStackApiCommunicationError("boom"),
    )
    monkeypatch.setattr(
        "custom_components.bookstack_sync.services._coordinators",
        lambda hass: [auth_broken, unreachable],
    )

    with pytest.raises(BookStackSyncAuthFailedError):
        await _run_all_entries(hass, dry_run=False, force=False, log_prefix="test")

    auth_broken.async_run_sync.assert_awaited_once()
    unreachable.async_run_sync.assert_awaited_once()


async def test_run_all_entries_no_error_when_all_succeed(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No failures anywhere -> no exception raised, every entry still called."""
    report = MagicMock()
    report.as_dict.return_value = {"ok": True}
    entry_a = _make_coordinator("A", report=report)
    entry_b = _make_coordinator("B", report=report)
    monkeypatch.setattr(
        "custom_components.bookstack_sync.services._coordinators",
        lambda hass: [entry_a, entry_b],
    )

    await _run_all_entries(hass, dry_run=True, force=False, log_prefix="test")

    entry_a.async_run_sync.assert_awaited_once()
    entry_b.async_run_sync.assert_awaited_once()
