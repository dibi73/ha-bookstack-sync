"""Service handlers for BookStack Sync."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.exceptions import HomeAssistantError, Unauthorized

from .const import (
    CONF_EXPORT_ENABLED,
    CONF_EXPORT_PATH,
    DEFAULT_EXPORT_ENABLED,
    DOMAIN,
    LOGGER,
    SERVICE_EXPORT_MARKDOWN,
    SERVICE_PREVIEW,
    SERVICE_RUN_NOW,
)
from .export import export as export_run

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall


def _coordinators(hass: HomeAssistant) -> list:
    """Return all loaded BookStack coordinators across config entries."""
    return [
        entry.runtime_data.coordinator
        for entry in hass.config_entries.async_entries(DOMAIN)
        if getattr(entry, "runtime_data", None) is not None
    ]


async def _require_admin(hass: HomeAssistant, call: ServiceCall) -> None:
    """
    Reject non-admin callers.

    These services trigger writes to an external system and dump page
    titles (= entity friendly names) into the HA log. We restrict them
    to admins so a low-privileged user with a long-lived token cannot
    use them as an enumeration / amplification primitive.
    """
    user_id = call.context.user_id
    if user_id is None:
        # System-triggered calls (e.g. automation context with no user)
        # are allowed - the operator owns the automation.
        return
    user = await hass.auth.async_get_user(user_id)
    if user is None or not user.is_admin:
        raise Unauthorized(
            context=call.context,
            permission="bookstack_sync.admin_only",
        )


class ExportDisabledError(HomeAssistantError):
    """
    Raised by ``export_markdown`` when the user has not opted in.

    Markdown back-export is off by default — it costs disk space and CPU
    on every sync, and most users only need the BookStack pages, not a
    parallel folder of files. The option lives in the integration's
    *Configure* dialog under *Markdown-Export aktivieren*.
    """

    translation_domain = DOMAIN
    translation_key = "export_disabled"


async def async_register_services(hass: HomeAssistant) -> None:
    """Register run_now, preview, and export_markdown."""
    if hass.services.has_service(DOMAIN, SERVICE_RUN_NOW):
        return

    async def _handle_run_now(call: ServiceCall) -> None:
        await _require_admin(hass, call)
        for coordinator in _coordinators(hass):
            LOGGER.info("Running BookStack sync (run_now)")
            await coordinator.async_run_sync(dry_run=False)

    async def _handle_preview(call: ServiceCall) -> None:
        await _require_admin(hass, call)
        for coordinator in _coordinators(hass):
            LOGGER.info("Running BookStack sync preview (dry-run)")
            report = await coordinator.async_run_sync(dry_run=True)
            LOGGER.info("Preview result: %s", report.as_dict())

    async def _handle_export(call: ServiceCall) -> None:
        await _require_admin(hass, call)
        dry_run = bool(call.data.get("dry_run", False))
        override_path = call.data.get("output_path")
        any_enabled = False
        for entry in hass.config_entries.async_entries(DOMAIN):
            if getattr(entry, "runtime_data", None) is None:
                continue
            if not entry.options.get(CONF_EXPORT_ENABLED, DEFAULT_EXPORT_ENABLED):
                continue
            any_enabled = True
            path = override_path or entry.options.get(CONF_EXPORT_PATH)
            LOGGER.info(
                "Running BookStack export (entry=%s, dry_run=%s)",
                entry.entry_id,
                dry_run,
            )
            result = await export_run(
                hass,
                entry,
                dry_run=dry_run,
                output_path=path,
            )
            entry.runtime_data.coordinator.last_export_result = result
            entry.runtime_data.coordinator.async_update_listeners()
        if not any_enabled:
            # Hard kill switch: no entry has opted in. Refuse loudly so the
            # user knows the call did nothing and can flip the switch.
            raise ExportDisabledError

    hass.services.async_register(DOMAIN, SERVICE_RUN_NOW, _handle_run_now)
    hass.services.async_register(DOMAIN, SERVICE_PREVIEW, _handle_preview)
    hass.services.async_register(DOMAIN, SERVICE_EXPORT_MARKDOWN, _handle_export)


async def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove services when the last config entry is unloaded."""
    if hass.config_entries.async_entries(DOMAIN):
        return
    for service in (SERVICE_RUN_NOW, SERVICE_PREVIEW, SERVICE_EXPORT_MARKDOWN):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
