"""DataUpdateCoordinator that drives the BookStack sync schedule."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, ClassVar

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ._strings import get_strings
from .api import BookStackApiAuthError, BookStackApiError
from .const import (
    CONF_BOOK_ID,
    CONF_EXCLUDED_AREAS,
    CONF_EXPORT_ENABLED,
    CONF_EXPORT_PATH,
    CONF_OUTPUT_LANGUAGE,
    CONF_SYNC_INTERVAL,
    DEFAULT_EXPORT_ENABLED,
    DEFAULT_INTERVAL,
    DEFAULT_OUTPUT_LANGUAGE,
    DOMAIN,
    INTERVAL_MANUAL,
    LOGGER,
    OUTPUT_LANGUAGE_AUTO,
    REPAIR_ISSUE_TAMPERED,
    REPAIR_ISSUE_UNREACHABLE,
    REPAIR_ISSUE_UNREACHABLE_THRESHOLD,
    SYNC_INTERVALS,
)
from .export import ExportResult
from .export import export as export_run
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
        # Set by the markdown back-export (issue #61). Stays None until
        # the user opts in via the options flow and either calls the
        # service or the post-sync auto-trigger fires.
        self.last_export_result: ExportResult | None = None
        # Surfaced via the status sensor so the dashboard can show
        # "syncing" while a run is in progress. Toggled in
        # ``async_run_sync`` (try/finally so failed runs also clear it).
        # v0.14.7: also True during the post-sync markdown back-export so
        # the sync button stays disabled until the *whole* run is done.
        self.is_syncing: bool = False
        # Per-page progress (v0.14.6, extended in v0.14.7 to cover the
        # markdown back-export phase). The sensor reads ``current_phase``
        # to pick a phase-specific localised template. Reset to (None, 0,
        # 0) at the start of every run and at the end of every phase.
        self.current_phase: str | None = None  # "sync" | "export" | None
        self.current_step: int = 0
        self.current_total: int = 0
        # Consecutive-failure counter for the "BookStack unreachable"
        # repair issue. Resets to 0 on the first successful sync.
        self._failure_streak: int = 0
        # Page keys (``device:UUID`` etc) for which a "page tampered"
        # repair issue is currently raised. Used to diff against the
        # latest sync report and auto-resolve issues on subsequent runs.
        self._active_tamper_keys: set[str] = set()
        # Serialises every sync path - schedule, run_now service, preview -
        # so they cannot interleave and create duplicate pages on first run.
        self._sync_lock = asyncio.Lock()

    async def _async_update_data(self) -> SyncReport:
        try:
            report = await self.async_run_sync(dry_run=False)
        except BookStackApiAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except BookStackApiError as err:
            self._note_failure()
            raise UpdateFailed(str(err)) from err
        else:
            self._note_success()
            # Tamper-issue reconciliation now runs from inside
            # ``async_run_sync`` (v0.14.1) so the manual
            # ``bookstack_sync.run_now`` service path also cleans up
            # stale issues. We keep the call here harmless / no-op
            # because the registry already reflects the current state.
            return report

    def _reconcile_tamper_issues(self, report: SyncReport) -> None:
        """
        Create / auto-resolve ``page_tampered`` repair issues.

        Source of truth is the HA issue-registry, NOT the in-memory cache:
        ``self._active_tamper_keys`` resets on every HA restart, which used
        to leave stale repair issues from previous sessions hanging around
        forever (v0.13.3 follow-up). We now query the registry directly so
        the diff against the current sync's tampered keys produces the
        correct delete-set even right after a restart.
        """
        current = dict(
            zip(report.tampered_page_keys, report.tampered_page_titles, strict=True),
        )
        entry_id = self.config_entry.entry_id
        prefix = f"{REPAIR_ISSUE_TAMPERED}_{entry_id}_"
        existing = {
            issue_id.removeprefix(prefix)
            for (issue_domain, issue_id) in ir.async_get(self.hass).issues
            if issue_domain == DOMAIN and issue_id.startswith(prefix)
        }
        new_keys = set(current.keys()) - existing
        resolved_keys = existing - set(current.keys())

        for key in new_keys:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"{REPAIR_ISSUE_TAMPERED}_{entry_id}_{key}",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=REPAIR_ISSUE_TAMPERED,
                translation_placeholders={"page_title": current[key]},
            )
        for key in resolved_keys:
            ir.async_delete_issue(
                self.hass,
                DOMAIN,
                f"{REPAIR_ISSUE_TAMPERED}_{entry_id}_{key}",
            )

        # In-memory cache kept for tests + diagnostics; no longer the
        # authoritative source.
        self._active_tamper_keys = set(current.keys())

    def _note_failure(self) -> None:
        """Increment the failure streak; raise repair issue at threshold."""
        self._failure_streak += 1
        if self._failure_streak >= REPAIR_ISSUE_UNREACHABLE_THRESHOLD:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"{REPAIR_ISSUE_UNREACHABLE}_{self.config_entry.entry_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=REPAIR_ISSUE_UNREACHABLE,
                translation_placeholders={
                    "count": str(self._failure_streak),
                },
            )

    def _note_success(self) -> None:
        """Reset the failure streak and auto-resolve the repair issue."""
        if self._failure_streak == 0:
            return
        self._failure_streak = 0
        ir.async_delete_issue(
            self.hass,
            DOMAIN,
            f"{REPAIR_ISSUE_UNREACHABLE}_{self.config_entry.entry_id}",
        )

    def _on_sync_progress(self, step: int, total: int) -> None:
        """
        Receive a progress tick from ``run_sync`` and refresh listeners.

        Called once per managed page; we just store the counts and call
        ``async_update_listeners()`` so the diagnostic status sensor
        re-renders. ~5 ticks/sec on a typical sync (rate-limited by
        ``WRITE_PAUSE_SECONDS = 0.2``); fine for a diagnostic-category
        sensor whose recorder traffic is acceptable.
        """
        self.current_step = step
        self.current_total = total
        self.async_update_listeners()

    def _on_export_progress(self, step: int, total: int) -> None:
        """
        Receive a progress tick from the markdown back-export (v0.14.7).

        Same shape as ``_on_sync_progress`` so the sensor's state-string
        renderer can stay symmetric — the only differentiator is
        ``current_phase`` which selects the right localised template.
        """
        self.current_step = step
        self.current_total = total
        self.async_update_listeners()

    _PHASE_TEMPLATE_KEYS: ClassVar[dict[str, str]] = {
        "sync": "sensor_state_syncing_progress_template",
        "export": "sensor_state_exporting_progress_template",
    }

    @property
    def sync_progress_text(self) -> str | None:
        """
        Localised progress line for the diagnostic sensor.

        Phase-aware: ``Sync läuft 12/345`` while syncing,
        ``Export läuft 12/345`` while running the markdown back-export.
        Returns ``None`` between the very-first phase-set and the very-
        first progress tick so the sensor falls back to the bare phase
        enum and HA's translation kicks in.
        """
        if self.current_phase is None or self.current_total <= 0:
            return None
        template_key = self._PHASE_TEMPLATE_KEYS.get(self.current_phase)
        if template_key is None:
            return None
        strings = get_strings(self._resolve_output_language())
        return strings[template_key].format(
            step=self.current_step,
            total=self.current_total,
        )

    async def async_run_sync(
        self,
        *,
        dry_run: bool = False,
        force: bool = False,
    ) -> SyncReport:
        """
        Execute a sync immediately, regardless of the schedule.

        ``force=True`` (v0.14.3) bypasses the tamper-skip path: pages
        whose stored hash drifted from the BookStack-stored AUTO block
        AND whose new render genuinely differs (the typical fallout
        from a version-bump that reshapes the AUTO block) get
        overwritten instead of skipped. The MANUAL block is preserved
        either way.
        """
        async with self._sync_lock:
            self.is_syncing = True
            self.current_phase = "sync"
            self.current_step = 0
            self.current_total = 0
            self.async_update_listeners()
            try:
                runtime = self.config_entry.runtime_data
                options = self.config_entry.options
                data = self.config_entry.data
                # Initial setup stores book_id in `data`, but the options
                # flow rewrites it into `options`. Look in options first,
                # then fall back to data so both layouts work.
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
                    force=force,
                    progress_callback=self._on_sync_progress,
                )
                if not dry_run:
                    self.last_run = datetime.now(tz=UTC)
                    self.last_report = report
                    # Reconcile tamper repair-issues inside the lock so
                    # both the scheduled-sync path and the manual
                    # ``run_now`` service path clean up stale issues.
                    # v0.13.4 only reconciled from ``_async_update_data``,
                    # so users on ``manual`` interval saw their old
                    # repair-issues hang around forever (v0.14.1 fix).
                    self._reconcile_tamper_issues(report)
            finally:
                # End of sync phase. ``is_syncing`` stays True if we're
                # about to roll into the export phase below — keeps the
                # sync button disabled across both phases.
                self.current_phase = None
                self.current_step = 0
                self.current_total = 0
                self.is_syncing = False
                self.async_update_listeners()
        # Lock is released. Opt-in markdown back-export runs here so it
        # cannot deadlock against itself if it ever calls back into a
        # locked sync path.
        if not dry_run:
            await self._maybe_export_after_sync()
        return report

    async def _maybe_export_after_sync(self) -> None:
        """
        Run the markdown back-export if the user has explicitly opted in.

        ``export_enabled`` is the only switch (default off): once on, every
        successful sync also exports. v0.13.2 dropped the separate
        ``export_after_sync`` toggle — it was redundant, since enabling the
        export feature already implies wanting it to run. Errors are logged
        but never raised — the sync itself already succeeded and we don't
        want a missing folder to flip the sensor red.

        v0.14.7: the export phase is surfaced on the diagnostic status
        sensor as ``Export läuft N/total`` (German) / ``Exporting N/total``
        (English) so the user no longer has to wonder whether the post-sync
        export has actually finished writing the .md files.
        """
        options = self.config_entry.options or {}
        if not options.get(CONF_EXPORT_ENABLED, DEFAULT_EXPORT_ENABLED):
            return
        self.is_syncing = True
        self.current_phase = "export"
        self.current_step = 0
        self.current_total = 0
        self.async_update_listeners()
        try:
            result = await export_run(
                self.hass,
                self.config_entry,
                dry_run=False,
                output_path=options.get(CONF_EXPORT_PATH),
                progress_callback=self._on_export_progress,
            )
        except Exception:  # noqa: BLE001 - export must not break the sync sensor
            LOGGER.exception("BookStack markdown export after sync failed")
            self.current_phase = None
            self.current_step = 0
            self.current_total = 0
            self.is_syncing = False
            self.async_update_listeners()
            return
        self.last_export_result = result
        self.current_phase = None
        self.current_step = 0
        self.current_total = 0
        self.is_syncing = False
        self.async_update_listeners()

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
