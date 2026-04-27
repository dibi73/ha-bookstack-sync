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

from .const import LOGGER

if TYPE_CHECKING:
    from collections.abc import Iterable

    from homeassistant.core import HomeAssistant


# Common attribute names that Tasmota / Shelly / generic MQTT integrations
# use to expose the topic, in priority order.
_MQTT_TOPIC_KEYS = ("topic", "state_topic", "command_topic", "mqtt_topic")


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
    mqtt_topic: str | None = None


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
class AddonSnapshot:
    """One Supervisor add-on (only available on HassOS / Supervised installs)."""

    slug: str
    name: str
    version: str | None
    state: str | None
    update_available: bool


@dataclass
class HASnapshot:
    """Deterministic, fully-sorted view of HA used by the renderer."""

    areas: list[AreaSnapshot]
    unassigned_devices: list[DeviceSnapshot]
    addons: list[AddonSnapshot]


def extract_snapshot(
    hass: HomeAssistant,
    *,
    excluded_area_ids: Iterable[str] = (),
) -> HASnapshot:
    """
    Build a sorted snapshot of areas/devices/entities/add-ons.

    ``excluded_area_ids`` skips entire areas (and their devices) so the user
    can keep certain rooms out of the wiki without losing the rest of the
    documentation. Sort order is stable so the renderer can produce
    byte-identical output when nothing actually changed.
    """
    excluded = set(excluded_area_ids)

    area_reg = ar.async_get(hass)
    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)

    areas: dict[str, AreaSnapshot] = {
        area.id: AreaSnapshot(area_id=area.id, name=area.name)
        for area in area_reg.areas.values()
        if area.id not in excluded
    }

    devices: dict[str, DeviceSnapshot] = {}
    for device in device_reg.devices.values():
        if device.area_id in excluded:
            continue
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
        if entity.area_id in excluded:
            continue
        if entity.device_id and entity.device_id not in devices:
            # Device was filtered out -> skip its entities too.
            continue
        state_obj = hass.states.get(entity.entity_id)
        attrs = dict(state_obj.attributes) if state_obj else {}
        snapshot = EntitySnapshot(
            entity_id=entity.entity_id,
            name=entity.name or entity.original_name or entity.entity_id,
            platform=entity.platform,
            device_id=entity.device_id,
            area_id=entity.area_id,
            state=state_obj.state if state_obj else None,
            attributes=attrs,
            disabled=entity.disabled,
            mqtt_topic=_mqtt_topic_from(attrs),
        )
        if entity.device_id:
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

    return HASnapshot(
        areas=sorted_areas,
        unassigned_devices=unassigned,
        addons=_extract_addons(hass),
    )


def _mqtt_topic_from(attrs: dict) -> str | None:
    """Return the most informative topic-like attribute, or None."""
    for key in _MQTT_TOPIC_KEYS:
        value = attrs.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _extract_addons(hass: HomeAssistant) -> list[AddonSnapshot]:
    """Best-effort add-on listing - empty unless HA Supervisor is available."""
    try:
        from homeassistant.components.hassio import (  # noqa: PLC0415 - optional dep
            get_addons_info,
            is_hassio,
        )
    except ImportError:
        return []

    try:
        if not is_hassio(hass):
            return []
        addons_dict = get_addons_info(hass) or {}
    except Exception as err:  # noqa: BLE001 - third-party call, never fatal
        LOGGER.debug("Could not query Supervisor add-ons: %s", err)
        return []

    addons: list[AddonSnapshot] = []
    for slug, info in addons_dict.items():
        if not isinstance(info, dict):
            continue
        addons.append(
            AddonSnapshot(
                slug=slug,
                name=info.get("name") or slug,
                version=info.get("version"),
                state=info.get("state"),
                update_available=bool(info.get("update_available")),
            ),
        )
    addons.sort(key=lambda a: (a.name.lower(), a.slug))
    return addons
