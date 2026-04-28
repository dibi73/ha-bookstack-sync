"""
Diagnostics dump for BookStack Sync.

Triggered when the user clicks ``Download diagnostics`` on the integration
card in *Settings → Devices & Services → BookStack Sync*.

Returns a redacted snapshot of the entry's config plus the last sync
report so a bug report can be filed without anyone having to type
"Lade Diagnose runter und schick die json" three times.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data

from .const import (
    CONF_BASE_URL,
    CONF_TOKEN_ID,
    CONF_TOKEN_SECRET,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import BookStackSyncConfigEntry


_REDACT = {CONF_TOKEN_ID, CONF_TOKEN_SECRET, CONF_BASE_URL}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: BookStackSyncConfigEntry,
) -> dict[str, Any]:
    """Return a redacted diagnostics dump for one BookStack Sync entry."""
    runtime = entry.runtime_data
    coordinator = runtime.coordinator
    store = runtime.store

    last_run = coordinator.last_run.isoformat() if coordinator.last_run else None
    last_report = (
        coordinator.last_report.as_dict()
        if coordinator.last_report is not None
        else None
    )

    # Page mapping summary - we don't dump the full mapping (could be
    # thousands of entries) but enough that a maintainer can spot whether
    # the user has e.g. 0 mappings (never synced) vs 400+ (real setup).
    pages = store.all()
    chapters = store.all_chapters()

    return {
        "config": {
            "data": async_redact_data(dict(entry.data), _REDACT),
            "options": dict(entry.options),
        },
        "ha": {
            "language": hass.config.language,
            "version": (
                hass.config.api.version if getattr(hass.config, "api", None) else None
            ),
        },
        "coordinator": {
            "last_run": last_run,
            "last_report": last_report,
            "is_active": coordinator.update_interval is not None,
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None
            ),
        },
        "store": {
            "page_count": len(pages),
            "tombstoned_count": sum(
                1 for p in pages.values() if p.tombstoned_at is not None
            ),
            "chapters": chapters,
            "sample_keys": sorted(pages.keys())[:10],
        },
    }
