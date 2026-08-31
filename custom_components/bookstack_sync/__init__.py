"""
BookStack Sync custom integration.

Documents the Home Assistant setup as markdown pages inside an existing
BookStack book and keeps it in sync. Manually added content inside marker
blocks is preserved across syncs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_loaded_integration

from .api import BookStackApiClient
from .const import (
    CONF_BASE_URL,
    CONF_TOKEN_ID,
    CONF_TOKEN_SECRET,
    CONF_VERIFY_SSL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)
from .coordinator import BookStackSyncCoordinator
from .data import BookStackSyncData
from .export_store import BookStackSyncExportStore
from .services import async_register_services, async_unregister_services
from .store import BookStackSyncStore

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import BookStackSyncConfigEntry

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BookStackSyncConfigEntry,
) -> bool:
    """Set up a BookStack Sync config entry."""
    verify_ssl = entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
    client = BookStackApiClient(
        base_url=entry.data[CONF_BASE_URL],
        token_id=entry.data[CONF_TOKEN_ID],
        token_secret=entry.data[CONF_TOKEN_SECRET],
        session=async_get_clientsession(hass, verify_ssl=verify_ssl),
    )
    store = BookStackSyncStore(hass, entry.entry_id)
    await store.async_load()

    export_store = BookStackSyncExportStore(hass, entry.entry_id)
    await export_store.async_load()

    coordinator = BookStackSyncCoordinator(hass, entry)

    entry.runtime_data = BookStackSyncData(
        client=client,
        coordinator=coordinator,
        integration=async_get_loaded_integration(hass, entry.domain),
        store=store,
        export_store=export_store,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Trigger the initial sync in the background so the integration finishes
    # setup quickly. The status sensor, per-page log lines and the persistent
    # notification let the user follow progress without blocking HA's UI.
    if coordinator.update_interval is not None:
        entry.async_create_background_task(
            hass,
            coordinator.async_request_refresh(),
            "bookstack_sync_initial_refresh",
        )

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: BookStackSyncConfigEntry,
) -> bool:
    """Unload platforms + services for this config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    await async_unregister_services(hass)
    return unload_ok


async def async_remove_entry(
    hass: HomeAssistant,
    entry: BookStackSyncConfigEntry,
) -> None:
    """
    Delete every repair issue this entry ever created (#186).

    Repair issue IDs embed ``entry.entry_id`` (see
    ``coordinator._reconcile_tamper_issues`` / ``_reconcile_markers_missing_issues``
    / ``_note_failure``), but nothing else ever tells the issue registry
    they're now orphaned once the entry itself is gone — unlike the
    PageMapping store, which HA deletes automatically along with the
    entry. Left unhandled, removed entries leave their repair issues
    behind forever, silently accumulating and burying whatever issue a
    user is actually looking for (confirmed live: 259 stale issues from
    a config entry removed months earlier).
    """
    registry = ir.async_get(hass)
    for issue_domain, issue_id in list(registry.issues):
        if issue_domain == DOMAIN and entry.entry_id in issue_id:
            ir.async_delete_issue(hass, DOMAIN, issue_id)


async def _async_update_listener(
    hass: HomeAssistant,
    entry: BookStackSyncConfigEntry,
) -> None:
    """Reload entry when options change so the new interval/book takes effect."""
    await hass.config_entries.async_reload(entry.entry_id)
