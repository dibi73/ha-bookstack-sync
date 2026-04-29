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


def _populate_network_info(
    device_snap: DeviceSnapshot,
    device_reg: dr.DeviceRegistry,
) -> None:
    """
    Fill ``device_snap.network`` and ``.network_extra`` from trackers + connections.

    Strategy:
    1. For every ``device_tracker.*`` entity attached to this device, build
       a ``NetworkInfo`` from its state attributes.
    2. Sort by ``last_seen`` desc — primary connection (most recent) first.
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

    infos.sort(key=lambda i: i.last_seen or "", reverse=True)

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
