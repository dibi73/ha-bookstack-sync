"""Tests for the sync coordinator.

Covers two important behaviours:
* The internal lock prevents two syncs from running concurrently
  (the fix from V0.1 against duplicate-page creation on first run).
* `BookStackApiAuthError` from a sync run is translated to
  `ConfigEntryAuthFailed` so HA's reauth flow gets triggered.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed

from custom_components.bookstack_sync.api import BookStackApiAuthError
from custom_components.bookstack_sync.coordinator import BookStackSyncCoordinator
from custom_components.bookstack_sync.sync import SyncReport

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


def _make_coordinator(
    hass: HomeAssistant,
    entry: MockConfigEntry,
) -> BookStackSyncCoordinator:
    return BookStackSyncCoordinator(hass, entry)


async def test_concurrent_calls_serialised(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """Two parallel async_run_sync calls execute one after the other."""
    config_entry.add_to_hass(hass)
    coord = _make_coordinator(hass, config_entry)

    started = []
    finished = []

    async def fake_run_sync(*args: object, **kwargs: object) -> SyncReport:
        marker = object()
        started.append(marker)
        # Yield once so a second call has a chance to enter the lock if it could.
        await asyncio.sleep(0)
        finished.append(marker)
        return SyncReport(dry_run=bool(kwargs.get("dry_run")))

    # Patch sync.run_sync where coordinator imports it
    with patch(
        "custom_components.bookstack_sync.coordinator.run_sync",
        new=fake_run_sync,
    ):
        # Build minimal runtime_data so coordinator.async_run_sync can read it
        config_entry.runtime_data = type(
            "RD", (), {"client": object(), "store": object()}
        )()
        await asyncio.gather(
            coord.async_run_sync(),
            coord.async_run_sync(),
        )

    # Both ran, but were serialised: the start of the second must come
    # AFTER the finish of the first.
    assert len(started) == 2
    assert len(finished) == 2
    assert started.index(finished[0]) == 0


async def test_auth_failure_raises_config_entry_auth_failed(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    config_entry.add_to_hass(hass)
    coord = _make_coordinator(hass, config_entry)
    config_entry.runtime_data = type(
        "RD",
        (),
        {"client": object(), "store": object()},
    )()

    with (
        patch(
            "custom_components.bookstack_sync.coordinator.run_sync",
            new=AsyncMock(side_effect=BookStackApiAuthError("token rotated")),
        ),
        pytest.raises(ConfigEntryAuthFailed),
    ):
        await coord._async_update_data()


async def test_last_run_recorded_after_successful_sync(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    config_entry.add_to_hass(hass)
    coord = _make_coordinator(hass, config_entry)
    config_entry.runtime_data = type(
        "RD",
        (),
        {"client": object(), "store": object()},
    )()
    report = SyncReport()

    with patch(
        "custom_components.bookstack_sync.coordinator.run_sync",
        new=AsyncMock(return_value=report),
    ):
        await coord.async_run_sync()

    assert coord.last_run is not None
    assert coord.last_report is report


async def test_is_syncing_flag_set_during_run(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """The is_syncing flag is True during run_sync, False before/after."""
    config_entry.add_to_hass(hass)
    coord = _make_coordinator(hass, config_entry)
    config_entry.runtime_data = type(
        "RD",
        (),
        {"client": object(), "store": object()},
    )()

    flag_during = []

    async def fake_run_sync(*args: object, **kwargs: object) -> SyncReport:
        flag_during.append(coord.is_syncing)
        return SyncReport(dry_run=bool(kwargs.get("dry_run")))

    assert coord.is_syncing is False
    with patch(
        "custom_components.bookstack_sync.coordinator.run_sync",
        new=fake_run_sync,
    ):
        await coord.async_run_sync()

    assert flag_during == [True]
    assert coord.is_syncing is False


async def test_is_syncing_flag_cleared_on_failure(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """A failed run also clears is_syncing (try/finally)."""
    config_entry.add_to_hass(hass)
    coord = _make_coordinator(hass, config_entry)
    config_entry.runtime_data = type(
        "RD",
        (),
        {"client": object(), "store": object()},
    )()

    with (
        patch(
            "custom_components.bookstack_sync.coordinator.run_sync",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
        pytest.raises(RuntimeError),
    ):
        await coord.async_run_sync()

    assert coord.is_syncing is False


async def test_dry_run_does_not_record_last_run(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    config_entry.add_to_hass(hass)
    coord = _make_coordinator(hass, config_entry)
    config_entry.runtime_data = type(
        "RD",
        (),
        {"client": object(), "store": object()},
    )()

    with patch(
        "custom_components.bookstack_sync.coordinator.run_sync",
        new=AsyncMock(return_value=SyncReport(dry_run=True)),
    ):
        await coord.async_run_sync(dry_run=True)

    assert coord.last_run is None
    assert coord.last_report is None


async def test_run_now_path_reconciles_tamper_issues(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """
    v0.14.1: stale tamper repair-issues also auto-resolve when the user
    triggers ``bookstack_sync.run_now`` (which calls ``async_run_sync``
    directly, bypassing ``_async_update_data``).

    v0.13.4 only reconciled from the scheduled-sync path. Users on
    ``manual`` interval — or anyone who restarted HA and used the
    ``run_now`` service before the daily schedule fired — kept seeing
    the 260+ "AUTO block was edited" repair-issues forever. The fix
    moves ``_reconcile_tamper_issues`` into ``async_run_sync`` so every
    successful sync (scheduled OR manual) sweeps the registry.
    """
    from homeassistant.helpers import issue_registry as ir  # noqa: PLC0415

    from custom_components.bookstack_sync.const import (  # noqa: PLC0415
        DOMAIN,
        REPAIR_ISSUE_TAMPERED,
    )

    config_entry.add_to_hass(hass)
    config_entry.runtime_data = type(
        "RD",
        (),
        {"client": object(), "store": object()},
    )()

    entry_id = config_entry.entry_id
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{REPAIR_ISSUE_TAMPERED}_{entry_id}_device:abc",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=REPAIR_ISSUE_TAMPERED,
        translation_placeholders={"page_title": "Acurite-Rain-25"},
    )

    coord = _make_coordinator(hass, config_entry)

    with patch(
        "custom_components.bookstack_sync.coordinator.run_sync",
        new=AsyncMock(return_value=SyncReport()),
    ):
        await coord.async_run_sync()

    issue_reg = ir.async_get(hass)
    remaining = [
        issue_id
        for (issue_domain, issue_id) in issue_reg.issues
        if issue_domain == DOMAIN
        and issue_id.startswith(f"{REPAIR_ISSUE_TAMPERED}_{entry_id}_")
    ]
    assert remaining == [], f"run_now did not clean up stale issues: {remaining}"


async def test_stale_tamper_issues_resolved_after_restart(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """
    v0.13.4 regression: stale tamper repair-issues from previous sessions
    are auto-deleted on the first clean sync after restart.

    Before v0.13.4 the reconciler only consulted ``self._active_tamper_keys``
    which is in-memory and resets on every coordinator construction. Old
    repair-issues raised in a previous HA session would therefore never be
    cleaned up — the user saw 260+ stale notifications hanging around even
    after the v0.13.3 hash fix had stopped producing new ones.
    """
    from homeassistant.helpers import issue_registry as ir  # noqa: PLC0415

    from custom_components.bookstack_sync.const import (  # noqa: PLC0415
        DOMAIN,
        REPAIR_ISSUE_TAMPERED,
    )

    config_entry.add_to_hass(hass)

    # Simulate a previous HA session that raised tamper issues for two
    # pages and then the user restarted before they could be resolved.
    entry_id = config_entry.entry_id
    for key in ("device:abc", "device:def"):
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"{REPAIR_ISSUE_TAMPERED}_{entry_id}_{key}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=REPAIR_ISSUE_TAMPERED,
            translation_placeholders={"page_title": f"page-{key}"},
        )

    # Now construct a fresh coordinator (= post-restart).
    coord = _make_coordinator(hass, config_entry)
    assert coord._active_tamper_keys == set()  # in-memory cache empty

    # Simulate a clean sync run — no tampered pages reported.
    coord._reconcile_tamper_issues(SyncReport())

    # All previously-stored tamper issues for this entry are gone.
    issue_reg = ir.async_get(hass)
    remaining = [
        issue_id
        for (issue_domain, issue_id) in issue_reg.issues
        if issue_domain == DOMAIN
        and issue_id.startswith(f"{REPAIR_ISSUE_TAMPERED}_{entry_id}_")
    ]
    assert remaining == [], f"stale tamper issues survived: {remaining}"


async def test_progress_callback_updates_sensor_progress_state(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """v0.14.6: progress callback feeds the diagnostic sensor mid-sync."""
    config_entry.add_to_hass(hass)
    coord = _make_coordinator(hass, config_entry)
    config_entry.runtime_data = type(
        "RD",
        (),
        {"client": object(), "store": object()},
    )()

    progress_seen: list[tuple[int, int, str | None]] = []

    async def fake_run_sync(*args: object, **kwargs: object) -> SyncReport:
        progress_callback = kwargs.get("progress_callback")
        assert progress_callback is not None, "coordinator must wire a callback"
        progress_callback(0, 5)
        progress_seen.append(
            (coord.current_step, coord.current_total, coord.sync_progress_text),
        )
        progress_callback(2, 5)
        progress_seen.append(
            (coord.current_step, coord.current_total, coord.sync_progress_text),
        )
        progress_callback(5, 5)
        progress_seen.append(
            (coord.current_step, coord.current_total, coord.sync_progress_text),
        )
        return SyncReport(dry_run=bool(kwargs.get("dry_run")))

    with patch(
        "custom_components.bookstack_sync.coordinator.run_sync",
        new=fake_run_sync,
    ):
        await coord.async_run_sync()

    # First tick: total=5, step=0 — text is "X 0/5".
    assert progress_seen[0][:2] == (0, 5)
    assert progress_seen[0][2] is not None
    assert "0/5" in progress_seen[0][2]
    assert progress_seen[1][:2] == (2, 5)
    assert "2/5" in progress_seen[1][2]
    assert progress_seen[2][:2] == (5, 5)
    assert "5/5" in progress_seen[2][2]

    # After the run: counters reset, no progress text.
    assert coord.current_step == 0
    assert coord.current_total == 0
    assert coord.sync_progress_text is None


async def test_sync_progress_text_is_none_before_first_tick(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """No progress data yet -> property returns None so sensor falls back."""
    config_entry.add_to_hass(hass)
    coord = _make_coordinator(hass, config_entry)
    assert coord.sync_progress_text is None


async def test_sensor_state_shows_progress_string_while_syncing(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """v0.14.6: status sensor surfaces ``Sync läuft 12/345`` mid-run."""
    from custom_components.bookstack_sync.sensor import (  # noqa: PLC0415
        BookStackSyncStatusSensor,
    )

    config_entry.add_to_hass(hass)
    coord = _make_coordinator(hass, config_entry)
    sensor = BookStackSyncStatusSensor(coord)

    # Before any sync: never_run.
    assert sensor.native_value == "never_run"

    # Mid-sync, no progress yet: enum-fallback so HA's state translation
    # still kicks in for the brief pre-first-tick window.
    coord.is_syncing = True
    coord.current_phase = "sync"
    assert sensor.native_value == "syncing"

    # Progress arrives — sensor now shows the formatted string.
    coord.current_step = 12
    coord.current_total = 345
    state = sensor.native_value
    assert "12/345" in state
    # Localised — German default.
    assert state.startswith(("Sync läuft", "Syncing"))

    # v0.14.7: phase flips to ``export`` for the post-sync markdown
    # back-export — sensor must localise that phase too.
    coord.current_phase = "export"
    coord.current_step = 5
    coord.current_total = 100
    state = sensor.native_value
    assert "5/100" in state
    assert state.startswith(("Export läuft", "Exporting"))

    # Sync done: counters reset, sensor falls back to ok.
    coord.is_syncing = False
    coord.current_phase = None
    coord.current_step = 0
    coord.current_total = 0
    coord.last_report = SyncReport()
    coord.last_run = None  # last_run gets stamped only after successful sync
    assert sensor.native_value == "ok"
