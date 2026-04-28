"""Tests for the deterministic markdown renderer.

The renderer's whole point is byte-identical output for unchanged input,
so the renderer-determinism property is the first thing we lock down.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from datetime import datetime

from custom_components.bookstack_sync.extractor import (
    AddonSnapshot,
    AreaSnapshot,
    AutomationSnapshot,
    DeviceSnapshot,
    EntitySnapshot,
    HASnapshot,
    IntegrationSnapshot,
    SceneSnapshot,
    ScriptSnapshot,
)
from custom_components.bookstack_sync.renderer import (
    _md_escape,
    render_addons_auto_block,
    render_area_auto_block,
    render_automations_auto_block,
    render_device_auto_block,
    render_integrations_auto_block,
    render_overview_auto_block,
    render_scenes_auto_block,
    render_scripts_auto_block,
    render_tombstone_auto_block,
)

# ---------------------------------------------------------------------------
# helpers


def _entity(entity_id: str = "sensor.x", *, name: str = "X") -> EntitySnapshot:
    return EntitySnapshot(
        entity_id=entity_id,
        name=name,
        platform="mqtt",
        device_id=None,
        area_id=None,
        state="on",
        attributes={},
        disabled=False,
    )


def _device(device_id: str = "dev1", *, name: str = "Device 1") -> DeviceSnapshot:
    return DeviceSnapshot(
        device_id=device_id,
        name=name,
        manufacturer="Acme",
        model="Model X",
        sw_version="1.0",
        hw_version="A",
        area_id=None,
        config_entries=("entry1",),
    )


def _empty_snapshot() -> HASnapshot:
    return HASnapshot(
        areas=[],
        unassigned_devices=[],
        automations=[],
        scripts=[],
        scenes=[],
        integrations=[],
        addons=[],
    )


# ---------------------------------------------------------------------------
# tests


class TestMdEscape:
    """Markdown-escape util — used to sanitize user-supplied names."""

    def test_pipe_escaped(self) -> None:
        assert _md_escape("a|b") == r"a\|b"

    def test_backslash_escaped_first(self) -> None:
        # Backslash must be escaped BEFORE pipe so we don't double-escape
        # a backslash that escaped a pipe.
        assert _md_escape("a\\b") == r"a\\b"

    def test_html_brackets_replaced(self) -> None:
        assert _md_escape("<script>") == "&lt;script&gt;"

    def test_newline_replaced_with_space(self) -> None:
        assert _md_escape("a\nb") == "a b"

    def test_empty_input(self) -> None:
        assert _md_escape("") == ""

    def test_no_special_chars_unchanged(self) -> None:
        assert _md_escape("Living Room") == "Living Room"


class TestDeterminism:
    """Same input must produce byte-identical output across calls."""

    def test_overview_is_deterministic(self, fixed_now: datetime) -> None:
        snap = _empty_snapshot()
        first = render_overview_auto_block(snap, fixed_now)
        second = render_overview_auto_block(snap, fixed_now)
        assert first == second

    def test_area_is_deterministic(self, fixed_now: datetime) -> None:
        area = AreaSnapshot(
            area_id="living",
            name="Living Room",
            devices=[_device("d1"), _device("d2")],
            orphan_entities=[],
        )
        first = render_area_auto_block(area, fixed_now)
        second = render_area_auto_block(area, fixed_now)
        assert first == second

    def test_device_is_deterministic(self, fixed_now: datetime) -> None:
        device = _device(name="Tasmota Plug")
        device.entities.extend([_entity("switch.a"), _entity("sensor.b")])
        first = render_device_auto_block(device, fixed_now)
        second = render_device_auto_block(device, fixed_now)
        assert first == second


class TestOverviewLinks:
    """Overview must use BookStack page-link syntax when ids are provided."""

    def test_area_link_rendered(self, fixed_now: datetime) -> None:
        area = AreaSnapshot(area_id="living", name="Living Room")
        snap = _empty_snapshot()
        snap.areas.append(area)
        out = render_overview_auto_block(
            snap,
            fixed_now,
            page_links={"area:living": 42},
        )
        assert "[Living Room](page:42)" in out

    def test_area_falls_back_to_bold_when_no_link(self, fixed_now: datetime) -> None:
        area = AreaSnapshot(area_id="living", name="Living Room")
        snap = _empty_snapshot()
        snap.areas.append(area)
        out = render_overview_auto_block(snap, fixed_now)
        assert "**Living Room**" in out
        assert "page:" not in out

    def test_bundle_links_rendered(self, fixed_now: datetime) -> None:
        snap = _empty_snapshot()
        out = render_overview_auto_block(
            snap,
            fixed_now,
            page_links={
                "integrations:_": 1,
                "automations:_": 2,
                "scripts:_": 3,
                "scenes:_": 4,
                "addons:_": 5,
            },
        )
        assert "[Integrationen](page:1)" in out
        assert "[Automatisierungen](page:2)" in out
        assert "[Skripte](page:3)" in out
        assert "[Szenen](page:4)" in out
        assert "[Add-ons](page:5)" in out

    def test_special_chars_in_area_name_escaped(self, fixed_now: datetime) -> None:
        # Names like "Wohn|zimmer <stage>" must not break the markdown table.
        area = AreaSnapshot(area_id="living", name="Wohn|zimmer <stage>")
        snap = _empty_snapshot()
        snap.areas.append(area)
        out = render_overview_auto_block(
            snap,
            fixed_now,
            page_links={"area:living": 99},
        )
        assert r"Wohn\|zimmer &lt;stage&gt;" in out


class TestBundlePages:
    """The five bundle-list renderers."""

    def test_automations_with_description_rendered_as_quote(
        self,
        fixed_now: datetime,
    ) -> None:
        autos = [
            AutomationSnapshot(
                entity_id="automation.foo",
                name="Foo",
                description="Wakes me up",
                state="on",
                mode="single",
                last_triggered="2026-04-28T06:00:00+00:00",
            ),
        ]
        out = render_automations_auto_block(autos, fixed_now)
        assert "### Foo" in out
        assert "`automation.foo`" in out
        assert "> Wakes me up" in out

    def test_empty_automations_emits_placeholder(self, fixed_now: datetime) -> None:
        out = render_automations_auto_block([], fixed_now)
        assert "Keine Automatisierungen" in out

    def test_scripts_use_md_escape_for_name(self, fixed_now: datetime) -> None:
        scripts = [
            ScriptSnapshot(
                entity_id="script.foo",
                name="Foo|Bar",
                description=None,
                state=None,
                last_triggered=None,
            ),
        ]
        out = render_scripts_auto_block(scripts, fixed_now)
        assert r"### Foo\|Bar" in out

    def test_scenes_table_format(self, fixed_now: datetime) -> None:
        scenes = [SceneSnapshot(entity_id="scene.bedtime", name="Bedtime")]
        out = render_scenes_auto_block(scenes, fixed_now)
        assert "**Bedtime**" in out
        assert "`scene.bedtime`" in out

    def test_integrations_table_columns_present(self, fixed_now: datetime) -> None:
        integ = [
            IntegrationSnapshot(
                entry_id="abc",
                domain="mqtt",
                title="MQTT Broker",
                state="loaded",
                source="user",
                device_count=12,
                entity_count=42,
            ),
        ]
        out = render_integrations_auto_block(integ, fixed_now)
        assert "`mqtt`" in out
        assert "MQTT Broker" in out
        assert "loaded" in out
        assert "12" in out
        assert "42" in out

    def test_addons_table(self, fixed_now: datetime) -> None:
        addons = [
            AddonSnapshot(
                slug="core_zwave",
                name="Z-Wave",
                version="1.2.3",
                state="started",
                update_available=True,
            ),
        ]
        out = render_addons_auto_block(addons, fixed_now)
        assert "`core_zwave`" in out
        assert "Z-Wave" in out
        assert "1.2.3" in out
        assert "started" in out
        assert "Ja" in out

    def test_no_addons_emits_supervisor_placeholder(self, fixed_now: datetime) -> None:
        out = render_addons_auto_block([], fixed_now)
        assert "Kein Supervisor" in out


class TestTombstone:
    """Tombstone-block has the obvious warning + date format."""

    def test_tombstone_contains_date(self, fixed_now: datetime) -> None:
        out = render_tombstone_auto_block(fixed_now)
        assert "2026-04-28" in out

    def test_tombstone_has_warning_header(self, fixed_now: datetime) -> None:
        out = render_tombstone_auto_block(fixed_now)
        assert "verwaist" in out


class TestEntityLinesMqttTopic:
    """MQTT topic should be surfaced when present in the entity attributes."""

    def test_mqtt_topic_rendered_when_present(self, fixed_now: datetime) -> None:
        device = _device()
        entity = _entity()
        entity.mqtt_topic = "tasmota/plug3/STATE"
        device.entities.append(entity)
        out = render_device_auto_block(device, fixed_now)
        assert "(Topic: `tasmota/plug3/STATE`)" in out

    def test_no_topic_means_no_topic_marker(self, fixed_now: datetime) -> None:
        device = _device()
        device.entities.append(_entity())
        out = render_device_auto_block(device, fixed_now)
        assert "Topic" not in out


@pytest.mark.parametrize(
    "render_fn",
    [
        render_overview_auto_block,
        render_area_auto_block,
        render_device_auto_block,
    ],
)
def test_all_renderers_include_attribution(
    render_fn: object,
    fixed_now: datetime,
) -> None:
    """Every page is timestamped + attributed - verifies _format_attribution path."""
    if render_fn is render_overview_auto_block:
        out = render_overview_auto_block(_empty_snapshot(), fixed_now)
    elif render_fn is render_area_auto_block:
        out = render_area_auto_block(
            AreaSnapshot(area_id="x", name="X"),
            fixed_now,
        )
    else:
        out = render_device_auto_block(_device(), fixed_now)
    assert "Stand 2026-04-28 12:00 UTC" in out
