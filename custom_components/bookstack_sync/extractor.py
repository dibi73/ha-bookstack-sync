"""Extract Home Assistant registry data into deterministic dataclasses."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from pathlib import Path
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

# Attribute keys we accept as IP / hostname on a device_tracker. UniFi,
# the generic device_tracker, ASUSWRT and FRITZ!Box all use slight
# variations. First match wins.
_TRACKER_IP_KEYS = ("ip", "ip_address", "address")
_TRACKER_HOST_KEYS = ("hostname", "host", "host_name")
_TRACKER_MAC_KEYS = ("mac", "mac_address")
_TRACKER_LAST_SEEN_KEYS = ("last_seen", "last_time_reachable")
_TRACKER_SSID_KEYS = ("essid", "ssid")
_TRACKER_VLAN_KEYS = ("network", "vlan", "vlan_name")


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
class NetworkInfo:
    """
    Network connection metadata for one HA device.

    Sourced from a ``device_tracker.*`` entity attached to the device
    (preferred — has live IP / last-seen) or from the device-registry's
    ``connections`` set (fallback — gives MAC only). UniFi-specific
    fields are populated when the source tracker comes from the
    ``unifi`` platform.
    """

    ip: str | None = None
    mac: str | None = None
    hostname: str | None = None
    connection_type: str | None = None  # "wired" / "wireless" / "unknown"
    last_seen: str | None = None
    ssid: str | None = None
    vlan: str | None = None
    signal_strength: int | None = None
    # UniFi-specific (None when source isn't UniFi)
    switch_mac: str | None = None
    switch_port: int | None = None
    ap_mac: str | None = None
    oui: str | None = None
    source_platform: str | None = None  # "unifi", "device_tracker", "registry"


@dataclass(frozen=True)
class DeviceIntegrationRef:
    """
    A device's link to one config entry (= one installed integration).

    Carries both ``entry_id`` (stable HA-internal handle) and ``domain``
    (human-readable, also what HA uses in its frontend URL
    ``/config/integrations/integration/<domain>``). v0.14.5 introduced
    this so the device page can render the friendly domain name and a
    deep-link instead of the ULID-style entry_id that pre-v0.14.5 builds
    accidentally exposed in the Stammdaten table.
    """

    entry_id: str
    domain: str


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
    config_entries: tuple[DeviceIntegrationRef, ...]
    entities: list[EntitySnapshot] = field(default_factory=list)
    # Primary network identity for this device. ``network_extra`` lists
    # additional concurrent connections (e.g. NUC plugged in via both
    # ethernet and WiFi). Sorted by ``last_seen`` desc, primary first.
    network: NetworkInfo | None = None
    network_extra: list[NetworkInfo] = field(default_factory=list)


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
    documentation_url: str | None = None


@dataclass
class AddonSnapshot:
    """One Supervisor add-on (only available on HassOS / Supervised installs)."""

    slug: str
    name: str
    version: str | None
    state: str | None
    update_available: bool


@dataclass
class UnifiInfraNode:
    """
    One UniFi infrastructure device (gateway / switch / AP).

    ``role`` is heuristically derived from the device's model string
    (USG/UDM → gateway, USW → switch, UAP/U6 → ap). Sub-classification
    drives the topology-tree rendering.
    """

    device_id: str
    name: str
    model: str
    role: str  # "gateway" / "switch" / "ap" / "other"
    mac: str | None
    ip: str | None
    parent_device_id: str | None  # via_device_id, None if root
    # Resolved post-walk: list of children's device_ids, sorted.
    child_device_ids: list[str] = field(default_factory=list)


@dataclass
class UnifiTopology:
    """Snapshot of UniFi LAN topology at sync time."""

    nodes: dict[str, UnifiInfraNode] = field(default_factory=dict)
    root_device_ids: list[str] = field(default_factory=list)
    # client device_id → infra device_id it physically connects to (switch
    # for wired, AP for wireless). Built by joining NetworkInfo's
    # ``switch_mac`` / ``ap_mac`` against UniFi infra MACs.
    client_to_infra: dict[str, str] = field(default_factory=dict)


@dataclass
class BluetoothDeviceHeard:
    """One BT device heard by a scanner."""

    name: str
    address: str  # MAC
    last_seen: str | None = None


@dataclass
class BluetoothScanner:
    """One BT scanner — HA's local adapter or an ESPHome proxy."""

    name: str
    is_proxy: bool  # False = HA-host's own BT adapter
    devices_heard: list[BluetoothDeviceHeard] = field(default_factory=list)


@dataclass
class BluetoothNetwork:
    """Snapshot of all BT scanners + the BT devices each heard."""

    scanners: list[BluetoothScanner] = field(default_factory=list)


@dataclass
class ServiceInfo:
    """A registered HA service (notify, tts, ...)."""

    domain: str  # "notify" or "tts"
    name: str  # e.g. "mobile_app_my_phone"
    description: str | None = None


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
    # UniFi device_trackers whose target entity is NOT linked to any HA
    # device — clients UniFi sees but HA doesn't know about. Useful for
    # spotting unknown / unwanted devices on the LAN.
    unknown_unifi_clients: list[NetworkInfo] = field(default_factory=list)
    # UniFi LAN topology (gateway / switches / APs) when the unifi
    # integration is loaded; empty otherwise.
    unifi_topology: UnifiTopology | None = None
    # Bluetooth scanners + heard devices when at least one BT proxy or
    # native HA BT adapter is configured; ``None`` otherwise.
    bluetooth: BluetoothNetwork | None = None
    # Notify and TTS services registered with HA. Empty when none.
    notify_services: list[ServiceInfo] = field(default_factory=list)
    tts_services: list[ServiceInfo] = field(default_factory=list)
    # Recorder configuration when the recorder integration is loaded.
    recorder: RecorderConfig | None = None
    # MQTT topic hierarchy when at least one entity has an mqtt_topic.
    mqtt_tree: MqttTopicTree | None = None
    # Energy-Dashboard configuration when ``.storage/energy`` exists.
    energy: EnergyConfig | None = None
    # Helper entities (input_*, timer, counter, schedule, ...) per domain.
    helpers: list[HelperGroup] = field(default_factory=list)
    # entity_id → list of (automation/script/scene) entries that reference it.
    # Populated from YAML config files (automations.yaml etc).
    reverse_usage: dict[str, list[ReverseUsageEntry]] = field(default_factory=dict)


def extract_snapshot(  # noqa: PLR0912, PLR0915 - cohesive registry walk
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

    # v0.14.5: pre-resolve entry_id -> domain so DeviceSnapshot.config_entries
    # can carry both. Pre-v0.14.5 the device's ``Integrationen`` cell
    # accidentally rendered ULID-style entry_ids; users want the friendly
    # domain plus a clickable deep-link to
    # ``/config/integrations/integration/<domain>``.
    entry_domains = {
        entry.entry_id: entry.domain for entry in hass.config_entries.async_entries()
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
        device_refs = tuple(
            DeviceIntegrationRef(
                entry_id=eid,
                # Fallback to entry_id for the rare orphan case where a
                # device still references an entry that's already gone
                # from hass.config_entries — better than crashing.
                domain=entry_domains.get(eid, eid),
            )
            for eid in sorted(device.config_entries)
        )
        devices[device.id] = DeviceSnapshot(
            device_id=device.id,
            name=display_name,
            manufacturer=device.manufacturer,
            model=device.model,
            sw_version=device.sw_version,
            hw_version=device.hw_version,
            area_id=device.area_id,
            config_entries=device_refs,
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
        _populate_network_info(device, device_reg)
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

    snapshot = HASnapshot(
        areas=sorted_areas,
        unassigned_devices=unassigned,
        automations=automations,
        scripts=scripts,
        scenes=scenes,
        integrations=_extract_integrations(hass, device_reg, entity_reg),
        addons=_extract_addons(hass),
        unknown_unifi_clients=_extract_unknown_unifi_clients(hass, entity_reg),
    )
    snapshot.unifi_topology = _extract_unifi_topology(device_reg, snapshot)
    snapshot.bluetooth = _extract_bluetooth_network(device_reg)
    snapshot.notify_services = _extract_services(hass, "notify")
    snapshot.tts_services = _extract_services(hass, "tts")
    snapshot.recorder = _extract_recorder_config(hass)
    snapshot.mqtt_tree = _build_mqtt_topic_tree(snapshot)
    snapshot.energy = _extract_energy_config(hass)
    snapshot.helpers = _extract_helpers(hass, entity_reg)
    snapshot.reverse_usage = _extract_reverse_usage(hass)
    return snapshot


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


def _automation_entity_ids(
    hass: HomeAssistant,
    entity_reg: er.EntityRegistry,
) -> set[str]:
    """
    Return union of entity_ids in registry + state-machine.

    Walking only the entity_registry misses YAML-defined automations
    that show up in ``hass.states`` but not the registry; walking only
    ``hass.states`` misses disabled automations + ones lost to startup
    race conditions. Union of both (issue #39).
    """
    ids: set[str] = {
        e.entity_id
        for e in entity_reg.entities.values()
        if e.entity_id.startswith("automation.")
    }
    ids.update(s.entity_id for s in hass.states.async_all("automation"))
    return ids


def _extract_automations(
    hass: HomeAssistant,
    entity_reg: er.EntityRegistry,
) -> list[AutomationSnapshot]:
    automations: list[AutomationSnapshot] = []
    for entity_id in _automation_entity_ids(hass, entity_reg):
        registry_entry = entity_reg.async_get(entity_id)
        state_obj = hass.states.get(entity_id)
        attrs = state_obj.attributes if state_obj else {}
        last = attrs.get("last_triggered")
        name = (
            (registry_entry.name if registry_entry else None)
            or (registry_entry.original_name if registry_entry else None)
            or attrs.get("friendly_name")
            or entity_id
        )
        area_id = registry_entry.area_id if registry_entry else None
        automations.append(
            AutomationSnapshot(
                entity_id=entity_id,
                name=name,
                description=attrs.get("description") or None,
                state=state_obj.state if state_obj else "disabled",
                mode=attrs.get("mode"),
                last_triggered=last.isoformat() if hasattr(last, "isoformat") else last,
                area_id=area_id,
            ),
        )
    automations.sort(key=lambda a: (a.name.lower(), a.entity_id))
    return automations


def _extract_scripts(
    hass: HomeAssistant,
    entity_reg: er.EntityRegistry,
) -> list[ScriptSnapshot]:
    scripts: list[ScriptSnapshot] = []
    ids: set[str] = {
        e.entity_id
        for e in entity_reg.entities.values()
        if e.entity_id.startswith("script.")
    }
    ids.update(s.entity_id for s in hass.states.async_all("script"))
    for entity_id in ids:
        registry_entry = entity_reg.async_get(entity_id)
        state_obj = hass.states.get(entity_id)
        attrs = state_obj.attributes if state_obj else {}
        last = attrs.get("last_triggered")
        name = (
            (registry_entry.name if registry_entry else None)
            or (registry_entry.original_name if registry_entry else None)
            or attrs.get("friendly_name")
            or entity_id
        )
        area_id = registry_entry.area_id if registry_entry else None
        scripts.append(
            ScriptSnapshot(
                entity_id=entity_id,
                name=name,
                description=attrs.get("description") or None,
                state=state_obj.state if state_obj else "disabled",
                last_triggered=last.isoformat() if hasattr(last, "isoformat") else last,
                area_id=area_id,
            ),
        )
    scripts.sort(key=lambda s: (s.name.lower(), s.entity_id))
    return scripts


def _extract_scenes(
    hass: HomeAssistant,
    entity_reg: er.EntityRegistry,
) -> list[SceneSnapshot]:
    scenes: list[SceneSnapshot] = []
    ids: set[str] = {
        e.entity_id
        for e in entity_reg.entities.values()
        if e.entity_id.startswith("scene.")
    }
    ids.update(s.entity_id for s in hass.states.async_all("scene"))
    for entity_id in ids:
        registry_entry = entity_reg.async_get(entity_id)
        state_obj = hass.states.get(entity_id)
        attrs = state_obj.attributes if state_obj else {}
        name = (
            (registry_entry.name if registry_entry else None)
            or (registry_entry.original_name if registry_entry else None)
            or attrs.get("friendly_name")
            or entity_id
        )
        area_id = registry_entry.area_id if registry_entry else None
        scenes.append(
            SceneSnapshot(
                entity_id=entity_id,
                name=name,
                area_id=area_id,
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
        # device_reg's devices iterate the raw HA registry here (not our
        # filtered DeviceSnapshots), so the values are still entry_id strings.
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
                documentation_url=_documentation_url_for(hass, entry.domain),
            ),
        )
    integrations.sort(key=lambda i: (i.domain, i.title.lower(), i.entry_id))
    return integrations


def _documentation_url_for(hass: HomeAssistant, domain: str) -> str | None:
    """
    Return the integration's documentation URL, or None.

    Uses HAs already-loaded integration registry (sync) so we don't have
    to await anything. For core integrations this resolves to the
    canonical ``home-assistant.io/integrations/<domain>/``; for custom
    integrations to whatever the manifest's ``documentation`` field points
    at (typically the GitHub repo).
    """
    try:
        from homeassistant.loader import (  # noqa: PLC0415 - local import keeps top clean
            async_get_loaded_integration,
        )
    except ImportError:
        return None
    try:
        integration = async_get_loaded_integration(hass, domain)
    except Exception:  # noqa: BLE001 - best-effort enrichment, never fatal
        return None
    return getattr(integration, "documentation", None) or None


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


def _device_macs_from_connections(device: dr.DeviceEntry) -> list[str]:
    """Pull MAC addresses out of ``device.connections`` (set of tuples)."""
    macs: list[str] = []
    for conn_type, value in device.connections:
        if conn_type == dr.CONNECTION_NETWORK_MAC and isinstance(value, str):
            macs.append(value)
    return sorted(macs)


def _first_str(attrs: dict, keys: tuple[str, ...]) -> str | None:
    """Return the first non-empty string-valued attribute among ``keys``."""
    for key in keys:
        value = attrs.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _detect_connection_type(attrs: dict) -> str | None:
    """Infer ``wired`` / ``wireless`` / ``None`` from a tracker's attributes."""
    if attrs.get("switch_mac") or attrs.get("switch_port") is not None:
        return "wired"
    if attrs.get("ap_mac") or _first_str(attrs, _TRACKER_SSID_KEYS):
        return "wireless"
    return None


def _build_network_info(
    entity: EntitySnapshot,
    fallback_macs: list[str],
) -> NetworkInfo | None:
    """
    Build a ``NetworkInfo`` from one device_tracker entity's state.

    Returns ``None`` if the tracker has no useful network data (no IP and
    no MAC anywhere — pure presence sensor or stale registration).
    """
    attrs = entity.attributes
    ip = _first_str(attrs, _TRACKER_IP_KEYS)
    mac = _first_str(attrs, _TRACKER_MAC_KEYS) or (
        fallback_macs[0] if fallback_macs else None
    )
    if not (ip or mac):
        return None

    hostname = _first_str(attrs, _TRACKER_HOST_KEYS) or entity.name
    last_seen_value = attrs.get("last_seen") or attrs.get("last_time_reachable")
    last_seen = (
        last_seen_value.isoformat()
        if hasattr(last_seen_value, "isoformat")
        else (last_seen_value if isinstance(last_seen_value, str) else None)
    )
    connection_type = _detect_connection_type(attrs)
    ssid = (
        _first_str(attrs, _TRACKER_SSID_KEYS) if connection_type == "wireless" else None
    )
    vlan = _first_str(attrs, _TRACKER_VLAN_KEYS)

    rssi_raw = attrs.get("rssi")
    signal = rssi_raw if isinstance(rssi_raw, int) else None

    switch_port_raw = attrs.get("switch_port")
    switch_port = switch_port_raw if isinstance(switch_port_raw, int) else None

    return NetworkInfo(
        ip=ip,
        mac=mac,
        hostname=hostname,
        connection_type=connection_type,
        last_seen=last_seen,
        ssid=ssid,
        vlan=vlan,
        signal_strength=signal,
        switch_mac=attrs.get("switch_mac")
        if isinstance(attrs.get("switch_mac"), str)
        else None,
        switch_port=switch_port,
        ap_mac=attrs.get("ap_mac") if isinstance(attrs.get("ap_mac"), str) else None,
        oui=attrs.get("oui") if isinstance(attrs.get("oui"), str) else None,
        source_platform=entity.platform,
    )


def _is_private_ip(ip: str | None) -> bool:
    """
    Return ``True`` when ``ip`` is in an RFC1918 / link-local range.

    Used to prefer LAN-side IPs over WAN-side ones when ranking the
    connections of a router / gateway. WAN IPs change frequently with
    DHCP from the ISP and are operationally less interesting than the
    static internal management IP.
    """
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.is_private or addr.is_link_local


def _populate_network_info(
    device_snap: DeviceSnapshot,
    device_reg: dr.DeviceRegistry,
) -> None:
    """
    Fill ``device_snap.network`` and ``.network_extra`` from trackers + connections.

    Strategy:
    1. For every ``device_tracker.*`` entity attached to this device, build
       a ``NetworkInfo`` from its state attributes.
    2. Sort: private (RFC1918 / link-local) IPs first, then by
       ``last_seen`` desc within each group. Routers / gateways have both
       a public WAN IP and a private LAN IP; the LAN one is always the
       useful one for documentation purposes.
    3. If no tracker carried useful data, fall back to a MAC-only NetworkInfo
       sourced from the device-registry's ``connections`` set (Zigbee /
       Matter devices often have a MAC there but no live tracker).
    """
    device = device_reg.async_get(device_snap.device_id)
    fallback_macs = _device_macs_from_connections(device) if device else []

    trackers = [
        e for e in device_snap.entities if e.entity_id.startswith("device_tracker.")
    ]
    infos: list[NetworkInfo] = []
    for tracker in trackers:
        info = _build_network_info(tracker, fallback_macs)
        if info:
            infos.append(info)

    # Two-pass stable sort: first break ties by last_seen desc (most
    # recent first), then prepend the private-IP entries. End result:
    # private IPs in last-seen-desc order, then non-private IPs in
    # last-seen-desc order. Critical for routers / gateways which carry
    # both a public WAN IP and a private LAN IP — the LAN one is always
    # the useful one for documentation.
    infos.sort(key=lambda i: i.last_seen or "", reverse=True)
    infos.sort(key=lambda i: 0 if _is_private_ip(i.ip) else 1)

    if not infos and fallback_macs:
        infos = [
            NetworkInfo(
                mac=fallback_macs[0],
                source_platform="registry",
            ),
        ]

    if infos:
        device_snap.network = infos[0]
        device_snap.network_extra = infos[1:]


def _extract_unknown_unifi_clients(
    hass: HomeAssistant,
    entity_reg: er.EntityRegistry,
) -> list[NetworkInfo]:
    """
    Return UniFi-tracked clients that are NOT linked to any HA device.

    These are clients UniFi sees on the network but the user has not
    promoted to a full HA device — phones of guests, raw IoT gadgets,
    forgotten LAN cabling. Useful for the cross-reference section on
    the Netzwerk page.
    """
    unknown: list[NetworkInfo] = []
    for entity_entry in entity_reg.entities.values():
        if entity_entry.platform != "unifi":
            continue
        if not entity_entry.entity_id.startswith("device_tracker."):
            continue
        if entity_entry.device_id:
            # Has a HA device — already represented on the main table.
            continue
        state_obj = hass.states.get(entity_entry.entity_id)
        if state_obj is None:
            continue
        attrs = dict(state_obj.attributes)
        synthetic = EntitySnapshot(
            entity_id=entity_entry.entity_id,
            name=entity_entry.name
            or entity_entry.original_name
            or entity_entry.entity_id,
            platform="unifi",
            device_id=None,
            area_id=None,
            state=state_obj.state,
            attributes=attrs,
            disabled=entity_entry.disabled,
        )
        info = _build_network_info(synthetic, fallback_macs=[])
        if info:
            unknown.append(info)

    unknown.sort(key=lambda i: (i.last_seen or "", i.hostname or ""), reverse=True)
    return unknown


def _classify_unifi_role(model: str) -> str:
    """Heuristically classify a UniFi device's role from its model string."""
    upper = model.upper() if model else ""
    if any(t in upper for t in ("USG", "UDM", "UCG", "GATEWAY")):
        return "gateway"
    if any(t in upper for t in ("USW", "US-", "SWITCH")):
        return "switch"
    if any(t in upper for t in ("UAP", "U6", "U7", "UB", "ACCESS POINT")):
        return "ap"
    return "other"


def _device_first_mac(device: dr.DeviceEntry) -> str | None:
    """Return the first MAC address on a device, or None."""
    for conn_type, value in device.connections:
        if conn_type == dr.CONNECTION_NETWORK_MAC and isinstance(value, str):
            return value
    return None


_UNIFI_MANUFACTURERS = frozenset(
    {"Ubiquiti", "Ubiquiti Inc.", "Ubiquiti Networks"},
)


def _extract_unifi_topology(
    device_reg: dr.DeviceRegistry,
    snapshot: HASnapshot,
) -> UnifiTopology | None:
    """
    Build a UniFi topology snapshot by walking the HA device registry.

    Returns ``None`` when no UniFi infra is found (integration not
    installed or only clients tracked).
    """
    nodes: dict[str, UnifiInfraNode] = {}
    for device in device_reg.devices.values():
        if device.manufacturer not in _UNIFI_MANUFACTURERS:
            continue
        role = _classify_unifi_role(device.model or "")
        if role == "other":
            # Probably a client device the UniFi integration created (rare);
            # skip it to keep the topology focused on infra.
            continue
        nodes[device.id] = UnifiInfraNode(
            device_id=device.id,
            name=device.name_by_user or device.name or device.model or device.id,
            model=device.model or "",
            role=role,
            mac=_device_first_mac(device),
            ip=None,  # Filled if a tracker links this device — not always
            parent_device_id=device.via_device_id,
        )

    if not nodes:
        return None

    # Resolve children + roots.
    for node in nodes.values():
        if node.parent_device_id and node.parent_device_id in nodes:
            nodes[node.parent_device_id].child_device_ids.append(node.device_id)
    for node in nodes.values():
        node.child_device_ids.sort(
            key=lambda cid: (nodes[cid].role, nodes[cid].name.lower()),
        )
    roots = sorted(
        (
            n.device_id
            for n in nodes.values()
            if not n.parent_device_id or n.parent_device_id not in nodes
        ),
        key=lambda did: (nodes[did].role != "gateway", nodes[did].name.lower()),
    )

    # Build client → infra map: walk every device in the snapshot, look
    # at switch_mac (wired) or ap_mac (wireless), match against infra MAC.
    mac_to_infra_id = {n.mac.lower(): n.device_id for n in nodes.values() if n.mac}
    client_to_infra: dict[str, str] = {}

    def visit_device(device_snap: DeviceSnapshot) -> None:
        info = device_snap.network
        if info is None:
            return
        target_mac = (info.switch_mac or info.ap_mac or "").lower()
        if target_mac and target_mac in mac_to_infra_id:
            client_to_infra[device_snap.device_id] = mac_to_infra_id[target_mac]

    for area in snapshot.areas:
        for d in area.devices:
            visit_device(d)
    for d in snapshot.unassigned_devices:
        visit_device(d)

    return UnifiTopology(
        nodes=nodes,
        root_device_ids=roots,
        client_to_infra=client_to_infra,
    )


def _device_first_bt_address(device: dr.DeviceEntry) -> str | None:
    """Return the first Bluetooth MAC on a device, or None."""
    for conn_type, value in device.connections:
        if conn_type == dr.CONNECTION_BLUETOOTH and isinstance(value, str):
            return value
    return None


def _is_bt_proxy_device(device: dr.DeviceEntry) -> bool:
    """
    Heuristic: ESPHome devices with bluetooth_proxy entities act as proxies.

    ESPHome's BT-proxy support exposes the underlying BT adapter as a
    HA device that other BLE devices link to via ``via_device_id``. We
    detect proxies by:
    - manufacturer mention "ESPHome"
    - or model containing "bluetooth proxy" / "ble proxy"
    - or any HA device with at least one ``via_device_id`` pointing here
      AND that pointer-device has CONNECTION_BLUETOOTH (i.e. children
      are BT devices)
    The third heuristic is left to caller — it has the registry to walk.
    """
    manuf = (device.manufacturer or "").lower()
    model = (device.model or "").lower()
    if "esphome" in manuf:
        return True
    return "bluetooth proxy" in model or "ble proxy" in model


def _extract_bluetooth_network(
    device_reg: dr.DeviceRegistry,
) -> BluetoothNetwork | None:
    """
    Group BT-tracked HA devices by the proxy / scanner that heard them.

    Returns ``None`` when no Bluetooth-connected device exists.
    """
    bt_devices: list[dr.DeviceEntry] = [
        d
        for d in device_reg.devices.values()
        if any(c[0] == dr.CONNECTION_BLUETOOTH for c in d.connections)
    ]
    if not bt_devices:
        return None

    # device_id → proxy device (None = local HA adapter)
    by_proxy: dict[str | None, list[dr.DeviceEntry]] = {}
    for d in bt_devices:
        proxy_id = d.via_device_id or None
        # Skip proxies themselves from the heard-list.
        by_proxy.setdefault(proxy_id, []).append(d)

    # Build BluetoothScanner entries.
    scanners: list[BluetoothScanner] = []

    for proxy_id, heard in by_proxy.items():
        if proxy_id is None:
            scanner = BluetoothScanner(name="local", is_proxy=False)
        else:
            proxy_device = device_reg.async_get(proxy_id)
            if proxy_device is None:
                continue
            scanner = BluetoothScanner(
                name=(
                    proxy_device.name_by_user
                    or proxy_device.name
                    or proxy_device.model
                    or proxy_id
                ),
                is_proxy=True,
            )
        for hd in sorted(heard, key=lambda d: (d.name or d.id).lower()):
            display_name = hd.name_by_user or hd.name or hd.id
            address = _device_first_bt_address(hd) or "—"
            scanner.devices_heard.append(
                BluetoothDeviceHeard(
                    name=display_name,
                    address=address,
                ),
            )
        scanners.append(scanner)

    # Order: local first, then proxies alphabetically.
    scanners.sort(key=lambda s: (s.is_proxy, s.name.lower()))

    if not scanners:
        return None
    return BluetoothNetwork(scanners=scanners)


def _extract_services(hass: HomeAssistant, domain: str) -> list[ServiceInfo]:
    """List services registered under ``domain`` (e.g. ``notify`` / ``tts``)."""
    domain_services = hass.services.async_services().get(domain, {})
    services = [ServiceInfo(domain=domain, name=name) for name in domain_services]
    services.sort(key=lambda s: s.name.lower())
    return services


# Temporary file — content will be appended to extractor.py and deleted.


# ----- #48 Recorder -----------------------------------------------------------


@dataclass
class RecorderConfig:
    """Snapshot of HA's recorder configuration."""

    db_engine: str | None = None
    db_url_redacted: str | None = None
    purge_keep_days: int | None = None
    excluded_domains: list[str] = field(default_factory=list)
    excluded_entities: list[str] = field(default_factory=list)
    included_domains: list[str] = field(default_factory=list)
    included_entities: list[str] = field(default_factory=list)


def _extract_recorder_config(hass: HomeAssistant) -> RecorderConfig | None:
    """Best-effort recorder config snapshot. Returns None when not available."""
    recorder_data = hass.data.get("recorder_instance") or hass.data.get("recorder")
    if recorder_data is None:
        return None

    rc = RecorderConfig()
    keep_days = getattr(recorder_data, "keep_days", None) or getattr(
        recorder_data,
        "purge_keep_days",
        None,
    )
    if isinstance(keep_days, int):
        rc.purge_keep_days = keep_days

    db_url = getattr(recorder_data, "db_url", None)
    if isinstance(db_url, str):
        import re  # noqa: PLC0415 - one-shot use

        rc.db_url_redacted = re.sub(r"//[^@]+@", "//<redacted>@", db_url)
        if db_url.startswith("sqlite:"):
            rc.db_engine = "sqlite"
        elif db_url.startswith("mysql"):
            rc.db_engine = "mariadb/mysql"
        elif db_url.startswith("postgres"):
            rc.db_engine = "postgresql"

    entity_filter = getattr(recorder_data, "entity_filter", None)
    if entity_filter is not None:
        for attr_name, target in (
            ("_exclude_d", "excluded_domains"),
            ("_exclude_e", "excluded_entities"),
            ("_include_d", "included_domains"),
            ("_include_e", "included_entities"),
        ):
            value = getattr(entity_filter, attr_name, None)
            if isinstance(value, (list, set, tuple)):
                getattr(rc, target).extend(sorted(str(v) for v in value))

    return rc


# ----- #52 MQTT topic tree ----------------------------------------------------


@dataclass
class MqttTopicNode:
    """One node in the MQTT topic tree."""

    name: str
    children: dict[str, MqttTopicNode] = field(default_factory=dict)
    entities: list[str] = field(default_factory=list)


@dataclass
class MqttTopicTree:
    """Hierarchical view of MQTT topics, entity_ids attached at leaves."""

    root: MqttTopicNode = field(default_factory=lambda: MqttTopicNode(name=""))
    total_entities: int = 0


def _build_mqtt_topic_tree(snapshot: HASnapshot) -> MqttTopicTree | None:
    """Group every entity that carries an mqtt_topic into a topic-prefix tree."""
    tree = MqttTopicTree()
    count = 0
    seen: list[EntitySnapshot] = []
    for area in snapshot.areas:
        for d in area.devices:
            seen.extend(d.entities)
    for d in snapshot.unassigned_devices:
        seen.extend(d.entities)

    for entity in seen:
        topic = entity.mqtt_topic
        if not topic:
            continue
        count += 1
        node = tree.root
        for seg in topic.strip("/").split("/"):
            if seg not in node.children:
                node.children[seg] = MqttTopicNode(name=seg)
            node = node.children[seg]
        node.entities.append(entity.entity_id)

    if count == 0:
        return None
    tree.total_entities = count
    return tree


# ----- #46 Energy -------------------------------------------------------------


@dataclass
class EnergySource:
    """One entry in the Energy-Dashboard config."""

    type: str
    label: str
    consumption_entity: str | None = None
    production_entity: str | None = None
    cost_entity: str | None = None


@dataclass
class EnergyConfig:
    """Energy-Dashboard configuration extracted from .storage/energy."""

    sources: list[EnergySource] = field(default_factory=list)
    individual_devices: list[str] = field(default_factory=list)


def _extract_energy_config(hass: HomeAssistant) -> EnergyConfig | None:
    """Read .storage/energy directly. Returns None when no Energy dashboard."""
    from pathlib import Path  # noqa: PLC0415 - one-shot use

    storage_path = Path(hass.config.path(".storage", "energy"))
    if not storage_path.is_file():
        return None
    try:
        import json  # noqa: PLC0415 - one-shot use

        with storage_path.open(encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError) as err:
        LOGGER.debug("Could not read .storage/energy: %s", err)
        return None

    data = (payload.get("data") if isinstance(payload, dict) else None) or {}
    cfg = EnergyConfig()

    for entry in data.get("energy_sources", []) or []:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("type", "unknown"))
        label_field = entry.get("name") or entry.get("stat_consumption") or kind
        cfg.sources.append(
            EnergySource(
                type=kind,
                label=str(label_field),
                consumption_entity=entry.get("stat_consumption")
                or entry.get("stat_energy_from"),
                production_entity=entry.get("stat_energy_to")
                or entry.get("stat_production"),
                cost_entity=entry.get("entity_energy_price") or entry.get("stat_cost"),
            ),
        )

    for entry in data.get("device_consumption", []) or []:
        if isinstance(entry, dict) and entry.get("stat_consumption"):
            cfg.individual_devices.append(str(entry["stat_consumption"]))

    if not cfg.sources and not cfg.individual_devices:
        return None
    return cfg


# ----- #42 Helpers ------------------------------------------------------------


_HELPER_DOMAINS = (
    "input_boolean",
    "input_number",
    "input_select",
    "input_text",
    "input_datetime",
    "input_button",
    "timer",
    "counter",
    "schedule",
    "todo",
    "template",
    "group",
)


@dataclass
class HelperEntry:
    """One HA helper entity with its current state + key attributes."""

    entity_id: str
    name: str
    domain: str
    state: str | None
    attributes: dict


@dataclass
class HelperGroup:
    """All helpers of one domain."""

    domain: str
    entries: list[HelperEntry] = field(default_factory=list)


def _extract_helpers(
    hass: HomeAssistant,
    entity_reg: er.EntityRegistry,
) -> list[HelperGroup]:
    """Walk entity registry for all helper-domain entities."""
    by_domain: dict[str, list[HelperEntry]] = {d: [] for d in _HELPER_DOMAINS}
    for entry in entity_reg.entities.values():
        domain = entry.entity_id.split(".", 1)[0]
        if domain not in by_domain:
            continue
        state_obj = hass.states.get(entry.entity_id)
        attrs = state_obj.attributes if state_obj else {}
        name = (
            entry.name
            or entry.original_name
            or attrs.get("friendly_name")
            or entry.entity_id
        )
        by_domain[domain].append(
            HelperEntry(
                entity_id=entry.entity_id,
                name=name,
                domain=domain,
                state=state_obj.state if state_obj else None,
                attributes=dict(attrs),
            ),
        )

    for state in hass.states.async_all():
        domain = state.entity_id.split(".", 1)[0]
        if domain not in by_domain:
            continue
        if any(h.entity_id == state.entity_id for h in by_domain[domain]):
            continue
        attrs = state.attributes
        by_domain[domain].append(
            HelperEntry(
                entity_id=state.entity_id,
                name=attrs.get("friendly_name") or state.entity_id,
                domain=domain,
                state=state.state,
                attributes=dict(attrs),
            ),
        )

    groups: list[HelperGroup] = []
    for domain in _HELPER_DOMAINS:
        entries = by_domain[domain]
        if not entries:
            continue
        entries.sort(key=lambda e: (e.name.lower(), e.entity_id))
        groups.append(HelperGroup(domain=domain, entries=entries))
    return groups


# Temporary file — content will be appended to extractor.py and deleted.


# ----- #43 Reverse-usage ------------------------------------------------------


@dataclass
class ReverseUsageEntry:
    """One automation / script / scene that references an entity."""

    domain: str  # "automation" / "script" / "scene"
    name: str  # the alias / friendly_name
    via_group: str | None = (
        None  # group.* entity_id when reference came through a group
    )


# Pattern for an HA entity_id: `<domain>.<object_id>`. Domain is one or
# more lowercase letters / underscores; object_id is letters / digits /
# underscores. Excludes module-style paths like ``homeassistant.start``
# (event names) by checking domain length and structure later.
_ENTITY_ID_RE = re.compile(r"\b([a-z][a-z_]{1,30}\.[a-z0-9_]+)\b")
_ENTITY_ID_MAX_LEN = 100


# Tags HA users put in YAML configs that PyYAML doesn't natively know.
# We accept them and convert to a stub so the rest of the parsing works.
_HA_YAML_TAGS = (
    "!secret",
    "!include",
    "!include_dir_named",
    "!include_dir_merge_named",
    "!include_dir_list",
    "!include_dir_merge_list",
    "!env_var",
    "!input",
)


def _build_ha_yaml_loader() -> type:
    """
    Build a PyYAML SafeLoader that tolerates HA-specific tags.

    The loader returns ``None`` for any tag it doesn't understand, so the
    surrounding YAML structure parses successfully even when an entry uses
    ``!secret`` or ``!include``.
    """
    import yaml as _yaml  # noqa: PLC0415 - HA bundles PyYAML; lazy import keeps top clean

    class HALoader(_yaml.SafeLoader):
        pass

    def _stub_constructor(loader, node) -> None:  # noqa: ANN001, ARG001
        return None

    for tag in _HA_YAML_TAGS:
        HALoader.add_constructor(tag, _stub_constructor)
    HALoader.add_multi_constructor(
        "!",
        lambda loader, suffix, node: None,  # noqa: ARG005
    )
    return HALoader


def _extract_entity_ids_from_text(text: str) -> set[str]:
    """Find anything that looks like a valid HA entity_id in ``text``."""
    ids: set[str] = set()
    for match in _ENTITY_ID_RE.findall(text):
        # Heuristic filters: discard tokens with very long object-IDs that
        # are clearly URLs / paths / hashes ("github.io" → "github.io" pass,
        # but URLs usually have many dots — we already split on word chars).
        if len(match) > _ENTITY_ID_MAX_LEN:
            continue
        ids.add(match)
    return ids


def _read_yaml_entries(
    path: Path,
    loader_cls: type,
) -> list:
    """
    Load a YAML file and return its entries as a list of dicts.

    Files come in two shapes: a top-level list of entries, or a top-level
    dict of name → entry. Both are flattened to a single list.
    """
    import yaml as _yaml  # noqa: PLC0415 - HA bundles PyYAML

    try:
        with path.open(encoding="utf-8") as f:
            data = _yaml.load(f, Loader=loader_cls)  # noqa: S506 - HA-trusted file
    except (OSError, _yaml.YAMLError) as err:
        LOGGER.debug("Could not parse YAML %s: %s", path, err)
        return []

    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return [item for item in data.values() if isinstance(item, dict)]
    return []


def _entry_label(item: dict, domain: str) -> str:
    """Pick the most human-readable name from an automation/script/scene entry."""
    return str(
        item.get("alias")
        or item.get("name")
        or item.get("friendly_name")
        or item.get("id")
        or domain,
    )


def _build_group_map(hass: HomeAssistant) -> dict[str, list[str]]:
    """
    Build group_entity_id → [member_entity_id, ...] for every group HA knows.

    Covers all HA "group" flavours that expose their members via the
    ``entity_id`` state attribute:

    - Classic ``group.*`` from the legacy group integration
    - ``light.*`` / ``switch.*`` / ``cover.*`` / ``media_player.*`` /
      ``fan.*`` / ``binary_sensor.*`` / ``sensor.*`` / ``lock.*`` /
      ``climate.*`` / ``button.*`` configured with ``platform: group``
    - UI-created helper-groups (which surface as one of the above)

    A state qualifies as a group iff its ``entity_id`` attribute is a
    non-empty iterable of strings shaped like entity_ids. Transitive
    membership (group-in-group) is left to the resolver, not flattened
    here, so the same map can answer both "direct members" and "all
    leaves" queries.
    """
    group_map: dict[str, list[str]] = {}
    for state in hass.states.async_all():
        members = state.attributes.get("entity_id")
        if not members or not isinstance(members, list | tuple | set):
            continue
        clean = [
            str(member)
            for member in members
            if isinstance(member, str) and "." in member
        ]
        if clean:
            group_map[state.entity_id] = clean
    return group_map


def _resolve_group_members(
    group_id: str,
    group_map: dict[str, list[str]],
    _seen: set[str] | None = None,
) -> set[str]:
    """
    Resolve a group recursively to the set of leaf (non-group) members.

    Cycle-safe: ``_seen`` tracks visited group_ids so a group that
    contains itself (or any cycle through nested groups) terminates
    rather than recursing forever.
    """
    seen = _seen if _seen is not None else set()
    if group_id in seen:
        return set()
    seen = seen | {group_id}

    leaves: set[str] = set()
    for member in group_map.get(group_id, ()):
        if member in group_map:
            leaves |= _resolve_group_members(member, group_map, seen)
        else:
            leaves.add(member)
    return leaves


def _extract_reverse_usage(hass: HomeAssistant) -> dict[str, list[ReverseUsageEntry]]:
    """
    Build entity_id → list of automations/scripts/scenes that reference it.

    Reads ``automations.yaml`` / ``scripts.yaml`` / ``scenes.yaml`` from
    the HA config dir (sync, no async needed). Each file may use HA's
    custom YAML tags (``!secret`` / ``!include``); the loader tolerates
    them. False positives (e.g. ``automation.morning`` matching as an
    entity_id token in another automation's body) are filtered out at
    render time by matching against the snapshot's actual entity set.

    Group-aware (v0.14.0): if a YAML entry references a group, the
    automation also gets credited to every leaf member of that group,
    tagged with ``via_group=<group_entity_id>`` so the device-page
    "Verwendet in" section can label the indirect link as
    *„über Gruppe ``group.foo``"*. The outer-most group the user
    actually wrote in the YAML is kept; intermediate groups in a
    nested chain are flattened away as implementation detail.
    """
    usage: dict[str, list[ReverseUsageEntry]] = {}
    loader_cls = _build_ha_yaml_loader()
    group_map = _build_group_map(hass)

    for fname, domain in (
        ("automations.yaml", "automation"),
        ("scripts.yaml", "script"),
        ("scenes.yaml", "scene"),
    ):
        path = Path(hass.config.path(fname))
        if not path.is_file():
            continue
        for entry in _read_yaml_entries(path, loader_cls):
            label = _entry_label(entry, domain)
            text = repr(entry)
            referenced = _extract_entity_ids_from_text(text)
            for entity_id in referenced:
                usage.setdefault(entity_id, []).append(
                    ReverseUsageEntry(domain=domain, name=label),
                )
                # Group-expansion: if this reference is a group, also
                # credit every leaf member with a ``via_group`` tag.
                if entity_id in group_map:
                    for leaf in _resolve_group_members(entity_id, group_map):
                        usage.setdefault(leaf, []).append(
                            ReverseUsageEntry(
                                domain=domain,
                                name=label,
                                via_group=entity_id,
                            ),
                        )

    # Deduplicate within each entity bucket (a single automation might
    # reach the same leaf through multiple groups; we keep the FIRST
    # via_group hit, dropping later duplicates).
    for entity_id, entries in usage.items():
        seen: set[tuple[str, str, str | None]] = set()
        deduped: list[ReverseUsageEntry] = []
        for entry in entries:
            key = (entry.domain, entry.name, entry.via_group)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(entry)
        # Stable ordering for byte-identical sync output. Direct hits
        # (via_group=None) sort before group-mediated hits.
        deduped.sort(
            key=lambda e: (e.domain, e.name.lower(), e.via_group or ""),
        )
        usage[entity_id] = deduped
    return usage
