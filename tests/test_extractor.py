"""Tests for the HA-registry extractor.

Uses pytest-homeassistant-custom-component's hass fixture to drive a
real (in-memory) HA core. We populate the area / device / entity
registries plus a few fake states and assert that ``extract_snapshot``
produces the expected sorted, filtered structure.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.helpers import (
    area_registry as ar,
)
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers import (
    label_registry as lr,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bookstack_sync.extractor import (
    _classify_unifi_role,
    _compute_device_groups,
    _extract_bluetooth_network,
    _parse_energy_payload,
    async_extract_addons,
    async_extract_backup_status,
    async_extract_energy_config,
    extract_snapshot,
)

if TYPE_CHECKING:
    import pytest
    from homeassistant.core import HomeAssistant


async def _seed_minimal_registry(hass: HomeAssistant) -> None:
    """Two areas, two devices each, a handful of entities + automation/script/scene."""
    # Devices in HA's registry must reference real config entries, so create
    # placeholder entries first.
    entry1 = MockConfigEntry(domain="mqtt", entry_id="entry1", title="MQTT")
    entry2 = MockConfigEntry(domain="zha", entry_id="entry2", title="Zigbee")
    entry1.add_to_hass(hass)
    entry2.add_to_hass(hass)

    area_reg = ar.async_get(hass)
    living = area_reg.async_create("Living Room")
    kitchen = area_reg.async_create("Kitchen")

    device_reg = dr.async_get(hass)
    sofa = device_reg.async_get_or_create(
        config_entry_id="entry1",
        identifiers={("mqtt", "sofa")},
        name="Sofa Light",
        manufacturer="Philips",
        model="Hue",
        sw_version="2.1",
    )
    device_reg.async_update_device(sofa.id, area_id=living.id)

    fridge = device_reg.async_get_or_create(
        config_entry_id="entry2",
        identifiers={("zigbee", "fridge")},
        name="Fridge Door",
        manufacturer="Acme",
        model="DoorSensor",
    )
    device_reg.async_update_device(fridge.id, area_id=kitchen.id)

    entity_reg = er.async_get(hass)
    entity_reg.async_get_or_create(
        domain="light",
        platform="hue",
        unique_id="sofa_light",
        device_id=sofa.id,
        suggested_object_id="sofa_light",
    )
    hass.states.async_set("light.sofa_light", "on", {"friendly_name": "Sofa Light"})

    # State for an automation we want exported.
    hass.states.async_set(
        "automation.morning",
        "on",
        {
            "friendly_name": "Morning Routine",
            "description": "Turn on lights at sunrise",
            "mode": "single",
            "last_triggered": None,
        },
    )
    hass.states.async_set(
        "script.welcome",
        "off",
        {"friendly_name": "Welcome", "description": "Say hello"},
    )
    hass.states.async_set("scene.cinema", "scening", {"friendly_name": "Cinema"})


async def test_extract_snapshot_basic_shape(hass: HomeAssistant) -> None:
    await _seed_minimal_registry(hass)
    snap = extract_snapshot(hass)

    area_names = [a.name for a in snap.areas]
    assert "Kitchen" in area_names
    assert "Living Room" in area_names
    # Sorted alphabetically (case-insensitive)
    assert area_names == sorted(area_names, key=str.lower)

    automation_names = [a.name for a in snap.automations]
    assert "Morning Routine" in automation_names
    morning = next(a for a in snap.automations if a.name == "Morning Routine")
    assert morning.description == "Turn on lights at sunrise"
    assert morning.mode == "single"

    script_names = [s.name for s in snap.scripts]
    assert "Welcome" in script_names

    scene_names = [s.name for s in snap.scenes]
    assert "Cinema" in scene_names


async def test_mqtt_topic_extracted_from_state_attributes(
    hass: HomeAssistant,
) -> None:
    await _seed_minimal_registry(hass)
    # Override the state to include an MQTT topic
    hass.states.async_set(
        "light.sofa_light",
        "on",
        {
            "friendly_name": "Sofa Light",
            "topic": "tasmota/sofa/STATE",
        },
    )
    snap = extract_snapshot(hass)
    living = next(a for a in snap.areas if a.name == "Living Room")
    sofa = next(d for d in living.devices if d.name == "Sofa Light")
    sofa_entity = next(e for e in sofa.entities if e.entity_id == "light.sofa_light")
    assert sofa_entity.mqtt_topic == "tasmota/sofa/STATE"


async def test_extract_addons_returns_empty_without_supervisor(
    hass: HomeAssistant,
) -> None:
    # In test environment there's no Supervisor available, so add-ons
    # should be an empty list (not raise).
    snap = extract_snapshot(hass)
    assert snap.addons == []


async def test_async_extract_addons_returns_empty_without_supervisor(
    hass: HomeAssistant,
) -> None:
    """No hassio config entry in the test hass -> [] immediately, no retries."""
    addons = await async_extract_addons(hass)
    assert addons == []


async def test_async_extract_addons_retries_until_coordinator_catches_up(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    #128: an empty Supervisor cache right after startup is retried, not
    silently accepted as "this install genuinely has zero add-ons".

    ``get_addons_info`` mirrors hassio's own ``ADDONS_COORDINATOR`` cache
    not being refreshed yet - empty on the first two calls, populated on
    the third. ``async_extract_addons`` must keep retrying instead of
    giving up after the first empty read.
    """
    monkeypatch.setattr(
        "custom_components.bookstack_sync.extractor._ADDONS_REFRESH_DELAY_SECONDS",
        0,
    )
    call_count = 0

    def fake_get_addons_info(hass: HomeAssistant) -> dict[str, dict[str, object]]:
        nonlocal call_count
        call_count += 1
        if call_count < 3:  # third call is when it "catches up"
            return {}
        return {
            "core_ssh": {
                "name": "Terminal & SSH",
                "version": "9.0.0",
                "state": "started",
                "update_available": False,
            },
        }

    with (
        patch("homeassistant.helpers.hassio.is_hassio", return_value=True),
        patch(
            "homeassistant.components.hassio.get_addons_info",
            side_effect=fake_get_addons_info,
        ),
    ):
        addons = await async_extract_addons(hass)

    assert call_count == 3
    assert [a.slug for a in addons] == ["core_ssh"]


async def test_async_extract_addons_gives_up_after_max_attempts(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cache that never catches up returns [] instead of retrying forever."""
    monkeypatch.setattr(
        "custom_components.bookstack_sync.extractor._ADDONS_REFRESH_DELAY_SECONDS",
        0,
    )
    call_count = 0

    def fake_get_addons_info(hass: HomeAssistant) -> dict[str, dict[str, object]]:
        nonlocal call_count
        call_count += 1
        return {}

    with (
        patch("homeassistant.helpers.hassio.is_hassio", return_value=True),
        patch(
            "homeassistant.components.hassio.get_addons_info",
            side_effect=fake_get_addons_info,
        ),
    ):
        addons = await async_extract_addons(hass)

    assert addons == []
    assert call_count == 3


async def test_async_extract_backup_status_none_without_backup_integration(
    hass: HomeAssistant,
) -> None:
    """
    No backup component set up in the test hass -> None, not a crash (#47).

    Same "silently produce nothing" contract as ``_extract_addons`` above:
    ``async_get_manager`` raises when the ``backup`` integration isn't
    set up on this hass instance, which is the case in the plain test
    fixture (no full HA default_config bootstrap).
    """
    status = await async_extract_backup_status(hass)
    assert status is None


async def test_async_extract_backup_status_parses_manager_data(
    hass: HomeAssistant,
) -> None:
    """
    Combines the sync config tier with the async backups tier correctly (#47).

    ``manager.config.data`` (sync, no I/O) drives last_completed/attempted;
    ``manager.async_get_backups()`` (async, real I/O against every agent)
    drives the per-backup, per-agent size/target list, including a
    failed agent on one backup and an agent-level list error — both
    must be surfaced, not silently dropped (lesson from #128).
    """
    completed = datetime(2026, 8, 26, 3, 0, tzinfo=UTC)
    attempted = datetime(2026, 8, 27, 3, 0, tzinfo=UTC)

    local_agent = MagicMock()
    local_agent.name = "Local"

    backup = MagicMock()
    backup.name = "Automatic backup 2026-08-26"
    backup.date = "2026-08-26T03:00:00+00:00"
    backup.homeassistant_version = "2026.8.3"
    backup.failed_agent_ids = ["gdrive.abc123"]
    backup.agents = {"local.local": MagicMock(size=123456, protected=True)}

    manager = MagicMock()
    manager.config.data.last_completed_automatic_backup = completed
    manager.config.data.last_attempted_automatic_backup = attempted
    manager.backup_agents = {"local.local": local_agent}
    manager.async_get_backups = AsyncMock(
        return_value=(
            {"backup1": backup},
            {"gdrive.abc123": Exception("token expired")},
        ),
    )

    with patch(
        "homeassistant.components.backup.async_get_manager",
        return_value=manager,
    ):
        status = await async_extract_backup_status(hass)

    assert status is not None
    assert status.last_completed == completed.isoformat()
    assert status.last_attempted == attempted.isoformat()
    assert status.agent_errors == ["gdrive.abc123"]
    assert len(status.backups) == 1
    entry = status.backups[0]
    assert entry.name == "Automatic backup 2026-08-26"
    assert entry.ha_version == "2026.8.3"
    assert entry.failed_agent_ids == ["gdrive.abc123"]
    assert len(entry.agents) == 1
    assert entry.agents[0].agent_name == "Local"
    assert entry.agents[0].size_bytes == 123456
    assert entry.agents[0].protected is True


async def test_automation_with_area_id_routed_to_area(
    hass: HomeAssistant,
) -> None:
    """An automation entity assigned an area_id lands on that AreaSnapshot."""
    await _seed_minimal_registry(hass)
    area_reg = ar.async_get(hass)
    living = next(a for a in area_reg.areas.values() if a.name == "Living Room")

    # Create an entity_registry entry for automation.morning with area_id=living
    entity_reg = er.async_get(hass)
    entry = entity_reg.async_get_or_create(
        domain="automation",
        platform="automation",
        unique_id="morning_unique",
        suggested_object_id="morning",
    )
    entity_reg.async_update_entity(entry.entity_id, area_id=living.id)
    # The state we already seeded under automation.morning may have a
    # different entity_id (no registry entry above). Make a new one matching
    # the registry entry's entity_id.
    hass.states.async_set(
        entry.entity_id,
        "on",
        {"friendly_name": "Routine in Wohnzimmer", "mode": "single"},
    )

    snap = extract_snapshot(hass)
    living_snap = next(a for a in snap.areas if a.name == "Living Room")
    routed_names = [a.name for a in living_snap.automations]
    assert "Routine in Wohnzimmer" in routed_names

    # Bundle list still contains it (master index).
    bundle_names = [a.name for a in snap.automations]
    assert "Routine in Wohnzimmer" in bundle_names


async def test_automation_without_area_only_in_bundle(
    hass: HomeAssistant,
) -> None:
    """An automation without area_id appears only on the bundle page."""
    await _seed_minimal_registry(hass)
    snap = extract_snapshot(hass)

    # The seeded automation.morning has NO entity_registry entry (no area).
    for area in snap.areas:
        names = [a.name for a in area.automations]
        assert "Morning Routine" not in names
    # But the bundle has it.
    assert any(a.name == "Morning Routine" for a in snap.automations)


async def test_area_scene_without_device_not_duplicated_in_orphan_entities(
    hass: HomeAssistant,
) -> None:
    """
    A scene with an area_id but no device_id must not be double-listed.

    Real-world report (see Anforderungsdokument, "Esszimmer" -
    scene.ez_tag, 2026-08-25): scenes/automations/scripts without a
    device_id get their own "Szenen"/"Automatisierungen"/"Skripte"
    section on the area page (via _extract_scenes et al.), but the
    generic orphan-entity loop in extract_snapshot used to add them a
    second time under "Entities ohne Geräte-Zuordnung" since it didn't
    exclude those domains.
    """
    await _seed_minimal_registry(hass)
    area_reg = ar.async_get(hass)
    living = next(a for a in area_reg.areas.values() if a.name == "Living Room")

    entity_reg = er.async_get(hass)
    entry = entity_reg.async_get_or_create(
        domain="scene",
        platform="homeassistant",
        unique_id="ez_tag_unique",
        suggested_object_id="ez_tag",
    )
    entity_reg.async_update_entity(entry.entity_id, area_id=living.id)
    hass.states.async_set(entry.entity_id, "on", {"friendly_name": "EZ Tag"})

    snap = extract_snapshot(hass)
    living_snap = next(a for a in snap.areas if a.name == "Living Room")

    scene_names = [s.name for s in living_snap.scenes]
    assert "EZ Tag" in scene_names

    orphan_entity_ids = [e.entity_id for e in living_snap.orphan_entities]
    assert entry.entity_id not in orphan_entity_ids


async def test_label_with_device_level_label_appears_in_snapshot(
    hass: HomeAssistant,
) -> None:
    """A device labelled directly (device_registry.labels) shows up (issue #22)."""
    await _seed_minimal_registry(hass)
    label_reg = lr.async_get(hass)
    label = label_reg.async_create("kritisch", icon="mdi:alarm")

    device_reg = dr.async_get(hass)
    sofa = device_reg.async_get_device_by_identifier(("mqtt", "sofa"), "entry1")
    assert sofa is not None
    device_reg.async_update_device(sofa.id, labels={label.label_id})

    snap = extract_snapshot(hass)

    assert len(snap.labels) == 1
    kritisch = snap.labels[0]
    assert kritisch.name == "kritisch"
    assert kritisch.icon == "mdi:alarm"
    assert [d.device_id for d in kritisch.devices] == [sofa.id]


async def test_label_with_entity_level_label_appears_in_snapshot(
    hass: HomeAssistant,
) -> None:
    """A device that only has a labelled ENTITY still shows up on the label."""
    await _seed_minimal_registry(hass)
    label_reg = lr.async_get(hass)
    label = label_reg.async_create("monitoring")

    entity_reg = er.async_get(hass)
    entity_reg.async_update_entity("light.sofa_light", labels={label.label_id})

    snap = extract_snapshot(hass)

    assert len(snap.labels) == 1
    assert snap.labels[0].name == "monitoring"
    device_names = [d.name for d in snap.labels[0].devices]
    assert device_names == ["Sofa Light"]


async def test_label_with_no_devices_is_skipped_entirely(hass: HomeAssistant) -> None:
    """A label defined in HA but unused anywhere never reaches the snapshot."""
    await _seed_minimal_registry(hass)
    label_reg = lr.async_get(hass)
    label_reg.async_create("unused-label")

    snap = extract_snapshot(hass)

    assert snap.labels == []


async def test_label_with_two_devices_lists_both_sorted(hass: HomeAssistant) -> None:
    """Two devices under the same label both appear, sorted by name."""
    await _seed_minimal_registry(hass)
    label_reg = lr.async_get(hass)
    label = label_reg.async_create("urlaub_aus")

    device_reg = dr.async_get(hass)
    sofa = device_reg.async_get_device_by_identifier(("mqtt", "sofa"), "entry1")
    fridge = device_reg.async_get_device_by_identifier(("zigbee", "fridge"), "entry2")
    assert sofa is not None
    assert fridge is not None
    device_reg.async_update_device(sofa.id, labels={label.label_id})
    device_reg.async_update_device(fridge.id, labels={label.label_id})

    snap = extract_snapshot(hass)

    assert len(snap.labels) == 1
    device_names = [d.name for d in snap.labels[0].devices]
    assert device_names == sorted(device_names, key=str.lower)
    assert set(device_names) == {"Sofa Light", "Fridge Door"}


async def test_device_network_from_tracker(hass: HomeAssistant) -> None:
    """A device with a linked device_tracker gets NetworkInfo populated."""
    entry = MockConfigEntry(domain="unifi", entry_id="entry_unifi", title="UniFi")
    entry.add_to_hass(hass)
    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)

    nuc = device_reg.async_get_or_create(
        config_entry_id="entry_unifi",
        identifiers={("unifi", "nuc")},
        connections={(dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff")},
        name="NUC Server",
    )
    tracker = entity_reg.async_get_or_create(
        domain="device_tracker",
        platform="unifi",
        unique_id="nuc_tracker",
        device_id=nuc.id,
        suggested_object_id="nuc_server",
    )
    hass.states.async_set(
        tracker.entity_id,
        "home",
        {
            "ip": "192.168.1.10",
            "mac": "aa:bb:cc:dd:ee:ff",
            "host": "nuc-server",
            "switch_mac": "f0:9f:c2:11:22:33",
            "switch_port": 4,
            "network": "LAN",
            "oui": "Intel Corp",
            "last_seen": "2026-04-29T20:00:00",
        },
    )

    snap = extract_snapshot(hass)
    nuc_snap = next(d for d in snap.unassigned_devices if d.name == "NUC Server")
    assert nuc_snap.network is not None
    assert nuc_snap.network.ip == "192.168.1.10"
    assert nuc_snap.network.mac == "aa:bb:cc:dd:ee:ff"
    assert nuc_snap.network.hostname == "nuc-server"
    assert nuc_snap.network.connection_type == "wired"
    assert nuc_snap.network.vlan == "LAN"
    assert nuc_snap.network.switch_port == 4


async def test_device_network_mac_only_fallback(hass: HomeAssistant) -> None:
    """A device with only a MAC connection (no tracker) still gets MAC info."""
    entry = MockConfigEntry(domain="zha", entry_id="entry_zha", title="Zigbee")
    entry.add_to_hass(hass)
    device_reg = dr.async_get(hass)

    device_reg.async_get_or_create(
        config_entry_id="entry_zha",
        identifiers={("zigbee", "00:11:22:33:44:55")},
        connections={(dr.CONNECTION_NETWORK_MAC, "00:11:22:33:44:55")},
        name="Aqara Sensor",
    )

    snap = extract_snapshot(hass)
    sensor_snap = next(d for d in snap.unassigned_devices if d.name == "Aqara Sensor")
    assert sensor_snap.network is not None
    assert sensor_snap.network.mac == "00:11:22:33:44:55"
    assert sensor_snap.network.ip is None
    assert sensor_snap.network.source_platform == "registry"


async def test_device_with_bogus_mac_connection_gets_no_network_info(
    hass: HomeAssistant,
) -> None:
    """
    #143: a non-MAC string tagged CONNECTION_NETWORK_MAC must not count.

    Observed in the wild: an RF-sensor bridge (rtl_433-style) registers
    its own device-unique-id string (e.g. "Acurite-609TXC-0") as a
    CONNECTION_NETWORK_MAC connection instead of a real MAC. Blindly
    trusting that made a pure RF-only sensor with no network presence
    at all look like it had network data - landing it on the Network
    overview page with everything else dashed out (real devices further
    down the same table showed correct IPs, so this wasn't a general
    extraction failure, just garbage-in-garbage-out for this one
    connection value).
    """
    entry = MockConfigEntry(domain="rtl_433", entry_id="entry_rf", title="RF")
    entry.add_to_hass(hass)
    device_reg = dr.async_get(hass)

    device_reg.async_get_or_create(
        config_entry_id="entry_rf",
        identifiers={("rtl_433", "Acurite-609TXC-0")},
        connections={(dr.CONNECTION_NETWORK_MAC, "Acurite-609TXC-0")},
        name="Acurite-609TXC-0",
    )

    snap = extract_snapshot(hass)
    rf_snap = next(d for d in snap.unassigned_devices if d.name == "Acurite-609TXC-0")
    assert rf_snap.network is None


def test_compute_device_groups_unions_shared_connections_and_identifiers() -> None:
    """
    Unit test for the union-find grouping itself, isolated from the registry.

    This repo's pinned ``homeassistant==2026.5.3`` still auto-merges two
    ``async_get_or_create`` calls that share a connection into a SINGLE
    device_registry entry (the old pre-2026.8 behaviour) — so the
    "two separate entries linked by a shared MAC" scenario this feature
    targets can't be reproduced through the public registry API on this
    HA version. It's exactly the scenario HA 2026.8 introduces (see
    Anforderungsdokument 9.1: the split removes that auto-merge). This
    test exercises the grouping algorithm directly against minimal
    stand-ins for ``dr.DeviceEntry`` (only the 3 attributes
    ``_compute_device_groups`` reads), independent of which HA version
    is actually installed.
    """

    class _FakeDevice:
        def __init__(
            self,
            device_id: str,
            identifiers: set[tuple[str, str]] | None = None,
            connections: set[tuple[str, str]] | None = None,
        ) -> None:
            self.id = device_id
            self.identifiers = identifiers or set()
            self.connections = connections or set()

    class _FakeRegistry:
        def __init__(self, devices: list[_FakeDevice]) -> None:
            self.devices = {d.id: d for d in devices}

    shared_mac = ("mac", "48:55:19:17:8e:10")
    tasmota = _FakeDevice("z_tasmota", connections={shared_mac})
    unifi = _FakeDevice("a_unifi", connections={shared_mac})
    solo = _FakeDevice("solo", identifiers={("mqtt", "solo")})

    groups = _compute_device_groups(_FakeRegistry([tasmota, unifi, solo]))

    # Canonical key = lexicographically smallest member id.
    assert groups["a_unifi"] == ["a_unifi", "z_tasmota"]
    assert groups["solo"] == ["solo"]
    assert "z_tasmota" not in groups  # only reachable as a member, not a key


def test_compute_device_groups_links_tuya_and_tuya_local_by_value() -> None:
    """
    ``tuya`` and ``tuya_local`` identifiers with the same value are the same device.

    Real-world case (see Anforderungsdokument 9.1, "Elternsz" report,
    2026-08-25): Tuya's cloud integration and the community Local-Tuya
    integration each create their own device_registry entry for the
    same physical device, both keyed by the same Tuya device id — but
    under a different identifier domain (``tuya`` vs. ``tuya_local``),
    so the exact (domain, value) tuple never matches and the generic
    identifier bucketing above misses them.
    """

    class _FakeDevice:
        def __init__(
            self,
            device_id: str,
            identifiers: set[tuple[str, str]] | None = None,
            connections: set[tuple[str, str]] | None = None,
        ) -> None:
            self.id = device_id
            self.identifiers = identifiers or set()
            self.connections = connections or set()

    class _FakeRegistry:
        def __init__(self, devices: list[_FakeDevice]) -> None:
            self.devices = {d.id: d for d in devices}

    tuya_cloud = _FakeDevice("b_tuya", identifiers={("tuya", "bf4bccffb1ce921856pwjh")})
    tuya_local = _FakeDevice(
        "a_tuya_local", identifiers={("tuya_local", "bf4bccffb1ce921856pwjh")}
    )
    other_tuya_pair = _FakeDevice(
        "c_tuya", identifiers={("tuya", "different-device-id")}
    )
    unrelated_domain_same_value = _FakeDevice(
        "d_unrelated", identifiers={("mqtt", "bf4bccffb1ce921856pwjh")}
    )

    groups = _compute_device_groups(
        _FakeRegistry(
            [tuya_cloud, tuya_local, other_tuya_pair, unrelated_domain_same_value]
        )
    )

    assert groups["a_tuya_local"] == ["a_tuya_local", "b_tuya"]
    assert groups["c_tuya"] == ["c_tuya"]
    # Same value, but not a tuya/tuya_local pair -> no cross-domain match.
    assert groups["d_unrelated"] == ["d_unrelated"]


def test_compute_device_groups_handles_non_2_tuple_identifiers() -> None:
    """
    Identifiers aren't always a strict (domain, value) 2-tuple.

    Production incident (2026-08-26): rfxtrx registers 4-part
    identifiers like ``("rfxtrx", "1a", "0", "000001:1")`` for its Rfy
    (Somfy) shutter devices. The tuya-linking code unconditionally
    unpacked every identifier as exactly ``domain, value = identifier``,
    which raised ``ValueError: too many values to unpack`` for any
    identifier with more than 2 parts and broke every sync on the real
    instance. Must not crash regardless of identifier tuple length, and
    must not treat rfxtrx's extra parts as a tuya match.
    """

    class _FakeDevice:
        def __init__(
            self,
            device_id: str,
            identifiers: set[tuple[str, ...]] | None = None,
            connections: set[tuple[str, str]] | None = None,
        ) -> None:
            self.id = device_id
            self.identifiers = identifiers or set()
            self.connections = connections or set()

    class _FakeRegistry:
        def __init__(self, devices: list[_FakeDevice]) -> None:
            self.devices = {d.id: d for d in devices}

    rfy1 = _FakeDevice("a_rfy1", identifiers={("rfxtrx", "1a", "0", "000001:1")})
    rfy2 = _FakeDevice("b_rfy2", identifiers={("rfxtrx", "1a", "0", "000002:1")})

    groups = _compute_device_groups(_FakeRegistry([rfy1, rfy2]))

    assert groups["a_rfy1"] == ["a_rfy1"]
    assert groups["b_rfy2"] == ["b_rfy2"]


async def test_device_group_aggregation_unions_entities_and_network(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Two devices forced into one group get merged into a single DeviceSnapshot.

    Grouping itself is covered separately (see the unit test above) since
    the registry-level auto-merge on this HA pin prevents constructing
    two genuinely separate linked entries. Here ``_compute_device_groups``
    is monkeypatched to isolate and cover the AGGREGATION logic in
    ``extract_snapshot`` (also_known_as, entity union, network-connection
    union across group members) — the part that actually changed.
    """
    tasmota_entry = MockConfigEntry(domain="tasmota", entry_id="entry_tasmota")
    unifi_entry = MockConfigEntry(domain="unifi", entry_id="entry_unifi")
    tasmota_entry.add_to_hass(hass)
    unifi_entry.add_to_hass(hass)
    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)

    # No shared connection here — kept genuinely separate so this HA
    # version's registry doesn't auto-merge them before our code runs.
    tasmota_device = device_reg.async_get_or_create(
        config_entry_id="entry_tasmota",
        identifiers={("tasmota", "48558E10")},
        name="Waschmaschinensteckdose",
    )
    unifi_device = device_reg.async_get_or_create(
        config_entry_id="entry_unifi",
        identifiers={("unifi", "client-48558e10")},
        connections={(dr.CONNECTION_NETWORK_MAC, "48:55:19:17:8e:10")},
        name="tasmota-178E10-3600",
    )
    members = sorted([tasmota_device.id, unifi_device.id])
    monkeypatch.setattr(
        "custom_components.bookstack_sync.extractor._compute_device_groups",
        lambda device_reg: {members[0]: members},
    )

    tasmota_switch = entity_reg.async_get_or_create(
        domain="switch",
        platform="tasmota",
        unique_id="tasmota_switch",
        device_id=tasmota_device.id,
        suggested_object_id="waschmaschinensteckdose",
    )
    unifi_tracker = entity_reg.async_get_or_create(
        domain="device_tracker",
        platform="unifi",
        unique_id="unifi_tracker",
        device_id=unifi_device.id,
        suggested_object_id="tasmota_178e10_3600",
    )
    hass.states.async_set(
        unifi_tracker.entity_id,
        "home",
        {"ip": "192.168.1.42", "mac": "48:55:19:17:8e:10"},
    )

    snap = extract_snapshot(hass)
    names = {"Waschmaschinensteckdose", "tasmota-178E10-3600"}

    merged = [d for d in snap.unassigned_devices if d.name in names]
    assert len(merged) == 1, "grouped devices must fold into a single page"
    device = merged[0]
    assert device.device_id == members[0]

    # Whichever entry became canonical, the other shows up as an alias.
    assert len(device.also_known_as) == 1
    aka = device.also_known_as[0]
    assert aka.name in names
    assert aka.name != device.name
    assert aka.domain in {"tasmota", "unifi"}
    assert aka.device_id in {tasmota_device.id, unifi_device.id}
    assert aka.device_id != device.device_id

    # Entities from BOTH source integrations are unioned onto the one page.
    entity_ids = {e.entity_id for e in device.entities}
    assert tasmota_switch.entity_id in entity_ids
    assert unifi_tracker.entity_id in entity_ids

    # Network info survives even if the canonical member itself carries
    # no connection of its own (union across group members, not just
    # the primary) — the MAC only lives on the UniFi-side entry.
    assert device.network is not None
    assert device.network.mac == "48:55:19:17:8e:10"


async def test_sticky_primary_prefers_existing_active_mapping(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    A device that already has an active BookStack page must keep primary
    status when a brand-new sibling registry row joins its group —
    regardless of list/ID ordering.

    Regression: found live in production. ``_compute_device_groups``
    recomputes groups fresh every sync with no memory of past runs;
    picking "smallest device_id" blindly meant a newly-appearing sibling
    (HA 2026.8 device-registry split, or a dual Tuya cloud+local
    registration) could steal primary status from an already-documented
    device purely by sorting smaller. The old page then looked like its
    HA object had vanished (false tombstone) while a duplicate page got
    created for the same physical device — confirmed to affect the vast
    majority of "orphaned" pages on a real installation.
    """
    entry_a = MockConfigEntry(domain="tuya", entry_id="entry_a")
    entry_b = MockConfigEntry(domain="tuya_local", entry_id="entry_b")
    entry_a.add_to_hass(hass)
    entry_b.add_to_hass(hass)
    device_reg = dr.async_get(hass)

    existing_device = device_reg.async_get_or_create(
        config_entry_id="entry_a",
        identifiers={("tuya", "shared-value")},
        name="Lamp",
    )
    new_sibling = device_reg.async_get_or_create(
        config_entry_id="entry_b",
        identifiers={("tuya_local", "shared-value")},
        name="Lamp",
    )
    # Fully replace grouping (unit-tested separately) so this test only
    # exercises primary selection — new sibling listed FIRST, simulating
    # the exact "sorts first" scenario that caused the production bug.
    monkeypatch.setattr(
        "custom_components.bookstack_sync.extractor._compute_device_groups",
        lambda device_reg: {"x": [new_sibling.id, existing_device.id]},
    )

    snap = extract_snapshot(
        hass,
        known_device_pages={existing_device.id: False},  # active, not tombstoned
    )

    assert len(snap.unassigned_devices) == 1
    assert snap.unassigned_devices[0].device_id == existing_device.id
    aka_ids = {aka.device_id for aka in snap.unassigned_devices[0].also_known_as}
    assert aka_ids == {new_sibling.id}


async def test_sticky_primary_prefers_active_over_tombstoned_mapping(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    When both group members already have a page, the currently-active
    one wins over an old, already-tombstoned duplicate — no reason to
    revive stale content just because it happens to sort first.
    """
    entry_a = MockConfigEntry(domain="tuya", entry_id="entry_a")
    entry_b = MockConfigEntry(domain="tuya_local", entry_id="entry_b")
    entry_a.add_to_hass(hass)
    entry_b.add_to_hass(hass)
    device_reg = dr.async_get(hass)

    tombstoned_device = device_reg.async_get_or_create(
        config_entry_id="entry_a",
        identifiers={("tuya", "shared-value")},
        name="Lamp",
    )
    active_device = device_reg.async_get_or_create(
        config_entry_id="entry_b",
        identifiers={("tuya_local", "shared-value")},
        name="Lamp",
    )
    monkeypatch.setattr(
        "custom_components.bookstack_sync.extractor._compute_device_groups",
        lambda device_reg: {"x": [tombstoned_device.id, active_device.id]},
    )

    snap = extract_snapshot(
        hass,
        known_device_pages={
            tombstoned_device.id: True,
            active_device.id: False,
        },
    )

    assert len(snap.unassigned_devices) == 1
    assert snap.unassigned_devices[0].device_id == active_device.id


async def test_label_on_non_canonical_group_member_still_surfaces(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    A label set only on a merged-away group member must still appear.

    Combines the device-group-dedup feature with the per-label pages
    feature (issue #22): ``devices`` in ``extract_snapshot`` is keyed
    by the group's CANONICAL device_id only. If a label is set on the
    device_registry entry of a *non-canonical* member (real scenario:
    the "WCEGLED" / "WCuLED" pair, label set on the UniFi-side entry
    which is not the canonical Tasmota-side one), ``_extract_labels``
    must still find it via ``primary_to_members`` — not silently drop
    it because only the canonical id is a key in ``devices``.
    """
    tasmota_entry = MockConfigEntry(domain="tasmota", entry_id="entry_tasmota")
    unifi_entry = MockConfigEntry(domain="unifi", entry_id="entry_unifi")
    tasmota_entry.add_to_hass(hass)
    unifi_entry.add_to_hass(hass)
    device_reg = dr.async_get(hass)

    tasmota_device = device_reg.async_get_or_create(
        config_entry_id="entry_tasmota",
        identifiers={("tasmota", "WCULED")},
        name="WCuLED",
    )
    unifi_device = device_reg.async_get_or_create(
        config_entry_id="entry_unifi",
        identifiers={("unifi", "client-wcegled")},
        connections={(dr.CONNECTION_NETWORK_MAC, "98:cd:ac:1f:7d:3a")},
        name="WCEGLED",
    )
    members = sorted([tasmota_device.id, unifi_device.id])
    monkeypatch.setattr(
        "custom_components.bookstack_sync.extractor._compute_device_groups",
        lambda device_reg: {members[0]: members},
    )

    label_reg = lr.async_get(hass)
    label = label_reg.async_create("test")
    # Label whichever member is NOT canonical (device_ids are random
    # UUIDs, so which of the two sorts first isn't predictable) — the
    # whole point of this test is exercising the non-canonical path.
    non_canonical_id = members[1]
    device_reg.async_update_device(non_canonical_id, labels={label.label_id})

    snap = extract_snapshot(hass)

    assert len(snap.labels) == 1
    labelled = snap.labels[0]
    assert labelled.name == "test"
    assert len(labelled.devices) == 1
    # The merged (canonical) device shows up, regardless of which raw
    # member actually carried the label in the registry.
    assert labelled.devices[0].device_id == members[0]


async def test_linked_device_unnamed_member_ignored(hass: HomeAssistant) -> None:
    """An unnamed sibling in a linked group doesn't hide the named device.

    HA sometimes leaves nameless stub devices behind. If one happens to
    share a connection with a real, named device, the named one must
    still be documented normally — and the stub must NOT show up as an
    "also known as" alias (it's filtered the same way an unlinked
    unnamed device always was).

    Since HA 2026.8, ``DeviceEntry.name`` falls back to the owning
    config entry's title whenever no explicit name is stored — so
    ``name=None`` alone no longer produces a genuinely nameless device.
    The entry itself needs an empty title too, or "unnamed" becomes
    unreachable via the public registry API.
    """
    entry_a = MockConfigEntry(domain="tasmota", entry_id="entry_a", title="")
    entry_b = MockConfigEntry(domain="mqtt", entry_id="entry_b")
    entry_a.add_to_hass(hass)
    entry_b.add_to_hass(hass)
    device_reg = dr.async_get(hass)

    shared_mac = (dr.CONNECTION_NETWORK_MAC, "aa:11:22:33:44:55")
    device_reg.async_get_or_create(
        config_entry_id="entry_a",
        identifiers={("tasmota", "stub")},
        connections={shared_mac},
        name=None,
    )
    device_reg.async_get_or_create(
        config_entry_id="entry_b",
        identifiers={("mqtt", "named")},
        connections={shared_mac},
        name="Named Plug",
    )

    snap = extract_snapshot(hass)
    named = [d for d in snap.unassigned_devices if d.name == "Named Plug"]
    assert len(named) == 1
    assert named[0].also_known_as == ()


async def test_unlinked_devices_stay_separate(hass: HomeAssistant) -> None:
    """Two devices with no shared connection/identifier are NOT merged."""
    entry = MockConfigEntry(domain="mqtt", entry_id="entry_solo")
    entry.add_to_hass(hass)
    device_reg = dr.async_get(hass)

    device_reg.async_get_or_create(
        config_entry_id="entry_solo",
        identifiers={("mqtt", "solo_a")},
        name="Solo Device A",
    )
    device_reg.async_get_or_create(
        config_entry_id="entry_solo",
        identifiers={("mqtt", "solo_b")},
        name="Solo Device B",
    )

    snap = extract_snapshot(hass)
    solo_a = next(d for d in snap.unassigned_devices if d.name == "Solo Device A")
    solo_b = next(d for d in snap.unassigned_devices if d.name == "Solo Device B")
    assert solo_a.also_known_as == ()
    assert solo_b.also_known_as == ()


async def test_device_with_multiple_trackers_primary_first(
    hass: HomeAssistant,
) -> None:
    """Two trackers attached → primary is the most recent, others land in extra."""
    entry = MockConfigEntry(domain="unifi", entry_id="entry_unifi", title="UniFi")
    entry.add_to_hass(hass)
    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)

    nuc = device_reg.async_get_or_create(
        config_entry_id="entry_unifi",
        identifiers={("unifi", "nuc")},
        name="NUC Server",
    )
    wired_entry = entity_reg.async_get_or_create(
        domain="device_tracker",
        platform="unifi",
        unique_id="nuc_wired",
        device_id=nuc.id,
        suggested_object_id="nuc_wired",
    )
    wifi_entry = entity_reg.async_get_or_create(
        domain="device_tracker",
        platform="unifi",
        unique_id="nuc_wifi",
        device_id=nuc.id,
        suggested_object_id="nuc_wifi",
    )
    hass.states.async_set(
        wired_entry.entity_id,
        "home",
        {
            "ip": "192.168.1.10",
            "mac": "aa:bb:cc:dd:ee:ff",
            "switch_mac": "f0:9f:c2:11:22:33",
            "last_seen": "2026-04-29T19:00:00",
        },
    )
    hass.states.async_set(
        wifi_entry.entity_id,
        "home",
        {
            "ip": "192.168.5.10",
            "mac": "11:22:33:44:55:66",
            "essid": "Home",
            "last_seen": "2026-04-29T20:00:00",
        },
    )

    snap = extract_snapshot(hass)
    nuc_snap = next(d for d in snap.unassigned_devices if d.name == "NUC Server")
    # Primary = most recent (WiFi: 20:00 > 19:00)
    assert nuc_snap.network is not None
    assert nuc_snap.network.ip == "192.168.5.10"
    assert nuc_snap.network.connection_type == "wireless"
    # Extra holds the wired tracker
    assert len(nuc_snap.network_extra) == 1
    assert nuc_snap.network_extra[0].ip == "192.168.1.10"
    assert nuc_snap.network_extra[0].connection_type == "wired"


async def test_router_prefers_private_ip_over_wan(hass: HomeAssistant) -> None:
    """A device with two trackers (WAN + LAN) shows the LAN IP as primary.

    Regression for issue #37: routers / gateways have a public WAN IP
    that's frequently fresher (ISP heartbeats) and used to win the
    ``last_seen`` race. The LAN IP is always the documentation-relevant
    one even when last-seen older.
    """
    entry = MockConfigEntry(domain="unifi", entry_id="entry_unifi", title="UniFi")
    entry.add_to_hass(hass)
    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)

    gateway = device_reg.async_get_or_create(
        config_entry_id="entry_unifi",
        identifiers={("unifi", "udm")},
        name="UDM Pro",
        model="UDM-Pro",
        manufacturer="Ubiquiti",
    )
    wan_tracker = entity_reg.async_get_or_create(
        domain="device_tracker",
        platform="unifi",
        unique_id="udm_wan",
        device_id=gateway.id,
        suggested_object_id="udm_wan",
    )
    lan_tracker = entity_reg.async_get_or_create(
        domain="device_tracker",
        platform="unifi",
        unique_id="udm_lan",
        device_id=gateway.id,
        suggested_object_id="udm_lan",
    )
    # WAN tracker has a fresher last_seen — would win without the fix.
    hass.states.async_set(
        wan_tracker.entity_id,
        "home",
        {
            "ip": "85.20.30.40",
            "mac": "aa:bb:cc:dd:ee:ff",
            "last_seen": "2026-04-30T20:00:00",
        },
    )
    hass.states.async_set(
        lan_tracker.entity_id,
        "home",
        {
            "ip": "192.168.1.1",
            "mac": "11:22:33:44:55:66",
            "last_seen": "2026-04-30T19:00:00",
        },
    )

    snap = extract_snapshot(hass)
    udm = next(d for d in snap.unassigned_devices if d.name == "UDM Pro")
    # Primary must be the private LAN IP, despite older last_seen.
    assert udm.network is not None
    assert udm.network.ip == "192.168.1.1"
    # Extra contains the WAN IP.
    assert len(udm.network_extra) == 1
    assert udm.network_extra[0].ip == "85.20.30.40"


def test_classify_unifi_role_matches_real_device_model_codes() -> None:
    """
    #147: the raw model strings HA's UniFi integration actually reports.

    ``UDM-Pro``/``USW-24-PoE`` (hyphenated, human-readable) match the
    original patterns fine, but real-world "Cloud Gateway Ultra" /
    "US 24 PoE 250W" hardware comes through as the unhyphenated
    internal shortnames ``UDRULT`` / ``US24P250`` - neither matched the
    original substring list, so both silently fell into "other" and
    were dropped from the topology tree entirely (along with every
    client wired to that now-missing switch).
    """
    assert _classify_unifi_role("UDM-Pro") == "gateway"
    assert _classify_unifi_role("UDRULT") == "gateway"
    assert _classify_unifi_role("USG-3P") == "gateway"
    assert _classify_unifi_role("USW-24-PoE") == "switch"
    assert _classify_unifi_role("US24P250") == "switch"
    assert _classify_unifi_role("UAP-AC-Lite") == "ap"
    assert _classify_unifi_role("U6-Pro") == "ap"
    assert _classify_unifi_role("SomeOtherDevice") == "other"


async def test_topology_includes_gateway_switch_and_wired_client(
    hass: HomeAssistant,
) -> None:
    """
    #147: gateway + switch (unhyphenated model codes) and a wired client
    all show up in the topology tree, the client attached to the switch.
    """
    entry = MockConfigEntry(domain="unifi", entry_id="entry_unifi", title="UniFi")
    entry.add_to_hass(hass)
    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)

    gateway = device_reg.async_get_or_create(
        config_entry_id="entry_unifi",
        identifiers={("unifi", "gw")},
        connections={(dr.CONNECTION_NETWORK_MAC, "0c:ea:14:35:2c:17")},
        name="Cloud Gateway Ultra",
        model="UDRULT",
        manufacturer="Ubiquiti Networks",
    )
    switch = device_reg.async_get_or_create(
        config_entry_id="entry_unifi",
        identifiers={("unifi", "sw")},
        connections={(dr.CONNECTION_NETWORK_MAC, "74:83:c2:6d:76:f2")},
        name="US 24 PoE 250W",
        model="US24P250",
        manufacturer="Ubiquiti Networks",
        via_device_id=gateway.id,
    )
    client = device_reg.async_get_or_create(
        config_entry_id="entry_unifi",
        identifiers={("unifi", "nas")},
        name="Datenstation",
    )
    tracker = entity_reg.async_get_or_create(
        domain="device_tracker",
        platform="unifi",
        unique_id="nas_tracker",
        device_id=client.id,
        suggested_object_id="datenstation",
    )
    hass.states.async_set(
        tracker.entity_id,
        "home",
        {
            "ip": "192.168.0.11",
            "mac": "00:11:32:b4:ed:3d",
            "switch_mac": "74:83:c2:6d:76:f2",
        },
    )

    snap = extract_snapshot(hass)
    topo = snap.unifi_topology
    assert topo is not None
    assert topo.nodes[gateway.id].role == "gateway"
    assert topo.nodes[switch.id].role == "switch"
    assert switch.id in topo.nodes[gateway.id].child_device_ids
    assert topo.client_to_infra[client.id] == switch.id


async def test_topology_uses_uplink_mac_sensor_when_via_device_id_is_unset(
    hass: HomeAssistant,
) -> None:
    """
    #147 follow-up: infra hierarchy from the "Uplink MAC" diagnostic sensor.

    Live-verified against real hardware: HA's UniFi integration leaves
    ``via_device_id`` unset on infrastructure devices (both the Gateway
    and Switch reported ``via=None``) - the actual switch↔gateway /
    AP↔switch uplink is only exposed as a per-device diagnostic sensor
    (unique_id prefixed ``device_uplink_mac-``) whose state is the MAC
    of the device it's plugged into. Without reading that sensor, every
    infra device renders as its own disconnected root instead of
    nested under its real parent.
    """
    entry = MockConfigEntry(domain="unifi", entry_id="entry_unifi", title="UniFi")
    entry.add_to_hass(hass)
    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)

    gateway = device_reg.async_get_or_create(
        config_entry_id="entry_unifi",
        identifiers={("unifi", "gw")},
        connections={(dr.CONNECTION_NETWORK_MAC, "0c:ea:14:35:2c:17")},
        name="Cloud Gateway Ultra",
        model="UDRULT",
        manufacturer="Ubiquiti Networks",
    )
    # No via_device_id - matches what HA's UniFi integration actually does.
    switch = device_reg.async_get_or_create(
        config_entry_id="entry_unifi",
        identifiers={("unifi", "sw")},
        connections={(dr.CONNECTION_NETWORK_MAC, "74:83:c2:6d:76:f2")},
        name="US 24 PoE 250W",
        model="US24P250",
        manufacturer="Ubiquiti Networks",
    )
    ap = device_reg.async_get_or_create(
        config_entry_id="entry_unifi",
        identifiers={("unifi", "ap")},
        connections={(dr.CONNECTION_NETWORK_MAC, "e0:63:da:e6:7a:d8")},
        name="EG AC LR",
        model="U6-Pro",
        manufacturer="Ubiquiti Networks",
    )
    switch_uplink = entity_reg.async_get_or_create(
        domain="sensor",
        platform="unifi",
        unique_id="device_uplink_mac-switch1",
        device_id=switch.id,
        suggested_object_id="us_24_poe_250w_uplink_mac",
    )
    hass.states.async_set(switch_uplink.entity_id, "0c:ea:14:35:2c:17")
    ap_uplink = entity_reg.async_get_or_create(
        domain="sensor",
        platform="unifi",
        unique_id="device_uplink_mac-ap1",
        device_id=ap.id,
        suggested_object_id="eg_ac_lr_uplink_mac",
    )
    hass.states.async_set(ap_uplink.entity_id, "74:83:c2:6d:76:f2")

    snap = extract_snapshot(hass)
    topo = snap.unifi_topology
    assert topo is not None
    assert topo.root_device_ids == [gateway.id]
    assert switch.id in topo.nodes[gateway.id].child_device_ids
    assert ap.id in topo.nodes[switch.id].child_device_ids


async def test_bluetooth_proxy_radio_not_tracked_but_listed_as_proxy(
    hass: HomeAssistant,
) -> None:
    """
    #155: a BT-proxy's own radio device must not appear as a tracked device.
    #162: but its host must still show up in ``proxies``.

    Live-verified real-world shape: an ESPHome node ("esp-btgw-badeg",
    WiFi MAC, no Bluetooth connection at all) hosts a *separate* HA
    device for its Bluetooth radio (own BT MAC, ``via_device_id``
    pointing back to the ESPHome node) - that's HA's scanner-to-host
    link, wired up by ``homeassistant.components.bluetooth``/
    ``esphome``, never a "this proxy heard this peripheral" link (no
    real peripheral ever carries ``via_device_id``, checked live).
    Before the #155 fix, the radio device was treated as a tracked
    device itself, duplicating the ESPHome node's own name under itself
    with nothing to distinguish it from real peripherals. Excluding it
    entirely then made every BT proxy vanish from the page with no way
    to tell which proxies even exist (live feedback: "es fehlen nun
    alle ble proxies") - #162 resolves the artifact's ``via_device_id``
    back to its host and lists that identity separately.
    """
    entry = MockConfigEntry(domain="esphome", entry_id="entry_esphome", title="ESPHome")
    entry.add_to_hass(hass)
    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)

    esphome_node = device_reg.async_get_or_create(
        config_entry_id="entry_esphome",
        identifiers={("esphome", "esp-btgw-badeg")},
        connections={(dr.CONNECTION_NETWORK_MAC, "90:15:06:db:33:d0")},
        name="esp-btgw-badeg",
    )
    device_reg.async_get_or_create(
        config_entry_id="entry_esphome",
        identifiers={("bluetooth", "90:15:06:db:33:d2")},
        connections={(dr.CONNECTION_BLUETOOTH, "90:15:06:db:33:d2")},
        name="esp-btgw-badeg",
        via_device_id=esphome_node.id,
    )
    plant_sensor = device_reg.async_get_or_create(
        config_entry_id="entry_esphome",
        identifiers={("bluetooth", "5c:85:7e:b0:d6:cb")},
        connections={(dr.CONNECTION_BLUETOOTH, "5c:85:7e:b0:d6:cb")},
        name="LeosPflanzensenor",
    )
    sensor_entry = entity_reg.async_get_or_create(
        domain="sensor",
        platform="xiaomi_ble",
        unique_id="leos_battery",
        device_id=plant_sensor.id,
        suggested_object_id="leos_battery",
    )
    hass.states.async_set(sensor_entry.entity_id, "87", {})

    network = _extract_bluetooth_network(hass, device_reg, entity_reg)

    assert network is not None
    assert [d.name for d in network.devices] == ["LeosPflanzensenor"]
    assert network.devices[0].is_available is True
    assert [p.name for p in network.proxies] == ["esp-btgw-badeg"]
    assert network.proxies[0].device_id == esphome_node.id


async def test_bluetooth_device_availability_and_last_seen(
    hass: HomeAssistant,
) -> None:
    """
    #160: devices carry a per-device availability flag + last-seen timestamp.

    A first design (#158) split devices into "seen"/"not found" by
    current availability - but "unavailable right now" is the normal
    state for a passive BLE sensor for a while after any HA restart,
    not a reliable "this device is gone" signal on its own. Verified
    live: a routine restart made every tracked device look missing.
    Replaced with a flat, most-recent-first list carrying both an
    availability flag and a `last_reported`-derived timestamp, so the
    reader judges rather than the page asserting "gone".
    """
    entry = MockConfigEntry(domain="esphome", entry_id="entry_esphome", title="ESPHome")
    entry.add_to_hass(hass)
    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)

    reachable = device_reg.async_get_or_create(
        config_entry_id="entry_esphome",
        identifiers={("bluetooth", "5c:85:7e:b0:d6:cb")},
        connections={(dr.CONNECTION_BLUETOOTH, "5c:85:7e:b0:d6:cb")},
        name="LeosPflanzensenor",
    )
    reachable_sensor = entity_reg.async_get_or_create(
        domain="sensor",
        platform="xiaomi_ble",
        unique_id="leos_battery",
        device_id=reachable.id,
        suggested_object_id="leos_battery",
    )
    hass.states.async_set(reachable_sensor.entity_id, "87", {})

    missing = device_reg.async_get_or_create(
        config_entry_id="entry_esphome",
        identifiers={("bluetooth", "aa:bb:cc:dd:ee:ff")},
        connections={(dr.CONNECTION_BLUETOOTH, "aa:bb:cc:dd:ee:ff")},
        name="XiaomiFuehlerKeller",
    )
    missing_sensor = entity_reg.async_get_or_create(
        domain="sensor",
        platform="xiaomi_ble",
        unique_id="keller_battery",
        device_id=missing.id,
        suggested_object_id="keller_battery",
    )
    hass.states.async_set(missing_sensor.entity_id, "unavailable", {})

    network = _extract_bluetooth_network(hass, device_reg, entity_reg)

    assert network is not None
    by_name = {d.name: d for d in network.devices}
    assert by_name["LeosPflanzensenor"].is_available is True
    assert by_name["XiaomiFuehlerKeller"].is_available is False
    # Most recently active first, regardless of current availability -
    # "XiaomiFuehlerKeller"'s state was written last, so it sorts first
    # even though it's currently unavailable.
    assert [d.name for d in network.devices] == [
        "XiaomiFuehlerKeller",
        "LeosPflanzensenor",
    ]
    assert all(d.last_seen is not None for d in network.devices)


async def test_disabled_automation_still_extracted(hass: HomeAssistant) -> None:
    """Regression for #39: an automation with no state object still appears.

    Previously the extractor used hass.states.async_all('automation') which
    returns 0 results when entities exist in the registry but their states
    aren't yet hydrated (early-startup race) or when the user has disabled
    automations. The fix walks the entity registry instead.
    """
    entity_reg = er.async_get(hass)
    entry = entity_reg.async_get_or_create(
        domain="automation",
        platform="automation",
        unique_id="never_started",
        suggested_object_id="never_started",
    )
    # Crucially: do NOT set hass.states for this entity. It exists only
    # in the registry (e.g. disabled, or hydration not yet done).

    snap = extract_snapshot(hass)
    names = [a.name for a in snap.automations]
    assert entry.entity_id in names or any(
        a.entity_id == entry.entity_id for a in snap.automations
    )
    found = next(a for a in snap.automations if a.entity_id == entry.entity_id)
    assert found.state == "disabled"


async def test_reverse_usage_from_automations_yaml(
    hass: HomeAssistant,
) -> None:
    """An automations.yaml referencing an entity populates reverse_usage."""
    from pathlib import Path  # noqa: PLC0415 - test-only

    # Use HA's canonical path API so we hit exactly the file the
    # extractor reads (hass.config.path joins to hass.config.config_dir).
    target = Path(hass.config.path("automations.yaml"))
    target.write_text(  # noqa: ASYNC240 - test setup, sync write is fine
        "- alias: Morning Lights\n"
        "  trigger:\n"
        "    - platform: time\n"
        "      at: '07:00'\n"
        "  action:\n"
        "    - service: light.turn_on\n"
        "      target:\n"
        "        entity_id: light.foo\n",
        encoding="utf-8",
    )

    snap = extract_snapshot(hass)
    assert "light.foo" in snap.reverse_usage, (
        f"reverse_usage was {snap.reverse_usage!r}"
    )
    refs = snap.reverse_usage["light.foo"]
    assert any(e.domain == "automation" and e.name == "Morning Lights" for e in refs)


async def test_reverse_usage_resolves_through_groups(
    hass: HomeAssistant,
) -> None:
    """v0.14.0: an automation referencing a group also credits each member.

    Setup: ``group.lights`` contains [``light.bedroom``, ``light.kitchen``].
    Automation triggers on ``group.lights``. Expected reverse_usage:

    * ``group.lights`` → direct entry, ``via_group=None``
    * ``light.bedroom`` → entry tagged ``via_group="group.lights"``
    * ``light.kitchen`` → entry tagged ``via_group="group.lights"``
    """
    from pathlib import Path  # noqa: PLC0415 - test-only

    # Stage the group as a state with the canonical entity_id attribute.
    hass.states.async_set(
        "group.lights",
        "on",
        {"entity_id": ["light.bedroom", "light.kitchen"]},
    )
    Path(hass.config.path("automations.yaml")).write_text(  # noqa: ASYNC240 - test setup
        "- alias: Evening On\n"
        "  trigger: []\n"
        "  action:\n"
        "    - service: light.turn_on\n"
        "      target:\n"
        "        entity_id: group.lights\n",
        encoding="utf-8",
    )

    snap = extract_snapshot(hass)

    # Direct hit on the group itself.
    direct = snap.reverse_usage.get("group.lights", [])
    assert any(
        e.domain == "automation" and e.name == "Evening On" and e.via_group is None
        for e in direct
    ), f"direct group reference missing: {direct!r}"

    # Each leaf member is credited with via_group set.
    for leaf in ("light.bedroom", "light.kitchen"):
        leaf_refs = snap.reverse_usage.get(leaf, [])
        assert any(
            e.domain == "automation"
            and e.name == "Evening On"
            and e.via_group == "group.lights"
            for e in leaf_refs
        ), f"{leaf} missing via_group reference: {leaf_refs!r}"


async def test_reverse_usage_resolves_groups_transitively(
    hass: HomeAssistant,
) -> None:
    """v0.14.0: nested groups resolve to their leaves.

    ``group.outer`` contains ``group.inner`` contains ``light.deep``.
    An automation referencing ``group.outer`` should credit ``light.deep``
    with ``via_group="group.outer"`` — the user wrote ``group.outer``,
    so that's what they see, not the implementation-detail inner group.
    """
    from pathlib import Path  # noqa: PLC0415 - test-only

    hass.states.async_set(
        "group.outer",
        "on",
        {"entity_id": ["group.inner"]},
    )
    hass.states.async_set(
        "group.inner",
        "on",
        {"entity_id": ["light.deep"]},
    )
    Path(hass.config.path("automations.yaml")).write_text(  # noqa: ASYNC240
        "- alias: Outer\n"
        "  trigger: []\n"
        "  action:\n"
        "    - service: light.turn_on\n"
        "      target:\n"
        "        entity_id: group.outer\n",
        encoding="utf-8",
    )

    snap = extract_snapshot(hass)
    leaf_refs = snap.reverse_usage.get("light.deep", [])
    assert any(
        e.domain == "automation" and e.name == "Outer" and e.via_group == "group.outer"
        for e in leaf_refs
    ), f"transitive resolution failed: {leaf_refs!r}"


def test_package_modules_all_parse() -> None:
    """
    Regression guard: every Python file in the package must parse cleanly.

    The Python-2-syntax ``except TypeError, ValueError`` bug in
    sync.py:_needs_move kept regressing during rebases (fixed in v0.5.1,
    v0.8.0, v0.8.2, v0.9.0). v0.13.0 refactored ``_needs_move`` to drop
    the multi-except entirely — early-return when ``raw is None``, single
    ``except`` otherwise — so the historical foot-gun is gone. This test
    stays as a guard against future ``except A, B:`` slips that are valid
    on Python 3.14 (HA-required) but break on 3.13 / older toolchains.
    """
    import ast  # noqa: PLC0415 - test-only
    from pathlib import Path  # noqa: PLC0415 - test-only

    pkg = Path(__file__).parent.parent / "custom_components" / "bookstack_sync"
    for py_file in pkg.rglob("*.py"):
        with py_file.open(encoding="utf-8") as f:
            ast.parse(f.read(), filename=str(py_file))


async def test_async_extract_energy_config_uses_executor(
    hass: HomeAssistant,
    tmp_path,
) -> None:
    """
    v0.14.10: Energy-Dashboard config is read via async_add_executor_job
    so HA's blocking-I/O loop guard (since 2025) doesn't warn on every
    sync. Reads an actual file off-thread and parses it.
    """
    import json  # noqa: PLC0415 - test-only

    storage_dir = tmp_path / ".storage"
    storage_dir.mkdir()
    (storage_dir / "energy").write_text(
        json.dumps(
            {
                "data": {
                    "energy_sources": [
                        {
                            "type": "grid",
                            "stat_consumption": "sensor.grid_in",
                            "stat_energy_to": "sensor.grid_out",
                        },
                    ],
                    "device_consumption": [
                        {"stat_consumption": "sensor.fridge_kwh"},
                    ],
                },
            },
        ),
        encoding="utf-8",
    )
    hass.config.config_dir = str(tmp_path)

    cfg = await async_extract_energy_config(hass)
    assert cfg is not None
    assert any(s.type == "grid" for s in cfg.sources)
    assert "sensor.fridge_kwh" in cfg.individual_devices


async def test_async_extract_energy_config_returns_none_when_missing(
    hass: HomeAssistant,
    tmp_path,
) -> None:
    """No ``.storage/energy`` file = no energy dashboard configured."""
    hass.config.config_dir = str(tmp_path)
    cfg = await async_extract_energy_config(hass)
    assert cfg is None


def test_parse_energy_payload_pure() -> None:
    """The parser is pure (no IO) so it stays unit-testable post-split."""
    cfg = _parse_energy_payload(
        {
            "data": {
                "energy_sources": [{"type": "solar", "name": "PV"}],
                "device_consumption": [{"stat_consumption": "sensor.boiler"}],
            },
        },
    )
    assert cfg is not None
    assert cfg.sources[0].type == "solar"
    assert cfg.individual_devices == ["sensor.boiler"]

    assert _parse_energy_payload(None) is None
    assert _parse_energy_payload({}) is None
