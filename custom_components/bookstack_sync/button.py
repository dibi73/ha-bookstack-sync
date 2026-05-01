"""
Button entities for BookStack Sync (issue #57).

Two buttons land on the integration's device card:

- ``Jetzt synchronisieren`` — fires ``coordinator.async_run_sync(dry_run=False)``
- ``Sync-Vorschau``        — fires ``coordinator.async_run_sync(dry_run=True)``

These mirror the ``bookstack_sync.run_now`` / ``bookstack_sync.preview``
services but show up directly on the device card so the user doesn't
have to walk through Developer Tools to trigger a sync.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import BookStackSyncCoordinator
    from .data import BookStackSyncConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001 - HA contract
    entry: BookStackSyncConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Register the run-now and preview buttons for this entry."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            BookStackSyncRunNowButton(coordinator),
            BookStackSyncPreviewButton(coordinator),
        ],
    )


class _BookStackSyncButtonBase(CoordinatorEntity, ButtonEntity):
    """
    Base class for BookStack-Sync buttons.

    Both buttons share the device-info, entity-category and
    coordinator-disabled-while-running gating.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BookStackSyncCoordinator,
        translation_key: str,
        unique_suffix: str,
        icon: str,
    ) -> None:
        """Bind to the coordinator and seed identifiers."""
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{unique_suffix}"
        self._attr_translation_key = translation_key
        self._attr_icon = icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=coordinator.config_entry.title,
            manufacturer="BookStack Sync",
            entry_type=None,
        )

    @property
    def available(self) -> bool:
        """
        Disable the button while a sync is in flight.

        Pressing during an active run would just queue behind the
        coordinator's lock, but greying it out is friendlier UX.
        """
        return not self.coordinator.is_syncing


class BookStackSyncRunNowButton(_BookStackSyncButtonBase):
    """Pressing this button kicks off a real sync immediately."""

    def __init__(self, coordinator: BookStackSyncCoordinator) -> None:
        """Wire the run-now button to the coordinator."""
        super().__init__(
            coordinator,
            translation_key="run_now",
            unique_suffix="run_now",
            icon="mdi:cloud-upload",
        )

    async def async_press(self) -> None:
        """Trigger an immediate full sync."""
        await self.coordinator.async_run_sync(dry_run=False)


class BookStackSyncPreviewButton(_BookStackSyncButtonBase):
    """Pressing this button performs a dry-run sync (logs only)."""

    def __init__(self, coordinator: BookStackSyncCoordinator) -> None:
        """Wire the preview button to the coordinator."""
        super().__init__(
            coordinator,
            translation_key="preview",
            unique_suffix="preview",
            icon="mdi:cloud-search",
        )

    async def async_press(self) -> None:
        """Trigger a dry-run sync — logs to HA log, writes nothing."""
        await self.coordinator.async_run_sync(dry_run=True)
