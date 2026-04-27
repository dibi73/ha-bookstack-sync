"""
BookStack Sync custom integration.

Documents the Home Assistant setup as markdown pages inside an existing
BookStack book and keeps it in sync. Manually added content inside marker
blocks is preserved across syncs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_loaded_integration

from .api import BookStackApiClient
from .const import (
    CONF_BASE_URL,
    CONF_TOKEN_ID,
    CONF_TOKEN_SECRET,
    CONF_VERIFY_SSL,
    DEFAULT_VERIFY_SSL,
)
from .coordinator import BookStackSyncCoordinator
from .data import BookStackSyncData
from .services import async_register_services, async_unregister_services
from .store import BookStackSyncStore

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import BookStackSyncConfigEntry

PLATFORMS: list = []  # services-only integration; no entities in V0


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

    coordinator = BookStackSyncCoordinator(hass, entry)

    entry.runtime_data = BookStackSyncData(
        client=client,
        coordinator=coordinator,
        integration=async_get_loaded_integration(hass, entry.domain),
        store=store,
    )

    if coordinator.update_interval is not None:
        await coordinator.async_config_entry_first_refresh()

    await async_register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: BookStackSyncConfigEntry,  # noqa: ARG001 - entry unused; HA contract
) -> bool:
    """Unload a config entry and tear down services if it was the last one."""
    await async_unregister_services(hass)
    return True


async def _async_update_listener(
    hass: HomeAssistant,
    entry: BookStackSyncConfigEntry,
) -> None:
    """Reload entry when options change so the new interval/book takes effect."""
    await hass.config_entries.async_reload(entry.entry_id)
