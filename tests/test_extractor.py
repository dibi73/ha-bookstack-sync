"""Tests for the HA-registry extractor.

Uses pytest-homeassistant-custom-component's hass fixture to drive a
real (in-memory) HA core. We populate the area / device / entity
registries plus a few fake states and assert that ``extract_snapshot``
produces the expected sorted, filtered structure.
"""

from __future__ import annotations

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
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bookstack_sync.extractor import extract_snapshot

if TYPE_CHECKING:
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
