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


async def test_extract_snapshot_excluded_area_drops_devices(
    hass: HomeAssistant,
) -> None:
    await _seed_minimal_registry(hass)
    area_reg = ar.async_get(hass)
    kitchen = next(a for a in area_reg.areas.values() if a.name == "Kitchen")

    snap = extract_snapshot(hass, excluded_area_ids=[kitchen.id])

    area_names = [a.name for a in snap.areas]
    assert "Kitchen" not in area_names
    assert "Living Room" in area_names

    # The fridge device was assigned to Kitchen, so it must be filtered out.
    all_devices = [d.name for area in snap.areas for d in area.devices]
    all_devices += [d.name for d in snap.unassigned_devices]
    assert "Fridge Door" not in all_devices


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
