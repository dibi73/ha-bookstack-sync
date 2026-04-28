"""DataUpdateCoordinator that drives the BookStack sync schedule."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ._strings import get_strings
from .api import BookStackApiAuthError, BookStackApiError
from .const import (
    CONF_BOOK_ID,
    CONF_EXCLUDED_AREAS,
    CONF_OUTPUT_LANGUAGE,
    CONF_SYNC_INTERVAL,
    DEFAULT_INTERVAL,
    DEFAULT_OUTPUT_LANGUAGE,
    INTERVAL_MANUAL,
    LOGGER,
    OUTPUT_LANGUAGE_AUTO,
    SYNC_INTERVALS,
)
from .sync import SyncReport, run_sync

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import BookStackSyncConfigEntry


class BookStackSyncCoordinator(DataUpdateCoordinator[SyncReport]):
    """Triggers sync runs on the configured cadence."""

    config_entry: BookStackSyncConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: BookStackSyncConfigEntry,
    ) -> None:
        """Wire up the schedule based on the entry's interval option."""
        interval_key = (entry.options or entry.data).get(
            CONF_SYNC_INTERVAL,
            DEFAULT_INTERVAL,
        )
        update_interval = (
            timedelta(seconds=SYNC_INTERVALS[interval_key])
            if interval_key != INTERVAL_MANUAL
            else None
        )
        super().__init__(
            hass,
            LOGGER,
            name="bookstack_sync",
            update_interval=update_interval,
        )
        self.config_entry = entry
        self.last_run: datetime | None = None
        self.last_report: SyncReport | None = None
        # Serialises every sync path - schedule, run_now service, preview -
        # so they cannot interleave and create duplicate pages on first run.
        self._sync_lock = asyncio.Lock()

    async def _async_update_data(self) -> SyncReport:
        try:
            return await self.async_run_sync(dry_run=False)
        except BookStackApiAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except BookStackApiError as err:
            raise UpdateFailed(str(err)) from err

    async def async_run_sync(self, *, dry_run: bool = False) -> SyncReport:
        """Execute a sync immediately, regardless of the schedule."""
        async with self._sync_lock:
            runtime = self.config_entry.runtime_data
            options = self.config_entry.options
            data = self.config_entry.data
            # Initial setup stores book_id in `data`, but the options flow
            # rewrites it into `options`. Look in options first, then fall
            # back to data so both layouts work without crashing.
            book_id = int(options.get(CONF_BOOK_ID) or data[CONF_BOOK_ID])
            excluded_areas = options.get(CONF_EXCLUDED_AREAS, []) or []
            strings = get_strings(self._resolve_output_language())
            report = await run_sync(
                self.hass,
                runtime.client,
                runtime.store,
                book_id,
                strings,
                dry_run=dry_run,
                excluded_area_ids=excluded_areas,
            )
            if not dry_run:
                self.last_run = datetime.now(tz=UTC)
                self.last_report = report
            return report

    def _resolve_output_language(self) -> str:
        """
        Return the language code to use for BookStack output.

        ``auto`` (default) follows the user's HA UI language. An explicit
        choice in the options flow (e.g. ``en``, ``de``) overrides it.
        """
        options = self.config_entry.options or {}
        choice = options.get(CONF_OUTPUT_LANGUAGE, DEFAULT_OUTPUT_LANGUAGE)
        if choice == OUTPUT_LANGUAGE_AUTO:
            return self.hass.config.language or "en"
        return choice
