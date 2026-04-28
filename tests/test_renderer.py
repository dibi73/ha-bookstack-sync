"""Tests for the deterministic markdown renderer.

The renderer's whole point is byte-identical output for unchanged input,
so the renderer-determinism property is the first thing we lock down.
After v0.4.0 every renderer takes a ``strings`` dict so we also assert
that output language follows that dict (DE vs EN).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

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

if TYPE_CHECKING:
    from datetime import datetime


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

    def test_square_brackets_escaped(self) -> None:
        # Defence-in-depth against link-label breakout: a device named
        # ``Lampe](javascript:alert(1))`` must not break out of
        # ``[label](page:N)`` and inject a clickable javascript: URL.
        assert _md_escape("Lampe](javascript:alert(1))") == (
            "Lampe\\](javascript:alert(1))"
        )
        assert _md_escape("[note]") == "\\[note\\]"

    def test_link_label_breakout_defused(self) -> None:
        # End-to-end: when a malicious name is rendered into a markdown
        # link, the close-bracket of the malicious name must arrive in
        # the output as ``\]`` (backslash-escaped) so the markdown parser
        # treats it as a literal character and does NOT close the link
        # label early. Note: the substring ``](`` is still present in the
        # raw text (``\]`` followed by ``(`` shares the two characters
        # ``](`` if you ignore the backslash) — what matters is the
        # parser sees the backslash, not a real link terminator.
        rendered = f"[{_md_escape('Lampe](javascript:alert(1))')}](page:42)"
        assert "\\]" in rendered, "close-bracket must be escaped"
        assert rendered.endswith("](page:42)")


class TestDeterminism:
    """Same input must produce byte-identical output across calls."""

    def test_overview_is_deterministic(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        snap = _empty_snapshot()
        first = render_overview_auto_block(snap, fixed_now, strings_de)
        second = render_overview_auto_block(snap, fixed_now, strings_de)
        assert first == second

    def test_area_is_deterministic(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        area = AreaSnapshot(
            area_id="living",
            name="Living Room",
            devices=[_device("d1"), _device("d2")],
            orphan_entities=[],
        )
        first = render_area_auto_block(area, fixed_now, strings_de)
        second = render_area_auto_block(area, fixed_now, strings_de)
        assert first == second

    def test_device_is_deterministic(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        device = _device(name="Tasmota Plug")
        device.entities.extend([_entity("switch.a"), _entity("sensor.b")])
        first = render_device_auto_block(device, fixed_now, strings_de)
        second = render_device_auto_block(device, fixed_now, strings_de)
        assert first == second


class TestI18n:
    """The strings dict drives the visible language; same input differs by lang."""

    def test_overview_is_german(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        out = render_overview_auto_block(_empty_snapshot(), fixed_now, strings_de)
        assert "## Statistik" in out
        assert "Räume" in out
        assert "Bereiche" in out
        assert "Statistics" not in out

    def test_overview_is_english(
        self,
        fixed_now: datetime,
        strings_en: dict[str, str],
    ) -> None:
        out = render_overview_auto_block(_empty_snapshot(), fixed_now, strings_en)
        assert "## Statistics" in out
        assert "Areas" in out
        assert "Sections" in out
        assert "Statistik" not in out

    def test_device_table_translates_field_labels(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
        strings_en: dict[str, str],
    ) -> None:
        device = _device()
        de_out = render_device_auto_block(device, fixed_now, strings_de)
        en_out = render_device_auto_block(device, fixed_now, strings_en)
        assert "Hersteller" in de_out
        assert "Manufacturer" in en_out
        assert "Manufacturer" not in de_out
        assert "Hersteller" not in en_out

    def test_addon_table_translates_yes_no(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
        strings_en: dict[str, str],
    ) -> None:
        addons = [
            AddonSnapshot(
                slug="x",
                name="X",
                version="1",
                state="started",
                update_available=True,
            ),
        ]
        de_out = render_addons_auto_block(addons, fixed_now, strings_de)
        en_out = render_addons_auto_block(addons, fixed_now, strings_en)
        assert "| Ja |" in de_out
        assert "| Yes |" in en_out

    def test_tombstone_speaks_chosen_language(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
        strings_en: dict[str, str],
    ) -> None:
        de = render_tombstone_auto_block(strings_de, fixed_now)
        en = render_tombstone_auto_block(strings_en, fixed_now)
        assert "verwaist" in de
        assert "orphaned" in en


class TestOverviewLinks:
    """Overview must use BookStack page-link syntax when ids are provided."""

    def test_area_link_rendered(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        area = AreaSnapshot(area_id="living", name="Living Room")
        snap = _empty_snapshot()
        snap.areas.append(area)
        out = render_overview_auto_block(
            snap,
            fixed_now,
            strings_de,
            page_links={"area:living": 42},
        )
        assert "[Living Room](page:42)" in out

    def test_area_falls_back_to_bold_when_no_link(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        area = AreaSnapshot(area_id="living", name="Living Room")
        snap = _empty_snapshot()
        snap.areas.append(area)
        out = render_overview_auto_block(snap, fixed_now, strings_de)
        assert "**Living Room**" in out
        assert "page:" not in out

    def test_bundle_links_rendered(
        self,
        fixed_now: datetime,
        strings_en: dict[str, str],
    ) -> None:
        snap = _empty_snapshot()
        out = render_overview_auto_block(
            snap,
            fixed_now,
            strings_en,
            page_links={
                "integrations:_": 1,
                "automations:_": 2,
                "scripts:_": 3,
                "scenes:_": 4,
                "addons:_": 5,
            },
        )
        assert "[Integrations](page:1)" in out
        assert "[Automations](page:2)" in out
        assert "[Scripts](page:3)" in out
        assert "[Scenes](page:4)" in out
        assert "[Add-ons](page:5)" in out

    def test_special_chars_in_area_name_escaped(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        area = AreaSnapshot(area_id="living", name="Wohn|zimmer <stage>")
        snap = _empty_snapshot()
        snap.areas.append(area)
        out = render_overview_auto_block(
            snap,
            fixed_now,
            strings_de,
            page_links={"area:living": 99},
        )
        assert r"Wohn\|zimmer &lt;stage&gt;" in out


class TestBundlePages:
    """The five bundle-list renderers."""

    def test_automations_with_description_rendered_as_quote(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
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
        out = render_automations_auto_block(autos, fixed_now, strings_de)
        assert "### Foo" in out
        assert "`automation.foo`" in out
        assert "> Wakes me up" in out

    def test_empty_automations_emits_placeholder(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        out = render_automations_auto_block([], fixed_now, strings_de)
        assert "Keine Automatisierungen" in out

    def test_scripts_use_md_escape_for_name(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        scripts = [
            ScriptSnapshot(
                entity_id="script.foo",
                name="Foo|Bar",
                description=None,
                state=None,
                last_triggered=None,
            ),
        ]
        out = render_scripts_auto_block(scripts, fixed_now, strings_de)
        assert r"### Foo\|Bar" in out

    def test_scenes_table_format(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        scenes = [SceneSnapshot(entity_id="scene.bedtime", name="Bedtime")]
        out = render_scenes_auto_block(scenes, fixed_now, strings_de)
        assert "**Bedtime**" in out
        assert "`scene.bedtime`" in out

    def test_integrations_table_columns_present(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
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
        out = render_integrations_auto_block(integ, fixed_now, strings_de)
        assert "`mqtt`" in out
        assert "MQTT Broker" in out
        assert "loaded" in out
        assert "12" in out
        assert "42" in out

    def test_addons_table(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        addons = [
            AddonSnapshot(
                slug="core_zwave",
                name="Z-Wave",
                version="1.2.3",
                state="started",
                update_available=True,
            ),
        ]
        out = render_addons_auto_block(addons, fixed_now, strings_de)
        assert "`core_zwave`" in out
        assert "Z-Wave" in out
        assert "1.2.3" in out
        assert "started" in out
        assert "Ja" in out

    def test_no_addons_emits_supervisor_placeholder(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        out = render_addons_auto_block([], fixed_now, strings_de)
        assert "Kein Supervisor" in out


class TestTombstone:
    """Tombstone-block has the obvious warning + date format."""

    def test_tombstone_contains_date(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        out = render_tombstone_auto_block(strings_de, fixed_now)
        assert "2026-04-28" in out

    def test_tombstone_has_warning_header(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        out = render_tombstone_auto_block(strings_de, fixed_now)
        assert "verwaist" in out


class TestEntityLinesMqttTopic:
    """MQTT topic should be surfaced when present in the entity attributes."""

    def test_mqtt_topic_rendered_when_present(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        device = _device()
        entity = _entity()
        entity.mqtt_topic = "tasmota/plug3/STATE"
        device.entities.append(entity)
        out = render_device_auto_block(device, fixed_now, strings_de)
        assert "(Topic: `tasmota/plug3/STATE`)" in out

    def test_no_topic_means_no_topic_marker(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        device = _device()
        device.entities.append(_entity())
        out = render_device_auto_block(device, fixed_now, strings_de)
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
    strings_de: dict[str, str],
) -> None:
    """Every page is timestamped + attributed - verifies _format_attribution path."""
    if render_fn is render_overview_auto_block:
        out = render_overview_auto_block(_empty_snapshot(), fixed_now, strings_de)
    elif render_fn is render_area_auto_block:
        out = render_area_auto_block(
            AreaSnapshot(area_id="x", name="X"),
            fixed_now,
            strings_de,
        )
    else:
        out = render_device_auto_block(_device(), fixed_now, strings_de)
    assert "2026-04-28 12:00 UTC" in out
