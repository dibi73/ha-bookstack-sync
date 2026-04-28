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
class AutomationSnapshot:
    """One automation, scraped from the automation domain's state."""

    entity_id: str
    name: str
    description: str | None
    state: str | None
    mode: str | None
    last_triggered: str | None
    area_id: str | None = None


@dataclass
class ScriptSnapshot:
    """One script, scraped from the script domain's state."""

    entity_id: str
    name: str
    description: str | None
    state: str | None
    last_triggered: str | None
    area_id: str | None = None


@dataclass
class SceneSnapshot:
    """One scene, scraped from the scene domain's state."""

    entity_id: str
    name: str
    area_id: str | None = None


@dataclass
class AreaSnapshot:
    """One Home Assistant area with the devices/entities assigned to it."""

    area_id: str
    name: str
    devices: list[DeviceSnapshot] = field(default_factory=list)
    orphan_entities: list[EntitySnapshot] = field(default_factory=list)
    automations: list[AutomationSnapshot] = field(default_factory=list)
    scripts: list[ScriptSnapshot] = field(default_factory=list)
    scenes: list[SceneSnapshot] = field(default_factory=list)


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
    automations: list[AutomationSnapshot]
    scripts: list[ScriptSnapshot]
    scenes: list[SceneSnapshot]
    integrations: list[IntegrationSnapshot]
    addons: list[AddonSnapshot]


def extract_snapshot(  # noqa: PLR0912 - cohesive registry walk; splitting hurts clarity
    hass: HomeAssistant,
    *,
    excluded_area_ids: Iterable[str] = (),
) -> HASnapshot:
    """
    Build a sorted snapshot of HA registries plus auxiliary data.

    Includes areas/devices/entities, automations/scripts/scenes/integrations
    and Supervisor add-ons (best-effort). ``excluded_area_ids`` skips entire
    areas (and their devices) so the user can keep certain rooms out of the
    wiki without losing the rest of the documentation. Sort order is stable
    so the renderer can produce byte-identical output when nothing actually
    changed.
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
        # Skip stub devices that some integrations leave behind: no name AND
        # no user-given name. We later filter again on entity-emptiness so
        # only useful devices land in the wiki.
        display_name = device.name_by_user or device.name
        if not display_name:
            continue
        devices[device.id] = DeviceSnapshot(
            device_id=device.id,
            name=display_name,
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

    automations = _extract_automations(hass, entity_reg)
    scripts = _extract_scripts(hass, entity_reg)
    scenes = _extract_scenes(hass, entity_reg)

    # Route automations / scripts / scenes that carry an area_id (set in the
    # HA entity registry) onto the corresponding area page. They still
    # appear on the bundle pages too - the bundle is the master index.
    for automation in automations:
        if automation.area_id and automation.area_id in areas:
            areas[automation.area_id].automations.append(automation)
    for script in scripts:
        if script.area_id and script.area_id in areas:
            areas[script.area_id].scripts.append(script)
    for scene in scenes:
        if scene.area_id and scene.area_id in areas:
            areas[scene.area_id].scenes.append(scene)

    sorted_areas = sorted(areas.values(), key=lambda a: (a.name.lower(), a.area_id))

    return HASnapshot(
        areas=sorted_areas,
        unassigned_devices=unassigned,
        automations=automations,
        scripts=scripts,
        scenes=scenes,
        integrations=_extract_integrations(hass, device_reg, entity_reg),
        addons=_extract_addons(hass),
    )


def _mqtt_topic_from(attrs: dict) -> str | None:
    """Return the most informative topic-like attribute, or None."""
    for key in _MQTT_TOPIC_KEYS:
        value = attrs.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _entity_area(
    entity_reg: er.EntityRegistry,
    entity_id: str,
) -> str | None:
    """Look up ``entity_id``'s ``area_id`` in the entity registry, if any."""
    entry = entity_reg.async_get(entity_id)
    return entry.area_id if entry else None


def _extract_automations(
    hass: HomeAssistant,
    entity_reg: er.EntityRegistry,
) -> list[AutomationSnapshot]:
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
                area_id=_entity_area(entity_reg, state.entity_id),
            ),
        )
    automations.sort(key=lambda a: (a.name.lower(), a.entity_id))
    return automations


def _extract_scripts(
    hass: HomeAssistant,
    entity_reg: er.EntityRegistry,
) -> list[ScriptSnapshot]:
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
                area_id=_entity_area(entity_reg, state.entity_id),
            ),
        )
    scripts.sort(key=lambda s: (s.name.lower(), s.entity_id))
    return scripts


def _extract_scenes(
    hass: HomeAssistant,
    entity_reg: er.EntityRegistry,
) -> list[SceneSnapshot]:
    scenes: list[SceneSnapshot] = []
    for state in hass.states.async_all("scene"):
        attrs = state.attributes
        scenes.append(
            SceneSnapshot(
                entity_id=state.entity_id,
                name=attrs.get("friendly_name") or state.entity_id,
                area_id=_entity_area(entity_reg, state.entity_id),
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
