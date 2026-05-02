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
    NetworkInfo,
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
    render_network_auto_block,
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
        """v0.14.1: overview is link-only — assert the section headings."""
        out = render_overview_auto_block(_empty_snapshot(), fixed_now, strings_de)
        assert "## Räume" in out
        assert "## Weitere Seiten" in out
        # No statistics section anymore — overview is pure navigation.
        assert "## Statistik" not in out
        assert "## Statistics" not in out

    def test_overview_is_english(
        self,
        fixed_now: datetime,
        strings_en: dict[str, str],
    ) -> None:
        out = render_overview_auto_block(_empty_snapshot(), fixed_now, strings_en)
        assert "## Areas" in out
        assert "## Other pages" in out
        assert "## Statistics" not in out
        assert "## Statistik" not in out

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

    def test_overview_is_link_only_no_statistics(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        """v0.14.1 invariant: overview = pure navigation, no derived data.

        Specifically: no ``Statistik`` block, no per-area device counts,
        no aggregated totals. Just cross-page links to areas + bundle
        pages + (when present) unassigned devices.
        """
        snap = _empty_snapshot()
        snap.areas.append(
            AreaSnapshot(
                area_id="lr",
                name="Living Room",
                devices=[_device("d1"), _device("d2"), _device("d3")],
            ),
        )
        out = render_overview_auto_block(
            snap,
            fixed_now,
            strings_de,
            page_links={"area:lr": 42},
        )
        # Navigation links present.
        assert "{{@42}}" in out
        # No statistics anywhere.
        assert "Statistik" not in out
        assert "**3**" not in out  # the old per-area device count
        assert "Geräte" not in out.split("## Räume")[0]  # nothing before areas
        # Per-area device count gone — the bullet is the bare link only.
        for line in out.splitlines():
            if line.startswith("- {{@42}}"):
                assert line == "- {{@42}}", f"area bullet should be bare link: {line!r}"

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
        # BookStack-internal cross-link syntax — server expands {{@N}}.
        assert "{{@42}}" in out

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
        assert "{{@" not in out

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
        assert "{{@1}}" in out
        assert "{{@2}}" in out
        assert "{{@3}}" in out
        assert "{{@4}}" in out
        assert "{{@5}}" in out

    def test_no_legacy_page_link_syntax_anywhere(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        """
        Regression #55: never emit ``](page:`` anywhere in any rendered page.

        The naïve markdown link form ``[label](page:42)`` is treated by
        BookStack as a relative URL ``page:42`` and 404s on click. The
        correct format is the BookStack server-side template
        ``{{@42}}``. This test calls every ``render_*_auto_block`` we
        ship and asserts the bad pattern never appears.
        """
        # Exercise a snapshot with all the page-link entry-points populated.
        area = AreaSnapshot(area_id="living", name="Wohnzimmer")
        snap = _empty_snapshot()
        snap.areas.append(area)
        snap.unassigned_devices.append(_device(name="Some Unassigned Device"))

        outputs: list[str] = [
            render_overview_auto_block(
                snap,
                fixed_now,
                strings_de,
                page_links={
                    "integrations:_": 1,
                    "automations:_": 2,
                    "scripts:_": 3,
                    "scenes:_": 4,
                    "addons:_": 5,
                    "area:living": 99,
                    "device:dev1": 100,
                },
            ),
            render_area_auto_block(area, fixed_now, strings_de),
            render_device_auto_block(
                _device(name="Plain Device"),
                fixed_now,
                strings_de,
            ),
        ]
        for out in outputs:
            assert "](page:" not in out, (
                f"legacy [label](page:N) syntax found in output: {out[:200]!r}"
            )

    def test_special_chars_in_area_name_escaped_when_no_link(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        # When a page-link IS available, BookStack's ``{{@id}}`` expands
        # to the page title server-side — our custom label is dropped.
        # When NO page-link exists we fall back to ``**escaped_label**``
        # — and that path must still escape special chars.
        area = AreaSnapshot(area_id="living", name="Wohn|zimmer <stage>")
        snap = _empty_snapshot()
        snap.areas.append(area)
        out = render_overview_auto_block(snap, fixed_now, strings_de)  # no links
        assert r"Wohn\|zimmer &lt;stage&gt;" in out


class TestAreaPerArea:
    """Area pages list automations / scripts / scenes assigned to that area."""

    def test_automations_section_rendered_when_present(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        area = AreaSnapshot(
            area_id="living",
            name="Wohnzimmer",
            automations=[
                AutomationSnapshot(
                    entity_id="automation.morning",
                    name="Morgenroutine",
                    description=None,
                    state="on",
                    mode="single",
                    last_triggered=None,
                    area_id="living",
                ),
            ],
        )
        out = render_area_auto_block(area, fixed_now, strings_de)
        assert "## Automatisierungen in Wohnzimmer" in out
        assert "Morgenroutine" in out

    def test_scenes_section_rendered_when_present(
        self,
        fixed_now: datetime,
        strings_en: dict[str, str],
    ) -> None:
        area = AreaSnapshot(
            area_id="living",
            name="Living Room",
            scenes=[SceneSnapshot(entity_id="scene.cinema", name="Cinema")],
        )
        out = render_area_auto_block(area, fixed_now, strings_en)
        assert "## Scenes in Living Room" in out
        assert "**Cinema**" in out
        assert "`scene.cinema`" in out

    def test_empty_lists_emit_no_sections(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        area = AreaSnapshot(area_id="x", name="Empty")
        out = render_area_auto_block(area, fixed_now, strings_de)
        assert "Automatisierungen in" not in out
        assert "Skripte in" not in out
        assert "Szenen in" not in out


class TestAreaTocRemoved:
    """v0.14.0 dropped the inline TOC: area pages are short navigation hubs now."""

    def test_no_toc_on_small_area(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        """Few elements: no TOC, never had one (was below threshold)."""
        area = AreaSnapshot(
            area_id="small",
            name="Klein",
            devices=[_device("d1", name="Eine Lampe")],
            scenes=[SceneSnapshot(entity_id="scene.x", name="Scene X")],
        )
        out = render_area_auto_block(area, fixed_now, strings_de)
        assert "**Inhalt**" not in out

    def test_no_toc_on_large_area(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        """Many elements: still no TOC. v0.14.0 removed it entirely.

        The full per-device tables that used to bloat area pages are gone,
        so the page stays scrollable without an inline TOC. Cross-page
        ``{{@<id>}}`` links to the dedicated device pages do the navigation.
        """
        area = AreaSnapshot(
            area_id="big",
            name="Wohnzimmer",
            devices=[
                _device("d1", name="Lampe"),
                _device("d2", name="Stehlampe"),
                _device("d3", name="Heizung"),
            ],
            automations=[
                AutomationSnapshot(
                    entity_id="automation.morning",
                    name="Morgen",
                    description=None,
                    state="on",
                    mode=None,
                    last_triggered=None,
                ),
            ],
            scenes=[SceneSnapshot(entity_id="scene.cinema", name="Cinema")],
        )
        out = render_area_auto_block(area, fixed_now, strings_de)
        assert "**Inhalt**" not in out
        # No same-page anchor links either; navigation goes via {{@id}}
        # cross-links to the device pages.
        assert "(#gerate-in-wohnzimmer)" not in out
        assert "(#lampe)" not in out

    def test_no_toc_on_devices(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        """Device pages never had a TOC; v0.14.0 doesn't change that."""
        device = _device(name="Hub")
        device.entities.extend(
            [_entity(f"sensor.x{i}") for i in range(10)],
        )
        out = render_device_auto_block(device, fixed_now, strings_de)
        assert "**Inhalt**" not in out


class TestDeviceNetworkSection:
    """Network section on device pages (issue #26)."""

    def test_no_network_section_when_no_data(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        device = _device(name="Plain Device")
        out = render_device_auto_block(device, fixed_now, strings_de)
        assert "## Netzwerk" not in out
        assert "### Netzwerk" not in out

    def test_network_section_with_primary_only(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        device = _device(name="NUC")
        device.network = NetworkInfo(
            ip="192.168.1.10",
            mac="aa:bb:cc:dd:ee:ff",
            hostname="nuc-server",
            connection_type="wired",
            vlan="LAN",
            last_seen="2026-04-29T20:00:00",
        )
        out = render_device_auto_block(device, fixed_now, strings_de)
        assert "### Netzwerk" in out
        assert "192.168.1.10" in out
        assert "aa:bb:cc:dd:ee:ff" in out
        assert "nuc-server" in out
        assert "LAN" in out
        assert "auch:" not in out

    def test_network_section_with_extra_connections(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        device = _device(name="NUC")
        device.network = NetworkInfo(
            ip="192.168.5.10",
            mac="11:22:33:44:55:66",
            hostname="nuc-server",
            connection_type="wireless",
            ssid="Home",
        )
        device.network_extra = [
            NetworkInfo(
                ip="192.168.1.10",
                mac="aa:bb:cc:dd:ee:ff",
                hostname="nuc-server",
                connection_type="wired",
            ),
        ]
        out = render_device_auto_block(device, fixed_now, strings_de)
        # Both IPs visible, primary first, secondary in parens.
        assert "192.168.5.10 (auch: 192.168.1.10)" in out
        # Both connection types visible.
        assert "WLAN (auch: LAN)" in out


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


class TestNetworkPage:
    """Network overview page rendering (#27 + #28)."""

    def test_lean_table_when_no_unifi_data(
        self,
        fixed_now,
        strings_de: dict[str, str],
    ) -> None:
        device = _device(name="Aqara Sensor")
        device.network = NetworkInfo(
            mac="00:11:22:33:44:55",
            source_platform="registry",
        )
        out = render_network_auto_block([device], fixed_now, strings_de)
        assert "## Geräte mit Netzwerkdaten (1)" in out
        assert "AP / Switch-Port" not in out
        assert "00:11:22:33:44:55" in out

    def test_unifi_columns_when_any_device_has_unifi_data(
        self,
        fixed_now,
        strings_de: dict[str, str],
    ) -> None:
        unifi = _device(name="NUC")
        unifi.network = NetworkInfo(
            ip="192.168.1.10",
            mac="aa:bb:cc:dd:ee:ff",
            hostname="nuc-server",
            connection_type="wired",
            switch_mac="f0:9f:c2:11:22:33",
            switch_port=4,
            oui="Intel Corp",
            source_platform="unifi",
        )
        out = render_network_auto_block([unifi], fixed_now, strings_de)
        assert "AP / Switch-Port" in out
        assert "Hersteller (OUI)" in out
        assert "Intel Corp" in out
        assert "f0:9f:c2:11:22:33" in out

    def test_dhcp_export_block(
        self,
        fixed_now,
        strings_de: dict[str, str],
    ) -> None:
        d = _device(name="Lampe")
        d.network = NetworkInfo(
            mac="aa:bb:cc:dd:ee:ff",
            ip="192.168.1.42",
            hostname="lampe-eg",
        )
        out = render_network_auto_block([d], fixed_now, strings_de)
        assert "## DHCP-Reservierungen" in out
        assert "aa:bb:cc:dd:ee:ff" in out
        assert "192.168.1.42" in out
        assert "lampe-eg" in out

    def test_unknown_clients_section(
        self,
        fixed_now,
        strings_de: dict[str, str],
    ) -> None:
        unknown = [
            NetworkInfo(
                mac="12:34:56:78:9a:bc",
                ip="192.168.1.99",
                hostname="unknown-12-34",
                last_seen="2026-04-29T20:00:00",
                source_platform="unifi",
            ),
        ]
        out = render_network_auto_block(
            [],
            fixed_now,
            strings_de,
            unknown_clients=unknown,
        )
        assert "## Unbekannte Clients (1)" in out
        assert "12:34:56:78:9a:bc" in out
        assert "192.168.1.99" in out


class TestAreaPageMinimal:
    """v0.14.0: area pages are navigation hubs only — no full device data."""

    def test_device_renders_as_cross_link_with_metadata(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        """Devices appear as ``- {{@<id>}} — Manufacturer Model`` lines."""
        # _device defaults: manufacturer="Acme", model="Model X"
        device = _device("abc", name="Bewegungsmelder Gang")
        area = AreaSnapshot(area_id="hall", name="Gang", devices=[device])
        out = render_area_auto_block(
            area,
            fixed_now,
            strings_de,
            page_links={"device:abc": 142},
        )
        assert "- {{@142}} — Acme Model X" in out

    def test_device_falls_back_to_bold_name_when_no_link(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        """No page_links yet (e.g. dry-run) → bold name + meta."""
        device = _device("abc", name="Lampe")
        area = AreaSnapshot(area_id="lr", name="Wohnzimmer", devices=[device])
        out = render_area_auto_block(area, fixed_now, strings_de)
        assert "- **Lampe** — Acme Model X" in out

    def test_no_full_device_table_anymore(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        """The pre-v0.14 per-device fact table + entity list MUST NOT appear."""
        device = _device("abc", name="Lampe")
        device.entities.append(_entity("light.lampe"))
        area = AreaSnapshot(area_id="r", name="Raum", devices=[device])
        out = render_area_auto_block(area, fixed_now, strings_de)
        # No "### Lampe" sub-heading anymore (full per-device sections gone)
        assert "### Lampe" not in out
        # No "Stammdaten" facts table on the area page
        assert "Stammdaten" not in out
        # No entity bullet from the per-device entity list
        assert "light.lampe" not in out

    def test_automation_listed_by_name_only(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        """Automations are now just ``- <name>`` — no bodies, modes, triggers."""
        area = AreaSnapshot(
            area_id="r",
            name="Raum",
            automations=[
                AutomationSnapshot(
                    entity_id="automation.morgen",
                    name="Morgenlicht",
                    description="(should not appear on area page anymore)",
                    state="on",
                    mode="single",
                    last_triggered="2026-04-30T07:00",
                ),
            ],
        )
        out = render_area_auto_block(area, fixed_now, strings_de)
        assert "- Morgenlicht" in out
        # The detail fields belong on bundle pages, not on the area page.
        assert "single" not in out
        assert "(should not appear on area page anymore)" not in out
        assert "2026-04-30" not in out


class TestUsedBySectionViaGroup:
    """v0.14.0: ``Verwendet in`` annotates group-mediated references."""

    def test_via_group_annotation_rendered(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        """Group-mediated reference shows ``(über Gruppe `group.X`)`` inline."""
        from custom_components.bookstack_sync.extractor import (  # noqa: PLC0415
            ReverseUsageEntry,
        )

        device = _device("abc", name="Lampe")
        device.entities.append(_entity("light.lampe"))
        reverse_usage = {
            "light.lampe": [
                ReverseUsageEntry(
                    domain="automation",
                    name="Abends an",
                    via_group="group.alle_lichter",
                ),
            ],
        }
        out = render_device_auto_block(
            device,
            fixed_now,
            strings_de,
            reverse_usage=reverse_usage,
        )
        assert "Abends an" in out
        assert "über Gruppe `group.alle_lichter`" in out

    def test_direct_reference_suppresses_group_dupes(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        """Same automation referenced direct AND via a group: only direct shows."""
        from custom_components.bookstack_sync.extractor import (  # noqa: PLC0415
            ReverseUsageEntry,
        )

        device = _device("abc", name="Lampe")
        device.entities.append(_entity("light.lampe"))
        reverse_usage = {
            "light.lampe": [
                ReverseUsageEntry(domain="automation", name="X"),
                ReverseUsageEntry(
                    domain="automation",
                    name="X",
                    via_group="group.foo",
                ),
            ],
        }
        out = render_device_auto_block(
            device,
            fixed_now,
            strings_de,
            reverse_usage=reverse_usage,
        )
        # Bullet appears once — the bare line, no via-group annotation.
        assert out.count("- X") == 1
        assert "über Gruppe" not in out
