"""Status sensor for the BookStack Sync coordinator."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN

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
    """Register the single status sensor for this entry."""
    async_add_entities([BookStackSyncStatusSensor(entry.runtime_data.coordinator)])


class BookStackSyncStatusSensor(CoordinatorEntity, SensorEntity):
    """
    Surfaces the result of the last sync run as a single sensor entity.

    The state is one of ``ok`` / ``error`` / ``never_run``; the counts and the
    last-run timestamp live as attributes so they can be put on a dashboard
    or used in automations.
    """

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    _attr_translation_key = "sync_status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:book-sync"

    def __init__(self, coordinator: BookStackSyncCoordinator) -> None:
        """Bind to the coordinator and seed identifiers."""
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_sync_status"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=coordinator.config_entry.title,
            manufacturer="BookStack Sync",
            entry_type=None,
        )

    @property
    def native_value(self) -> str:
        """Top-level status: ``ok``, ``error`` or ``never_run``."""
        report = self.coordinator.last_report
        if report is None:
            return "never_run"
        if report.errors:
            return "error"
        return "ok"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Counts + timestamp for the last completed sync."""
        report = self.coordinator.last_report
        last_run = self.coordinator.last_run
        if report is None:
            return {
                "last_run": None,
                "created": 0,
                "updated": 0,
                "unchanged": 0,
                "tombstoned": 0,
                "skipped_conflict": 0,
                "errors": [],
                "total_pages": 0,
            }
        return {
            "last_run": last_run.isoformat() if last_run else None,
            "created": len(report.created),
            "updated": len(report.updated),
            "unchanged": len(report.unchanged),
            "tombstoned": len(report.tombstoned),
            "skipped_conflict": len(report.skipped_conflict),
            "errors": report.errors,
            "total_pages": (
                len(report.created)
                + len(report.updated)
                + len(report.unchanged)
                + len(report.tombstoned)
                + len(report.skipped_conflict)
            ),
        }
