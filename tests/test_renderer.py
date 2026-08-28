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
    AkaEntry,
    AreaSnapshot,
    AutomationSnapshot,
    BackupAgentEntry,
    BackupEntry,
    BackupStatusSnapshot,
    BluetoothDeviceHeard,
    BluetoothNetwork,
    DeviceIntegrationRef,
    DeviceSnapshot,
    EntitySnapshot,
    HASnapshot,
    HelperEntry,
    HelperGroup,
    IntegrationSnapshot,
    LabelSnapshot,
    NetworkInfo,
    SceneSnapshot,
    ScriptSnapshot,
    UnifiInfraNode,
    UnifiTopology,
)
from custom_components.bookstack_sync.renderer import (
    _format_bytes,
    _md_escape,
    render_addons_auto_block,
    render_area_auto_block,
    render_automations_auto_block,
    render_backup_auto_block,
    render_bluetooth_auto_block,
    render_device_auto_block,
    render_helpers_auto_block,
    render_integrations_auto_block,
    render_label_auto_block,
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
        config_entries=(DeviceIntegrationRef(entry_id="entry1", domain="acme"),),
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

        v0.14.4: cross-references are now plain Markdown links pointing
        at the BookStack page URL, not the ``{{@<id>}}`` template
        (which BookStack treats as include/transclusion).
        """
        url = "http://bookstack.local/books/book/page/lr"
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
            page_links={"area:lr": url},
        )
        # Navigation link present in Markdown form.
        assert f"[Living Room]({url})" in out
        # No statistics anywhere.
        assert "Statistik" not in out
        assert "**3**" not in out
        assert "Geräte" not in out.split("## Räume")[0]
        # Bare link, no per-area device count appended.
        for line in out.splitlines():
            if line.startswith(f"- [Living Room]({url})"):
                assert line == f"- [Living Room]({url})", (
                    f"area bullet should be bare link: {line!r}"
                )
        # And the deprecated transclusion syntax must not appear.
        assert "{{@" not in out

    def test_area_link_rendered_as_markdown_link(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        url = "http://bookstack.local/books/book/page/living"
        area = AreaSnapshot(area_id="living", name="Living Room")
        snap = _empty_snapshot()
        snap.areas.append(area)
        out = render_overview_auto_block(
            snap,
            fixed_now,
            strings_de,
            page_links={"area:living": url},
        )
        # v0.14.4: plain Markdown link, not {{@id}} include syntax.
        assert f"[Living Room]({url})" in out
        assert "{{@" not in out

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
        assert "](http" not in out  # no link rendered without URL in map

    def test_labels_section_links_to_label_pages(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        url = "http://bookstack.local/books/book/page/kritisch"
        snap = _empty_snapshot()
        snap.labels.append(
            LabelSnapshot(label_id="kritisch", name="kritisch", icon=None, devices=[]),
        )
        out = render_overview_auto_block(
            snap,
            fixed_now,
            strings_de,
            page_links={"label:kritisch": url},
        )
        assert f"[kritisch]({url})" in out
        assert "## Labels" in out

    def test_labels_section_omitted_when_no_labels(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        out = render_overview_auto_block(_empty_snapshot(), fixed_now, strings_de)
        assert "## Labels" not in out

    def test_bundle_links_rendered_as_markdown(
        self,
        fixed_now: datetime,
        strings_en: dict[str, str],
    ) -> None:
        snap = _empty_snapshot()
        urls = {
            "integrations:_": "http://b/books/book/page/int",
            "automations:_": "http://b/books/book/page/auto",
            "scripts:_": "http://b/books/book/page/scr",
            "scenes:_": "http://b/books/book/page/scn",
            "addons:_": "http://b/books/book/page/add",
        }
        out = render_overview_auto_block(
            snap,
            fixed_now,
            strings_en,
            page_links=urls,
        )
        for url in urls.values():
            assert f"]({url})" in out
        assert "{{@" not in out

    def test_no_legacy_or_transclusion_syntax_anywhere(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        """v0.14.4: never emit ``{{@<id>}}`` (transclusion!) or ``](page:``.

        Both are bug histories: ``[label](page:N)`` 404s (issue #55 in
        v0.10.0), ``{{@<id>}}`` causes BookStack to inline-include the
        linked page's whole content (the user-visible misbehaviour
        leading to v0.14.4). The correct form is plain Markdown
        ``[label](https://bookstack.../books/<book>/page/<slug>)``.
        """
        url_a = "http://b/books/book/page/wz"
        url_d = "http://b/books/book/page/dev1"
        url_unassigned = "http://b/books/book/page/unassigned"
        url_int = "http://b/books/book/page/int"

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
                    "integrations:_": url_int,
                    "area:living": url_a,
                    "device:dev1": url_unassigned,
                },
            ),
            render_area_auto_block(
                area,
                fixed_now,
                strings_de,
                page_links={"device:dev1": url_d},
            ),
            render_device_auto_block(
                _device(name="Plain Device"),
                fixed_now,
                strings_de,
            ),
        ]
        for out in outputs:
            assert "](page:" not in out, (
                f"legacy [label](page:N) syntax found: {out[:200]!r}"
            )
            assert "{{@" not in out, f"transclusion syntax found: {out[:200]!r}"

    def test_special_chars_in_area_name_escaped_when_no_link(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        """Fall-back path (no URL) must escape special chars in the bold label."""
        area = AreaSnapshot(area_id="living", name="Wohn|zimmer <stage>")
        snap = _empty_snapshot()
        snap.areas.append(area)
        out = render_overview_auto_block(snap, fixed_now, strings_de)
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


class TestDeviceAlsoKnownAs:
    """
    "Auch bekannt als" / "Also known as" section for merged device pages.

    See extractor._compute_device_groups / DeviceSnapshot.also_known_as —
    when a physical device is represented by several linked
    device_registry entries, the non-canonical ones are folded into this
    section instead of getting their own stub page.
    """

    def test_no_section_when_not_grouped(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        device = _device(name="Plain Device")
        out = render_device_auto_block(device, fixed_now, strings_de)
        assert "Auch bekannt als" not in out

    def test_aka_entry_links_with_ha_url(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        device = _device(name="Waschmaschinensteckdose")
        device.also_known_as = (
            AkaEntry(
                name="tasmota-178E10-3600",
                domain="unifi",
                device_id="dev-unifi-side",
            ),
        )
        out = render_device_auto_block(
            device,
            fixed_now,
            strings_de,
            ha_url="http://ha.local:8123",
        )
        assert "## Auch bekannt als" in out
        assert (
            "[tasmota-178E10-3600]"
            "(http://ha.local:8123/config/devices/device/dev-unifi-side) (unifi)"
        ) in out

    def test_aka_entry_falls_back_to_bold_without_ha_url(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        device = _device(name="Waschmaschinensteckdose")
        device.also_known_as = (
            AkaEntry(name="tasmota-178E10-3600", domain="unifi", device_id="dev-x"),
        )
        out = render_device_auto_block(device, fixed_now, strings_de)
        assert "**tasmota-178E10-3600** (unifi)" in out
        assert "](http" not in out

    def test_multiple_aka_entries_all_listed(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        device = _device(name="Datenstation")
        device.also_known_as = (
            AkaEntry(name="DatenStation", domain="synology_dsm", device_id="dev-b"),
            AkaEntry(name="Datenstation", domain="unifi", device_id="dev-c"),
        )
        out = render_device_auto_block(device, fixed_now, strings_de)
        assert "DatenStation** (synology_dsm)" in out
        assert "Datenstation** (unifi)" in out

    def test_english_label(
        self,
        fixed_now: datetime,
        strings_en: dict[str, str],
    ) -> None:
        device = _device(name="Washing machine outlet")
        device.also_known_as = (
            AkaEntry(name="tasmota-178E10-3600", domain="unifi", device_id="dev-x"),
        )
        out = render_device_auto_block(device, fixed_now, strings_en)
        assert "## Also known as" in out


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


@pytest.mark.parametrize(
    "render_fn",
    [
        render_overview_auto_block,
        render_area_auto_block,
        render_device_auto_block,
    ],
)
def test_all_renderers_start_with_auto_generated_heading(
    render_fn: object,
    fixed_now: datetime,
    strings_de: dict[str, str],
) -> None:
    """
    Every page's AUTO block opens with a visible heading (issue #129).

    The ``<!-- BEGIN AUTO-GENERATED -->`` marker itself is an invisible
    HTML comment in rendered BookStack output — a reader can't tell
    where the auto-generated part begins, or that it's auto-generated
    at all, without a visible heading. Injected centrally via
    ``_format_attribution`` (every renderer's first line), so this one
    parametrized test covering three representative page types stands
    in for all 16 call sites.
    """
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
    assert out.startswith("# Automatische Dokumentation\n")


def test_auto_generated_heading_is_localised(
    fixed_now: datetime,
    strings_en: dict[str, str],
) -> None:
    """The heading follows the active output language, not hardcoded German."""
    out = render_device_auto_block(_device(), fixed_now, strings_en)
    assert out.startswith("# Automatic Documentation\n")
    assert "Automatische Dokumentation" not in out


class TestBackupPage:
    """Backup status page rendering (#47)."""

    def test_lists_backup_with_target_and_size(
        self,
        fixed_now,
        strings_de: dict[str, str],
    ) -> None:
        status = BackupStatusSnapshot(
            last_completed="2026-08-26T03:00:00+00:00",
            last_attempted="2026-08-27T03:00:00+00:00",
            backups=[
                BackupEntry(
                    name="Automatic backup 2026-08-26",
                    date="2026-08-26T03:00:00+00:00",
                    ha_version="2026.8.3",
                    agents=[
                        BackupAgentEntry(
                            agent_name="Local",
                            size_bytes=1_288_490_188,  # ~1.2 GB
                            protected=True,
                        ),
                    ],
                ),
            ],
        )
        out = render_backup_auto_block(status, fixed_now, strings_de)
        assert "2026-08-26T03:00:00+00:00" in out  # last_completed line
        assert "Automatic backup 2026-08-26" in out
        assert "2026.8.3" in out
        assert "Local (1.2 GB)" in out

    def test_failed_agent_shown_distinctly(
        self,
        fixed_now,
        strings_de: dict[str, str],
    ) -> None:
        status = BackupStatusSnapshot(
            backups=[
                BackupEntry(
                    name="Automatic backup",
                    date="2026-08-26T03:00:00+00:00",
                    failed_agent_ids=["gdrive.abc123"],
                ),
            ],
        )
        out = render_backup_auto_block(status, fixed_now, strings_de)
        assert "gdrive.abc123 (fehlgeschlagen)" in out

    def test_agent_list_errors_surfaced_not_hidden(
        self,
        fixed_now,
        strings_de: dict[str, str],
    ) -> None:
        """
        A failed agent-list query is called out, per the #128 lesson.

        Missing/erroring data must be surfaced with a note, never make
        the whole section silently vanish.
        """
        status = BackupStatusSnapshot(agent_errors=["gdrive.abc123"])
        out = render_backup_auto_block(status, fixed_now, strings_de)
        assert "gdrive.abc123" in out
        assert "nicht abfragbar" in out

    def test_empty_state_when_no_backups(
        self,
        fixed_now,
        strings_de: dict[str, str],
    ) -> None:
        out = render_backup_auto_block(BackupStatusSnapshot(), fixed_now, strings_de)
        assert "Keine Backups gefunden" in out

    def test_localised_to_english(
        self,
        fixed_now,
        strings_en: dict[str, str],
    ) -> None:
        out = render_backup_auto_block(BackupStatusSnapshot(), fixed_now, strings_en)
        assert "No backups found" in out
        assert "Backup status" in out


class TestFormatBytes:
    """Byte-size formatting helper backing the Backup page's size column."""

    def test_bytes_stay_whole_numbers(self) -> None:
        assert _format_bytes(500) == "500 B"

    def test_kilobytes(self) -> None:
        assert _format_bytes(1536) == "1.5 KB"

    def test_gigabytes(self) -> None:
        assert _format_bytes(1_288_490_188) == "1.2 GB"


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

    def test_topology_renders_before_the_device_table(
        self,
        fixed_now,
        strings_de: dict[str, str],
    ) -> None:
        """
        #147: topology sits right after the attribution line, above the
        flat table - on a real setup the table can run to hundreds of
        rows, which buried the at-a-glance topology tree at the very
        bottom of the page.
        """
        gateway = UnifiInfraNode(
            device_id="gw",
            name="Cloud Gateway Ultra",
            model="UDRULT",
            role="gateway",
            mac="0c:ea:14:35:2c:17",
            ip=None,
            parent_device_id=None,
        )
        topology = UnifiTopology(
            nodes={"gw": gateway},
            root_device_ids=["gw"],
        )
        device = _device(name="NUC")
        device.network = NetworkInfo(mac="aa:bb:cc:dd:ee:ff", source_platform="unifi")

        out = render_network_auto_block(
            [device],
            fixed_now,
            strings_de,
            topology=topology,
            snapshot=_empty_snapshot(),
        )

        topology_pos = out.index("## Topologie")
        table_pos = out.index("## Geräte mit Netzwerkdaten")
        assert topology_pos < table_pos

    def test_nested_infra_gets_indented_tree_branches(
        self,
        fixed_now,
        strings_de: dict[str, str],
    ) -> None:
        """
        #152: Switch (child of Gateway) and AP (child of Switch) must render
        with an indented tree branch, not flush-left like the root.

        Never visible before #147/#149 fixed the underlying gateway/switch
        classification and uplink-based hierarchy - a two-level-deep infra
        chain never existed to expose this. The bug: ``child_prefix``'s
        ``if prefix else ""`` guard collapsed indentation back to "" for
        every root's children, since an empty prefix string is falsy.
        """
        gateway = UnifiInfraNode(
            device_id="gw",
            name="Cloud Gateway Ultra",
            model="UDRULT",
            role="gateway",
            mac="0c:ea:14:35:2c:17",
            ip=None,
            parent_device_id=None,
            child_device_ids=["sw"],
        )
        switch = UnifiInfraNode(
            device_id="sw",
            name="US 24 PoE 250W",
            model="US24P250",
            role="switch",
            mac="74:83:c2:6d:76:f2",
            ip=None,
            parent_device_id="gw",
            child_device_ids=["ap"],
        )
        ap = UnifiInfraNode(
            device_id="ap",
            name="EG AC LR",
            model="U6-Pro",
            role="ap",
            mac="e0:63:da:e6:7a:d8",
            ip=None,
            parent_device_id="sw",
        )
        topology = UnifiTopology(
            nodes={"gw": gateway, "sw": switch, "ap": ap},
            root_device_ids=["gw"],
        )

        out = render_network_auto_block(
            [],
            fixed_now,
            strings_de,
            topology=topology,
            snapshot=_empty_snapshot(),
        )

        lines = out.splitlines()
        gateway_line = next(li for li in lines if "Cloud Gateway Ultra" in li)
        switch_line = next(li for li in lines if "US 24 PoE 250W" in li)
        ap_line = next(li for li in lines if "EG AC LR" in li)

        assert gateway_line.startswith("Gateway:")
        assert switch_line.startswith("└── Switch:")
        assert ap_line.startswith("    └── AP:")


class TestBluetoothPage:
    """#158: Bluetooth page splits devices by current availability."""

    def test_seen_and_not_found_sections(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        network = BluetoothNetwork(
            seen=[
                BluetoothDeviceHeard(
                    name="LeosPflanzensenor", address="5c:85:7e:b0:d6:cb"
                )
            ],
            not_found=[
                BluetoothDeviceHeard(
                    name="XiaomiFuehlerKeller",
                    address="aa:bb:cc:dd:ee:ff",
                    last_seen="2026-08-20T10:00:00+00:00",
                ),
            ],
        )
        out = render_bluetooth_auto_block(network, fixed_now, strings_de)

        seen_pos = out.index("## Gesehen (1)")
        not_found_pos = out.index("## Sollte da sein, aber nicht gefunden (1)")
        assert seen_pos < not_found_pos
        assert "LeosPflanzensenor" in out
        assert "XiaomiFuehlerKeller" in out
        assert "2026-08-20T10:00:00+00:00" in out

    def test_empty_sections_show_fallback_text(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        network = BluetoothNetwork(
            seen=[],
            not_found=[
                BluetoothDeviceHeard(
                    name="XiaomiFuehlerKeller", address="aa:bb:cc:dd:ee:ff"
                ),
            ],
        )
        out = render_bluetooth_auto_block(network, fixed_now, strings_de)
        assert "Aktuell keine Geräte erreichbar" in out


class TestAreaPageMinimal:
    """v0.14.0: area pages are navigation hubs only — no full device data."""

    def test_device_renders_as_cross_link_with_metadata(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        """v0.14.4: devices appear as ``- [Name](URL) — Manufacturer Model``."""
        url = "http://bookstack.local/books/book/page/bm-gang"
        device = _device("abc", name="Bewegungsmelder Gang")
        area = AreaSnapshot(area_id="hall", name="Gang", devices=[device])
        out = render_area_auto_block(
            area,
            fixed_now,
            strings_de,
            page_links={"device:abc": url},
        )
        assert f"- [Bewegungsmelder Gang]({url}) — Acme Model X" in out
        assert "{{@" not in out

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


# ---------------------------------------------------------------------------
# v0.14.5: HA-frontend deep-links


_HA_URL = "http://homeassistant.local:8123"


class TestHaLinksDevicePage:
    """Device pages link out to the live HA UI when ``ha_url`` is set."""

    def test_device_page_has_open_in_ha_line(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        out = render_device_auto_block(
            _device("abc"),
            fixed_now,
            strings_de,
            ha_url=_HA_URL,
        )
        assert (
            f"[In Home Assistant öffnen]({_HA_URL}/config/devices/device/abc)"
        ) in out

    def test_integrations_cell_uses_domain_not_entry_id(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        device = _device()
        out = render_device_auto_block(
            device,
            fixed_now,
            strings_de,
            ha_url=_HA_URL,
        )
        # Friendly domain rendered, not the ULID-style entry_id.
        assert (f"[acme]({_HA_URL}/config/integrations/integration/acme)") in out
        assert "entry1" not in out

    def test_entity_id_becomes_dev_tools_link(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        device = _device()
        device.entities.append(_entity("sensor.foo"))
        out = render_device_auto_block(
            device,
            fixed_now,
            strings_de,
            ha_url=_HA_URL,
        )
        assert (
            f"[`sensor.foo`]({_HA_URL}/developer-tools/state?entity_id=sensor.foo)"
        ) in out

    def test_no_ha_url_means_no_link_no_dangling_label(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        device = _device()
        device.entities.append(_entity("sensor.foo"))
        out = render_device_auto_block(device, fixed_now, strings_de)
        assert "homeassistant" not in out
        assert "In Home Assistant öffnen" not in out
        # Plain code-span survives unchanged when no URL is configured.
        assert "`sensor.foo`" in out

    def test_integrations_cell_falls_back_to_plain_domain_without_ha_url(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        out = render_device_auto_block(_device(), fixed_now, strings_de)
        # Domain is still shown (the v0.14.5 bug-fix), just not as a link.
        assert "| acme |" in out
        assert "entry1" not in out


class TestHaLinksAreaPage:
    """Area pages get an open-in-HA line; entity_ids in the area become links."""

    def test_area_page_has_open_in_ha_line(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        out = render_area_auto_block(
            AreaSnapshot(area_id="kitchen", name="Küche"),
            fixed_now,
            strings_de,
            ha_url=_HA_URL,
        )
        assert (
            f"[In Home Assistant öffnen]({_HA_URL}/config/areas/area/kitchen)"
        ) in out

    def test_area_automations_link_to_edit(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        area = AreaSnapshot(area_id="kitchen", name="Küche")
        area.automations.append(
            AutomationSnapshot(
                entity_id="automation.morning_lights",
                name="Morgenlicht",
                description=None,
                state="on",
                mode=None,
                last_triggered=None,
            ),
        )
        out = render_area_auto_block(area, fixed_now, strings_de, ha_url=_HA_URL)
        assert (
            f"[Morgenlicht]({_HA_URL}/config/automation/edit/morning_lights)"
        ) in out


class TestHaLinksBundles:
    """Automation / script / scene bundles get edit links per entry."""

    def test_automation_heading_links_to_edit(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        out = render_automations_auto_block(
            [
                AutomationSnapshot(
                    entity_id="automation.foo_bar",
                    name="Foo Bar",
                    description=None,
                    state="on",
                    mode="single",
                    last_triggered=None,
                ),
            ],
            fixed_now,
            strings_de,
            ha_url=_HA_URL,
        )
        assert (f"### [Foo Bar]({_HA_URL}/config/automation/edit/foo_bar)") in out

    def test_script_heading_links_to_edit(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        out = render_scripts_auto_block(
            [
                ScriptSnapshot(
                    entity_id="script.party_mode",
                    name="Partymodus",
                    description=None,
                    state="off",
                    last_triggered=None,
                ),
            ],
            fixed_now,
            strings_de,
            ha_url=_HA_URL,
        )
        assert (f"### [Partymodus]({_HA_URL}/config/script/edit/party_mode)") in out

    def test_scene_line_links_to_edit(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        out = render_scenes_auto_block(
            [SceneSnapshot(entity_id="scene.movie_night", name="Filmabend")],
            fixed_now,
            strings_de,
            ha_url=_HA_URL,
        )
        assert (f"[**Filmabend**]({_HA_URL}/config/scene/edit/movie_night)") in out


class TestHaLinksIntegrations:
    """Domain cell in integrations table links to the HA frontend."""

    def test_domain_cell_is_clickable(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        out = render_integrations_auto_block(
            [
                IntegrationSnapshot(
                    entry_id="abc",
                    domain="mqtt",
                    title="MQTT Broker",
                    state="loaded",
                    source="user",
                    device_count=3,
                    entity_count=12,
                ),
            ],
            fixed_now,
            strings_de,
            ha_url=_HA_URL,
        )
        assert (f"[`mqtt`]({_HA_URL}/config/integrations/integration/mqtt)") in out


class TestHaLinksHelpers:
    """Helpers page gets a single sammel-link to /config/helpers."""

    def test_helpers_page_links_to_helpers_section(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        groups = [
            HelperGroup(
                domain="input_boolean",
                entries=[
                    HelperEntry(
                        entity_id="input_boolean.guest_mode",
                        name="Gastmodus",
                        domain="input_boolean",
                        state="off",
                        attributes={},
                    ),
                ],
            ),
        ]
        out = render_helpers_auto_block(
            groups,
            fixed_now,
            strings_de,
            ha_url=_HA_URL,
        )
        assert (
            f"[Helper-Konfiguration in Home Assistant öffnen]({_HA_URL}/config/helpers)"
        ) in out
        # Per-entry deep-links go through the entity_id code-span.
        assert (
            "[`input_boolean.guest_mode`]"
            f"({_HA_URL}/developer-tools/state?entity_id=input_boolean.guest_mode)"
        ) in out

    def test_helpers_page_no_link_without_ha_url(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        out = render_helpers_auto_block([], fixed_now, strings_de)
        assert "Helper-Konfiguration" not in out
        assert "/config/helpers" not in out


class TestRenderLabel:
    """Label page (issue #22) — one table row per device carrying the label."""

    def test_device_row_with_manufacturer_model_area(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        device_url = "http://bookstack.local/books/book/page/dev1"
        area_url = "http://bookstack.local/books/book/page/living"
        label = LabelSnapshot(
            label_id="kritisch",
            name="kritisch",
            icon=None,
            devices=[_device("dev1", name="Rauchmelder")],
        )
        label.devices[0].area_id = "living"
        out = render_label_auto_block(
            label,
            fixed_now,
            strings_de,
            page_links={"device:dev1": device_url, "area:living": area_url},
            area_names={"living": "Wohnzimmer"},
        )
        assert f"[Rauchmelder]({device_url})" in out
        assert f"[Wohnzimmer]({area_url})" in out
        assert "Acme" in out  # manufacturer from _device()
        assert "Model X" in out  # model from _device()
        assert "Geräte mit diesem Label (1)" in out

    def test_device_row_falls_back_to_bold_without_links(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        label = LabelSnapshot(
            label_id="kritisch",
            name="kritisch",
            icon=None,
            devices=[_device("dev1", name="Rauchmelder")],
        )
        out = render_label_auto_block(label, fixed_now, strings_de)
        assert "**Rauchmelder**" in out
        assert "](http" not in out

    def test_device_without_area_shows_dash(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        label = LabelSnapshot(
            label_id="kritisch",
            name="kritisch",
            icon=None,
            devices=[_device("dev1", name="Rauchmelder")],
        )
        out = render_label_auto_block(label, fixed_now, strings_de)
        rows = [
            line
            for line in out.splitlines()
            if line.startswith(("| [Rauch", "| **Rauch"))
        ]
        assert len(rows) == 1
        assert rows[0].endswith("| — |")

    def test_ha_open_line_uses_config_labels(
        self,
        fixed_now: datetime,
        strings_de: dict[str, str],
    ) -> None:
        label = LabelSnapshot(
            label_id="kritisch",
            name="kritisch",
            icon=None,
            devices=[_device("dev1")],
        )
        out = render_label_auto_block(label, fixed_now, strings_de, ha_url=_HA_URL)
        assert f"[In Home Assistant öffnen]({_HA_URL}/config/labels)" in out

    def test_english_strings(
        self,
        fixed_now: datetime,
        strings_en: dict[str, str],
    ) -> None:
        label = LabelSnapshot(
            label_id="critical",
            name="critical",
            icon=None,
            devices=[_device("dev1", name="Smoke Detector")],
        )
        out = render_label_auto_block(label, fixed_now, strings_en)
        assert "Devices with this label (1)" in out
        assert "**Smoke Detector**" in out
