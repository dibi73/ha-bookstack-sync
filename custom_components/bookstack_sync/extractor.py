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
class AutomationSnapshot:
    """One automation, scraped from the automation domain's state."""

    entity_id: str
    name: str
    description: str | None
    state: str | None
    mode: str | None
    last_triggered: str | None


@dataclass
class ScriptSnapshot:
    """One script, scraped from the script domain's state."""

    entity_id: str
    name: str
    description: str | None
    state: str | None
    last_triggered: str | None


@dataclass
class SceneSnapshot:
    """One scene, scraped from the scene domain's state."""

    entity_id: str
    name: str


@dataclass
class IntegrationSnapshot:
    """One config entry / installed integration."""

    entry_id: str
    domain: str
    title: str
    state: str
    source: str
    device_count: int
    entity_count: int


@dataclass
class HASnapshot:
    """Deterministic, fully-sorted view of HA used by the renderer."""

    areas: list[AreaSnapshot]
    unassigned_devices: list[DeviceSnapshot]
    automations: list[AutomationSnapshot]
    scripts: list[ScriptSnapshot]
    scenes: list[SceneSnapshot]
    integrations: list[IntegrationSnapshot]


def extract_snapshot(hass: HomeAssistant) -> HASnapshot:
    """
    Build a sorted snapshot of areas/devices/entities/automations/integrations.

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

    automations = _extract_automations(hass)
    scripts = _extract_scripts(hass)
    scenes = _extract_scenes(hass)
    integrations = _extract_integrations(hass, device_reg, entity_reg)

    return HASnapshot(
        areas=sorted_areas,
        unassigned_devices=unassigned,
        automations=automations,
        scripts=scripts,
        scenes=scenes,
        integrations=integrations,
    )


def _extract_automations(hass: HomeAssistant) -> list[AutomationSnapshot]:
    automations: list[AutomationSnapshot] = []
    for state in hass.states.async_all("automation"):
        attrs = state.attributes
        last = attrs.get("last_triggered")
        automations.append(
            AutomationSnapshot(
                entity_id=state.entity_id,
                name=attrs.get("friendly_name") or state.entity_id,
                description=attrs.get("description") or None,
                state=state.state,
                mode=attrs.get("mode"),
                last_triggered=last.isoformat() if hasattr(last, "isoformat") else last,
            ),
        )
    automations.sort(key=lambda a: (a.name.lower(), a.entity_id))
    return automations


def _extract_scripts(hass: HomeAssistant) -> list[ScriptSnapshot]:
    scripts: list[ScriptSnapshot] = []
    for state in hass.states.async_all("script"):
        attrs = state.attributes
        last = attrs.get("last_triggered")
        scripts.append(
            ScriptSnapshot(
                entity_id=state.entity_id,
                name=attrs.get("friendly_name") or state.entity_id,
                description=attrs.get("description") or None,
                state=state.state,
                last_triggered=last.isoformat() if hasattr(last, "isoformat") else last,
            ),
        )
    scripts.sort(key=lambda s: (s.name.lower(), s.entity_id))
    return scripts


def _extract_scenes(hass: HomeAssistant) -> list[SceneSnapshot]:
    scenes: list[SceneSnapshot] = []
    for state in hass.states.async_all("scene"):
        attrs = state.attributes
        scenes.append(
            SceneSnapshot(
                entity_id=state.entity_id,
                name=attrs.get("friendly_name") or state.entity_id,
            ),
        )
    scenes.sort(key=lambda s: (s.name.lower(), s.entity_id))
    return scenes


def _extract_integrations(
    hass: HomeAssistant,
    device_reg: dr.DeviceRegistry,
    entity_reg: er.EntityRegistry,
) -> list[IntegrationSnapshot]:
    devices_per_entry: dict[str, int] = {}
    for device in device_reg.devices.values():
        for entry_id in device.config_entries:
            devices_per_entry[entry_id] = devices_per_entry.get(entry_id, 0) + 1

    entities_per_entry: dict[str, int] = {}
    for entity in entity_reg.entities.values():
        if entity.config_entry_id:
            entities_per_entry[entity.config_entry_id] = (
                entities_per_entry.get(entity.config_entry_id, 0) + 1
            )

    integrations: list[IntegrationSnapshot] = []
    for entry in hass.config_entries.async_entries():
        # entry.state is an enum (ConfigEntryState); .value gives the human key
        state_value = getattr(entry.state, "value", str(entry.state))
        integrations.append(
            IntegrationSnapshot(
                entry_id=entry.entry_id,
                domain=entry.domain,
                title=entry.title or entry.domain,
                state=str(state_value),
                source=entry.source,
                device_count=devices_per_entry.get(entry.entry_id, 0),
                entity_count=entities_per_entry.get(entry.entry_id, 0),
            ),
        )
    integrations.sort(key=lambda i: (i.domain, i.title.lower(), i.entry_id))
    return integrations
