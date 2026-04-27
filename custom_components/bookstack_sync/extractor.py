"""Extract Home Assistant registry data into deterministic dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from homeassistant.helpers import (
    area_registry as ar,
)
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


@dataclass
class EntitySnapshot:
    """One Home Assistant entity at the moment the sync ran."""

    entity_id: str
    name: str
    platform: str
    device_id: str | None
    area_id: str | None
    state: str | None
    attributes: dict
    disabled: bool


@dataclass
class DeviceSnapshot:
    """One Home Assistant device with its entity list."""

    device_id: str
    name: str
    manufacturer: str | None
    model: str | None
    sw_version: str | None
    hw_version: str | None
    area_id: str | None
    config_entries: tuple[str, ...]
    entities: list[EntitySnapshot] = field(default_factory=list)


@dataclass
class AreaSnapshot:
    """One Home Assistant area with the devices/entities assigned to it."""

    area_id: str
    name: str
    devices: list[DeviceSnapshot] = field(default_factory=list)
    orphan_entities: list[EntitySnapshot] = field(default_factory=list)


@dataclass
class HASnapshot:
    """Deterministic, fully-sorted view of HA used by the renderer."""

    areas: list[AreaSnapshot]
    unassigned_devices: list[DeviceSnapshot]


def extract_snapshot(hass: HomeAssistant) -> HASnapshot:
    """
    Build a sorted snapshot of areas/devices/entities.

    Sort order is stable so the renderer can produce byte-identical output
    when nothing actually changed -> avoids spurious BookStack revisions.
    """
    area_reg = ar.async_get(hass)
    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)

    areas: dict[str, AreaSnapshot] = {
        area.id: AreaSnapshot(area_id=area.id, name=area.name)
        for area in area_reg.areas.values()
    }

    devices: dict[str, DeviceSnapshot] = {}
    for device in device_reg.devices.values():
        devices[device.id] = DeviceSnapshot(
            device_id=device.id,
            name=device.name_by_user or device.name or device.id,
            manufacturer=device.manufacturer,
            model=device.model,
            sw_version=device.sw_version,
            hw_version=device.hw_version,
            area_id=device.area_id,
            config_entries=tuple(sorted(device.config_entries)),
        )

    orphan_entities_by_area: dict[str, list[EntitySnapshot]] = {}
    for entity in entity_reg.entities.values():
        state_obj = hass.states.get(entity.entity_id)
        snapshot = EntitySnapshot(
            entity_id=entity.entity_id,
            name=entity.name or entity.original_name or entity.entity_id,
            platform=entity.platform,
            device_id=entity.device_id,
            area_id=entity.area_id,
            state=state_obj.state if state_obj else None,
            attributes=dict(state_obj.attributes) if state_obj else {},
            disabled=entity.disabled,
        )
        if entity.device_id and entity.device_id in devices:
            devices[entity.device_id].entities.append(snapshot)
        else:
            area_id = entity.area_id or ""
            orphan_entities_by_area.setdefault(area_id, []).append(snapshot)

    unassigned: list[DeviceSnapshot] = []
    for device in devices.values():
        device.entities.sort(key=lambda e: e.entity_id)
        if device.area_id and device.area_id in areas:
            areas[device.area_id].devices.append(device)
        else:
            unassigned.append(device)

    for area in areas.values():
        area.devices.sort(key=lambda d: (d.name.lower(), d.device_id))
        area.orphan_entities = sorted(
            orphan_entities_by_area.get(area.area_id, []),
            key=lambda e: e.entity_id,
        )

    unassigned.sort(key=lambda d: (d.name.lower(), d.device_id))
    sorted_areas = sorted(areas.values(), key=lambda a: (a.name.lower(), a.area_id))

    return HASnapshot(areas=sorted_areas, unassigned_devices=unassigned)
