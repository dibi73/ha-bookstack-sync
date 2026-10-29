"""Repair-issue fix flows: force-resync a single conflicted page (#190)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult
from homeassistant.helpers import issue_registry as ir

from .api import BookStackApiError
from .const import LOGGER, REPAIR_ISSUE_BULK_CONFLICT, REPAIR_ISSUE_ORPHAN_CONFLICT
from .coordinator import BookStackSyncBusyError

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import BookStackSyncConfigEntry


class _SinglePageFixFlow(RepairsFlow):
    """
    Confirm, then force-overwrite one page's AUTO block.

    Mirrors ``homeassistant.components.repairs.ConfirmRepairFlow`` (a
    plain confirm dialog with no side effects) but runs the resync
    itself once the user confirms, via the entry's coordinator so it
    shares the same sync lock as a normal scheduled/manual run.
    """

    def __init__(self, entry_id: str, page_key: str) -> None:
        self._entry_id = entry_id
        self._page_key = page_key

    async def async_step_init(
        self,
        user_input: dict[str, str] | None = None,  # noqa: ARG002 - flow-step contract
    ) -> RepairsFlowResult:
        """Single-step flow: go straight to the confirmation form."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self,
        user_input: dict[str, str] | None = None,
    ) -> RepairsFlowResult:
        """Show the confirmation form, then run the resync on submit."""
        if user_input is not None:
            entry: BookStackSyncConfigEntry | None = (
                self.hass.config_entries.async_get_entry(self._entry_id)
            )
            if entry is None:
                # Config entry was removed between the issue being raised
                # and the user clicking Fix - nothing left to resync.
                return self.async_abort(reason="entry_not_found")
            try:
                found = await self._async_run_fix(entry)
            except BookStackSyncBusyError:
                # #203: a full sync is already holding the lock - fail
                # fast rather than leave the confirm dialog spinning for
                # however long that sync takes.
                return self.async_abort(reason="sync_in_progress")
            except BookStackApiError as err:
                # #227/#236: the abort dialog only says "failed"; the log
                # is the only place the actual cause shows up.
                LOGGER.warning("Resync of %s failed: %s", self._page_key, err)
                return self.async_abort(reason="resync_failed")
            if not found:
                # The device/area/label behind this page vanished from HA
                # too, in the time between the issue and the Fix click.
                return self.async_abort(reason="page_not_found")
            return self.async_create_entry(title="", data={})

        issue_registry = ir.async_get(self.hass)
        description_placeholders = None
        if issue := issue_registry.async_get_issue(self.handler, self.issue_id):
            description_placeholders = issue.translation_placeholders
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders=description_placeholders,
        )

    async def _async_run_fix(self, entry: BookStackSyncConfigEntry) -> bool:
        """Force-overwrite the page's AUTO block; False if the page is gone."""
        return await entry.runtime_data.coordinator.async_fix_single_page(
            self._page_key,
        )


class _OrphanTombstoneFixFlow(_SinglePageFixFlow):
    """
    Confirm, then mark one conflicted orphaned page as orphaned anyway (#275).

    Same confirm dialog and error handling as ``_SinglePageFixFlow``; only
    the action differs, since there is no HA object left to resync from.
    """

    async def _async_run_fix(self, entry: BookStackSyncConfigEntry) -> bool:
        """Force-tombstone the page; False if it was already resolved."""
        return await entry.runtime_data.coordinator.async_tombstone_single_page(
            self._page_key,
        )


class _BulkForceResyncFixFlow(RepairsFlow):
    """
    Confirm, then force-resync every page in one run.

    Companion to ``_SinglePageFixFlow`` for the aggregate
    ``bulk_page_conflict`` issue (see
    ``coordinator._reconcile_bulk_conflict_issue``): surfaced when a
    single rendering-only code change (e.g. a version bump) leaves many
    pages hash-drifted at once, so a non-developer user has a
    discoverable way to run the equivalent of the ``force=true`` service
    parameter without touching Developer Tools.
    """

    def __init__(self, entry_id: str) -> None:
        self._entry_id = entry_id

    async def async_step_init(
        self,
        user_input: dict[str, str] | None = None,  # noqa: ARG002 - flow-step contract
    ) -> RepairsFlowResult:
        """Single-step flow: go straight to the confirmation form."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self,
        user_input: dict[str, str] | None = None,
    ) -> RepairsFlowResult:
        """Show the confirmation form, then run the forced resync on submit."""
        if user_input is not None:
            entry: BookStackSyncConfigEntry | None = (
                self.hass.config_entries.async_get_entry(self._entry_id)
            )
            if entry is None:
                return self.async_abort(reason="entry_not_found")
            try:
                await entry.runtime_data.coordinator.async_force_resync_all()
            except BookStackSyncBusyError:
                return self.async_abort(reason="sync_in_progress")
            except BookStackApiError as err:
                LOGGER.warning("Forced resync of all pages failed: %s", err)
                return self.async_abort(reason="resync_failed")
            return self.async_create_entry(title="", data={})

        issue_registry = ir.async_get(self.hass)
        description_placeholders = None
        if issue := issue_registry.async_get_issue(self.handler, self.issue_id):
            description_placeholders = issue.translation_placeholders
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders=description_placeholders,
        )


async def async_create_fix_flow(
    hass: HomeAssistant,  # noqa: ARG001 - required by the repairs platform contract
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """
    Create the fix flow for a page-conflict-family repair issue.

    ``page_tampered``/``page_markers_missing`` share ``_SinglePageFixFlow``
    - only the resync target differs, carried in ``data`` (set when the
    issue was created, see ``coordinator._reconcile_tamper_issues`` /
    ``_reconcile_markers_missing_issues``). The aggregate
    ``bulk_page_conflict`` issue (id prefix distinguishes it, since it
    carries no ``page_key``) gets its own flow that resyncs everything.
    """
    data = data or {}
    if issue_id.startswith(f"{REPAIR_ISSUE_BULK_CONFLICT}_"):
        return _BulkForceResyncFixFlow(entry_id=str(data.get("entry_id", "")))
    if issue_id.startswith(f"{REPAIR_ISSUE_ORPHAN_CONFLICT}_"):
        return _OrphanTombstoneFixFlow(
            entry_id=str(data.get("entry_id", "")),
            page_key=str(data.get("page_key", "")),
        )
    return _SinglePageFixFlow(
        entry_id=str(data.get("entry_id", "")),
        page_key=str(data.get("page_key", "")),
    )
