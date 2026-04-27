"""Service handlers for BookStack Sync."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .const import DOMAIN, LOGGER, SERVICE_PREVIEW, SERVICE_RUN_NOW

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall


def _coordinators(hass: HomeAssistant) -> list:
    """Return all loaded BookStack coordinators across config entries."""
    return [
        entry.runtime_data.coordinator
        for entry in hass.config_entries.async_entries(DOMAIN)
        if getattr(entry, "runtime_data", None) is not None
    ]


async def async_register_services(hass: HomeAssistant) -> None:
    """Register run_now and preview as integration-level services."""
    if hass.services.has_service(DOMAIN, SERVICE_RUN_NOW):
        return

    async def _handle_run_now(_call: ServiceCall) -> None:
        for coordinator in _coordinators(hass):
            LOGGER.info("Running BookStack sync (run_now)")
            await coordinator.async_run_sync(dry_run=False)

    async def _handle_preview(_call: ServiceCall) -> None:
        for coordinator in _coordinators(hass):
            LOGGER.info("Running BookStack sync preview (dry-run)")
            report = await coordinator.async_run_sync(dry_run=True)
            LOGGER.info("Preview result: %s", report.as_dict())

    hass.services.async_register(DOMAIN, SERVICE_RUN_NOW, _handle_run_now)
    hass.services.async_register(DOMAIN, SERVICE_PREVIEW, _handle_preview)


async def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove services when the last config entry is unloaded."""
    if hass.config_entries.async_entries(DOMAIN):
        return
    for service in (SERVICE_RUN_NOW, SERVICE_PREVIEW):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
