"""Service handlers for BookStack Sync."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.exceptions import HomeAssistantError, Unauthorized

from .api import BookStackApiAuthError, BookStackApiError
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

    from .coordinator import BookStackSyncCoordinator


def _coordinators(hass: HomeAssistant) -> list[BookStackSyncCoordinator]:
    """
    Return all loaded BookStack coordinators across config entries.

    v0.14.2: order matters when multiple BookStack instances are
    configured and one of them has the markdown back-export enabled.
    The export-enabled instance MUST sync first, otherwise its
    post-sync export pass would run while the OTHER instances are
    still in mid-sync — leaving the exported folder with a stale
    snapshot of one instance and a fresh snapshot of another.

    Sort key: ``not export_enabled`` (False sorts before True), so
    the single export-enabled entry comes out at index 0; remaining
    entries keep their config-entry creation order via Python's
    stable sort.
    """
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if getattr(entry, "runtime_data", None) is not None
    ]
    entries.sort(
        key=lambda entry: (
            not entry.options.get(
                CONF_EXPORT_ENABLED,
                DEFAULT_EXPORT_ENABLED,
            )
        ),
    )
    return [entry.runtime_data.coordinator for entry in entries]


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


class BookStackUnreachableError(HomeAssistantError):
    """
    Raised after ``run_now``/``preview`` if ≥1 configured entry couldn't be reached.

    Wires up the "bookstack_unreachable" exception-translation entry that
    was part of the Gold-quality-scale "exception-translations skeleton"
    (strings.json) but, before v0.15.0/#133, was never actually raised by
    any code path — only used as a Repair-Issue translation key. Per-entry
    detail goes to the log (``LOGGER.exception``); the translated message
    points the user there rather than repeating it.
    """

    translation_domain = DOMAIN
    translation_key = "bookstack_unreachable"


class BookStackSyncAuthFailedError(HomeAssistantError):
    """
    Raised after ``run_now``/``preview`` if ≥1 configured entry's token was rejected.

    Same skeleton-wiring story as ``BookStackUnreachableError``, for the
    pre-existing "bookstack_auth_failed" translation entry. Takes priority
    over ``BookStackUnreachableError`` when a run mixes both failure kinds
    across entries — an auth rejection needs the user to act (reauth-flow
    / renew the token), which is more actionable than "check the log".
    """

    translation_domain = DOMAIN
    translation_key = "bookstack_auth_failed"


async def _run_all_entries(
    hass: HomeAssistant,
    *,
    dry_run: bool,
    force: bool,
    log_prefix: str,
) -> None:
    """
    Run ``async_run_sync`` for every configured entry, isolating failures (#133).

    Before v0.15.0, a single unreachable/rejected BookStack instance made
    the whole ``run_now``/``preview`` service call raise immediately (HTTP
    500 to the caller) — so if the entry sorted first happened to be
    broken, every OTHER configured, perfectly healthy instance silently
    never got synced in that call. Every entry now gets a chance
    regardless of earlier failures; failures are logged per-entry via
    ``LOGGER.exception`` (full traceback, entry title for context), and a
    single aggregated error is raised at the end so the caller still sees
    that something failed instead of a silent partial success.
    """
    had_auth_failure = False
    had_other_failure = False
    for coordinator in _coordinators(hass):
        title = coordinator.config_entry.title
        LOGGER.info("%s (entry=%s, force=%s)", log_prefix, title, force)
        try:
            report = await coordinator.async_run_sync(dry_run=dry_run, force=force)
        except BookStackApiAuthError:
            LOGGER.exception("BookStack sync failed for %s (auth rejected)", title)
            had_auth_failure = True
        except BookStackApiError:
            LOGGER.exception("BookStack sync failed for %s", title)
            had_other_failure = True
        else:
            if dry_run:
                LOGGER.info("Preview result (%s): %s", title, report.as_dict())
    if had_auth_failure:
        raise BookStackSyncAuthFailedError
    if had_other_failure:
        raise BookStackUnreachableError


async def async_register_services(hass: HomeAssistant) -> None:
    """Register run_now, preview, and export_markdown."""
    if hass.services.has_service(DOMAIN, SERVICE_RUN_NOW):
        return

    async def _handle_run_now(call: ServiceCall) -> None:
        await _require_admin(hass, call)
        force = bool(call.data.get("force", False))
        await _run_all_entries(
            hass,
            dry_run=False,
            force=force,
            log_prefix="Running BookStack sync (run_now)",
        )

    async def _handle_preview(call: ServiceCall) -> None:
        await _require_admin(hass, call)
        force = bool(call.data.get("force", False))
        await _run_all_entries(
            hass,
            dry_run=True,
            force=force,
            log_prefix="Running BookStack sync preview (dry-run)",
        )

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
