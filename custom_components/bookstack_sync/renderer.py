"""
Deterministic markdown rendering for BookStack pages.

The renderer is intentionally simple string composition rather than Jinja2:
templates would add an external file dependency for very little gain at this
size, and string composition makes it trivial to keep output byte-identical
when nothing changed.

Every public ``render_*`` function takes a ``strings`` mapping (see
``_strings.get_strings``). The mapping carries every visible text so the
output language follows the user's choice without changing render code.
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

from .const import ATTRIBUTION

# Inline TOC at the top of an area page only renders when the area has
# at least this many "elements" (devices + automations + scripts + scenes).
# Below this we'd be adding noise to a page that already fits on one
# screen.
_AREA_TOC_THRESHOLD = 3

if TYPE_CHECKING:
    from datetime import datetime

    from .extractor import (
        AddonSnapshot,
        AreaSnapshot,
        AutomationSnapshot,
        BluetoothNetwork,
        DeviceSnapshot,
        EnergyConfig,
        EntitySnapshot,
        HASnapshot,
        HelperGroup,
        IntegrationSnapshot,
        MqttTopicNode,
        MqttTopicTree,
        NetworkInfo,
        RecorderConfig,
        ReverseUsageEntry,
        SceneSnapshot,
        ScriptSnapshot,
        ServiceInfo,
        UnifiTopology,
    )


def _format_attribution(strings: dict[str, str], now: datetime) -> str:
    return strings["attribution_template"].format(
        attribution=ATTRIBUTION,
        timestamp=now.strftime("%Y-%m-%d %H:%M"),
    )


def _slugify(text: str) -> str:
    """
    Generate a heading-anchor slug compatible with BookStack's renderer.

    BookStack uses a GitHub-style auto-anchor algorithm: lowercase ASCII,
    runs of non-alphanumeric collapsed to ``-``, leading/trailing
    hyphens stripped. Umlauts and other non-ASCII characters are
    transliterated via NFKD + ASCII fold (so ``Wohnzimmer Süd`` becomes
    ``wohnzimmer-sud``). On exotic characters the slug may diverge from
    BookStack's exact output - in the worst case the click jump fails
    and the user has to scroll, the page itself still reads fine.
    """
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = nfkd.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")


def _md_escape(value: str) -> str:
    """
    Escape characters that would break a markdown table or inject HTML.

    BookStack renders markdown safely by default but we don't want a device
    named ``Living Room | <script>`` to either break the table layout or end
    up as an inline HTML tag if a user enables raw-HTML in BookStack.

    ``[`` / ``]`` are escaped to defuse a name like
    ``Lampe](javascript:alert(1))`` from breaking out of a markdown link
    label and injecting a clickable ``javascript:`` URL. BookStack's own
    sanitiser strips ``javascript:`` schemes on render, but treating that
    as defence-in-depth lets us not depend on it.
    """
    if not value:
        return value
    return (
        value.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", " ")
    )


def render_tombstone_auto_block(strings: dict[str, str], now: datetime) -> str:
    """Render the AUTO block for a page whose HA object no longer exists."""
    attribution = strings["tombstone_attribution_template"].format(
        attribution=ATTRIBUTION,
        timestamp=now.strftime("%Y-%m-%d %H:%M"),
    )
    explanation = strings["tombstone_explanation_template"].format(
        date=now.strftime("%Y-%m-%d"),
    )
    return (
        f"{attribution}\n"
        f"\n"
        f"> {strings['tombstone_warning']}\n"
        f">\n"
        f"> {explanation}\n"
        f">\n"
        f"> {strings['tombstone_manual_hint']}\n"
    )


def render_overview_auto_block(
    snapshot: HASnapshot,
    now: datetime,
    strings: dict[str, str],
    page_links: dict[str, int] | None = None,
) -> str:
    """Render the AUTO block of the overview page (with optional page links)."""
    links = page_links or {}
    total_devices = sum(len(area.devices) for area in snapshot.areas) + len(
        snapshot.unassigned_devices,
    )
    total_entities = sum(
        len(d.entities) for area in snapshot.areas for d in area.devices
    ) + sum(len(d.entities) for d in snapshot.unassigned_devices)

    lines: list[str] = [
        _format_attribution(strings, now),
        "",
        f"## {strings['section_statistics']}",
        "",
        f"- {strings['stat_areas']}: **{len(snapshot.areas)}**",
        f"- {strings['stat_devices']}: **{total_devices}**",
        f"- {strings['stat_entities']}: **{total_entities}**",
        f"- {strings['stat_integrations']}: **{len(snapshot.integrations)}**",
        f"- {strings['stat_automations']}: **{len(snapshot.automations)}**",
        f"- {strings['stat_scripts']}: **{len(snapshot.scripts)}**",
        f"- {strings['stat_scenes']}: **{len(snapshot.scenes)}**",
        f"- {strings['stat_addons']}: **{len(snapshot.addons)}**",
        "",
        f"## {strings['section_categories']}",
        "",
    ]
    bundle_links = (
        ("integrations:_", strings["bundle_integrations"]),
        ("automations:_", strings["bundle_automations"]),
        ("scripts:_", strings["bundle_scripts"]),
        ("scenes:_", strings["bundle_scenes"]),
        ("helpers:_", strings["bundle_helpers"]),
        ("addons:_", strings["bundle_addons"]),
        ("network:_", strings["bundle_network"]),
        ("bluetooth:_", strings["bundle_bluetooth"]),
        ("services:_", strings["bundle_services"]),
        ("recorder:_", strings["bundle_recorder"]),
        ("mqtt:_", strings["bundle_mqtt"]),
        ("energy:_", strings["bundle_energy"]),
    )
    for key, label in bundle_links:
        page_id = links.get(key)
        if page_id is not None:
            lines.append(f"- [{label}](page:{page_id})")
        else:
            lines.append(f"- {label}")

    lines.extend(["", f"## {strings['section_areas']}", ""])
    if snapshot.areas:
        for area in snapshot.areas:
            label = _md_escape(area.name)
            page_id = links.get(f"area:{area.area_id}")
            link = (
                f"[{label}](page:{page_id})" if page_id is not None else f"**{label}**"
            )
            lines.append(
                f"- {link} – {len(area.devices)} {strings['stat_devices']}",
            )
    else:
        lines.append(strings["empty_areas"])

    if snapshot.unassigned_devices:
        lines.extend(
            [
                "",
                f"## {strings['section_unassigned_devices']}",
                "",
            ],
        )
        for device in snapshot.unassigned_devices:
            label = _md_escape(device.name)
            page_id = links.get(f"device:{device.device_id}")
            link = f"[{label}](page:{page_id})" if page_id is not None else label
            lines.append(f"- {link}")

    return "\n".join(lines)


def _area_toc_lines(
    area: AreaSnapshot,
    strings: dict[str, str],
) -> list[str]:
    """
    Build an inline TOC for big area pages.

    Returns ``[]`` for areas with fewer than ``_AREA_TOC_THRESHOLD``
    elements (devices + automations + scripts + scenes) so small areas
    don't get a noisy table-of-one.
    """
    total = (
        len(area.devices) + len(area.automations) + len(area.scripts) + len(area.scenes)
    )
    if total < _AREA_TOC_THRESHOLD:
        return []

    name = _md_escape(area.name)
    raw_name = area.name
    lines: list[str] = [f"**{strings['toc_label']}**", ""]

    if area.devices:
        section = strings["section_devices_in_area_template"].format(name=name)
        section_anchor = _slugify(
            strings["section_devices_in_area_template"].format(name=raw_name),
        )
        lines.append(f"- [{section}](#{section_anchor})")
        lines.extend(
            f"  - [{_md_escape(d.name)}](#{_slugify(d.name)})" for d in area.devices
        )

    if area.automations:
        section = strings["section_automations_in_area_template"].format(name=name)
        section_anchor = _slugify(
            strings["section_automations_in_area_template"].format(name=raw_name),
        )
        lines.append(f"- [{section}](#{section_anchor})")
        lines.extend(
            f"  - [{_md_escape(a.name)}](#{_slugify(a.name)})" for a in area.automations
        )

    if area.scripts:
        section = strings["section_scripts_in_area_template"].format(name=name)
        section_anchor = _slugify(
            strings["section_scripts_in_area_template"].format(name=raw_name),
        )
        lines.append(f"- [{section}](#{section_anchor})")
        lines.extend(
            f"  - [{_md_escape(s.name)}](#{_slugify(s.name)})" for s in area.scripts
        )

    if area.scenes:
        section = strings["section_scenes_in_area_template"].format(name=name)
        section_anchor = _slugify(
            strings["section_scenes_in_area_template"].format(name=raw_name),
        )
        lines.append(f"- [{section}](#{section_anchor})")
        # Scenes don't get individual H3 headings (they're rendered as a
        # bulleted list), so no per-scene sub-bullets.

    lines.append("")
    return lines


def render_area_auto_block(
    area: AreaSnapshot,
    now: datetime,
    strings: dict[str, str],
) -> str:
    """Render the AUTO block of one area page."""
    lines: list[str] = [
        _format_attribution(strings, now),
        "",
        *_area_toc_lines(area, strings),
        "## "
        + strings["section_devices_in_area_template"].format(
            name=_md_escape(area.name),
        ),
        "",
    ]
    if area.devices:
        for device in area.devices:
            lines.extend(
                [
                    f"### {_md_escape(device.name)}",
                    "",
                    _device_facts_table(device, strings),
                ],
            )
            if device.entities:
                lines.extend(
                    [
                        "",
                        f"**{strings['label_entities']}**",
                        "",
                        *_entity_lines(device.entities, strings),
                    ],
                )
            lines.append("")
    else:
        lines.append(strings["empty_devices_in_room"])

    if area.orphan_entities:
        lines.extend(
            [
                "",
                f"## {strings['section_orphan_entities']}",
                "",
                *_entity_lines(area.orphan_entities, strings),
            ],
        )

    if area.automations:
        lines.extend(
            [
                "",
                "## "
                + strings["section_automations_in_area_template"].format(
                    name=_md_escape(area.name),
                ),
                "",
            ],
        )
        for auto in area.automations:
            lines.extend(_automation_block(auto, strings))

    if area.scripts:
        lines.extend(
            [
                "",
                "## "
                + strings["section_scripts_in_area_template"].format(
                    name=_md_escape(area.name),
                ),
                "",
            ],
        )
        for script in area.scripts:
            lines.extend(_script_block(script, strings))

    if area.scenes:
        lines.extend(
            [
                "",
                "## "
                + strings["section_scenes_in_area_template"].format(
                    name=_md_escape(area.name),
                ),
                "",
            ],
        )
        lines.extend(
            f"- **{_md_escape(s.name)}** – `{s.entity_id}`" for s in area.scenes
        )

    return "\n".join(lines).rstrip() + "\n"


def render_device_auto_block(
    device: DeviceSnapshot,
    now: datetime,
    strings: dict[str, str],
    reverse_usage: dict[str, list[ReverseUsageEntry]] | None = None,
) -> str:
    """Render the AUTO block of one device page."""
    lines: list[str] = [
        _format_attribution(strings, now),
        "",
        f"## {strings['section_master_data']}",
        "",
        _device_facts_table(device, strings),
    ]
    if device.network is not None:
        lines.extend(_network_section(device, strings))
    lines.extend(["", f"## {strings['section_entities']}", ""])
    if device.entities:
        lines.extend(_entity_lines(device.entities, strings))
    else:
        lines.append(strings["empty_entities_in_device"])
    if reverse_usage:
        lines.extend(_used_by_section(device, strings, reverse_usage))
    return "\n".join(lines).rstrip() + "\n"


def _used_by_section(
    device: DeviceSnapshot,
    strings: dict[str, str],
    reverse_usage: dict[str, list[ReverseUsageEntry]],
) -> list[str]:
    """
    Render the ``Verwendet in`` block for a device page (#43).

    Aggregates reverse-usage across all entities of the device. Output
    grouped by domain (automation / script / scene). Returns ``[]`` when
    no entity is referenced anywhere — keeps unused devices clean.
    """
    by_domain: dict[str, set[str]] = {
        "automation": set(),
        "script": set(),
        "scene": set(),
    }
    for entity in device.entities:
        for entry in reverse_usage.get(entity.entity_id, []):
            if entry.domain in by_domain:
                by_domain[entry.domain].add(entry.name)
    if not any(by_domain.values()):
        return []

    lines: list[str] = ["", f"## {strings['section_used_by']}", ""]
    for domain, domain_label_key in (
        ("automation", "used_by_automations"),
        ("script", "used_by_scripts"),
        ("scene", "used_by_scenes"),
    ):
        names = by_domain[domain]
        if not names:
            continue
        lines.extend(["", f"### {strings[domain_label_key]}", ""])
        lines.extend(f"- {_md_escape(name)}" for name in sorted(names, key=str.lower))
    return lines


def _network_section(
    device: DeviceSnapshot,
    strings: dict[str, str],
) -> list[str]:
    """
    Render the network sub-section of a device page.

    Primary connection (most-recent ``last_seen``) is shown as bullet
    points; additional concurrent connections (e.g. NUC plugged in via
    both ethernet and WiFi) are appended as ``(also: ...)``-style
    parenthetical entries.
    """
    primary = device.network
    if primary is None:
        return []

    def conn_label(info_obj: object) -> str:
        ct = getattr(info_obj, "connection_type", None)
        if ct == "wired":
            return strings["connection_wired"]
        if ct == "wireless":
            return strings["connection_wireless"]
        return strings.get("connection_unknown", "?")

    lines: list[str] = ["", f"### {strings['section_network']}", ""]

    def with_extra(label: str, primary_val: str | None, attr: str) -> str | None:
        """Format ``- label: primary (also: extra1, extra2)`` if any value."""
        if primary_val is None and not any(
            getattr(e, attr, None) for e in device.network_extra
        ):
            return None
        extras = [
            getattr(e, attr) for e in device.network_extra if getattr(e, attr, None)
        ]
        body = primary_val or "—"
        if extras:
            also = strings["network_also_template"].format(values=", ".join(extras))
            body += f" ({also})"
        return f"- {label}: {body}"

    ip_line = with_extra(strings["field_ip"], primary.ip, "ip")
    if ip_line:
        lines.append(ip_line)
    mac_line = with_extra(strings["field_mac"], primary.mac, "mac")
    if mac_line:
        lines.append(mac_line)
    host_line = with_extra(strings["field_hostname"], primary.hostname, "hostname")
    if host_line:
        lines.append(host_line)
    if primary.connection_type:
        suffix = ""
        extra_types = [conn_label(e) for e in device.network_extra if e.connection_type]
        if extra_types:
            also = strings["network_also_template"].format(
                values=", ".join(extra_types),
            )
            suffix = f" ({also})"
        lines.append(f"- {strings['field_connection']}: {conn_label(primary)}{suffix}")
    if primary.vlan:
        lines.append(f"- {strings['field_vlan']}: {_md_escape(primary.vlan)}")
    if primary.ssid:
        lines.append(f"- {strings['field_ssid']}: {_md_escape(primary.ssid)}")
    if primary.last_seen:
        lines.append(f"- {strings['field_last_seen']}: {primary.last_seen}")

    return lines


def render_addons_auto_block(
    addons: list[AddonSnapshot],
    now: datetime,
    strings: dict[str, str],
) -> str:
    """Render the AUTO block listing every Supervisor add-on."""
    lines: list[str] = [
        _format_attribution(strings, now),
        "",
        "## " + strings["section_addons_count_template"].format(count=len(addons)),
        "",
    ]
    if not addons:
        lines.append(strings["empty_addons"])
        return "\n".join(lines).rstrip() + "\n"

    lines.extend(
        [
            f"| {strings['addon_col_name']} | {strings['addon_col_slug']} "
            f"| {strings['addon_col_version']} | {strings['addon_col_state']} "
            f"| {strings['addon_col_update']} |",
            "| --- | --- | --- | --- | --- |",
        ],
    )
    yes = strings["addon_update_yes"]
    no = strings["addon_update_no"]
    lines.extend(
        f"| {_md_escape(a.name)} | `{a.slug}` | {a.version or '—'} "
        f"| {a.state or '—'} | {yes if a.update_available else no} |"
        for a in addons
    )
    return "\n".join(lines).rstrip() + "\n"


def render_automations_auto_block(
    automations: list[AutomationSnapshot],
    now: datetime,
    strings: dict[str, str],
) -> str:
    """Render the AUTO block listing every HA automation."""
    lines: list[str] = [
        _format_attribution(strings, now),
        "",
        "## "
        + strings["section_automations_count_template"].format(
            count=len(automations),
        ),
        "",
    ]
    if not automations:
        lines.append(strings["empty_automations"])
        return "\n".join(lines).rstrip() + "\n"

    for auto in automations:
        lines.extend(_automation_block(auto, strings))
    return "\n".join(lines).rstrip() + "\n"


def render_scripts_auto_block(
    scripts: list[ScriptSnapshot],
    now: datetime,
    strings: dict[str, str],
) -> str:
    """Render the AUTO block listing every HA script."""
    lines: list[str] = [
        _format_attribution(strings, now),
        "",
        "## " + strings["section_scripts_count_template"].format(count=len(scripts)),
        "",
    ]
    if not scripts:
        lines.append(strings["empty_scripts"])
        return "\n".join(lines).rstrip() + "\n"

    for script in scripts:
        lines.extend(_script_block(script, strings))
    return "\n".join(lines).rstrip() + "\n"


def render_scenes_auto_block(
    scenes: list[SceneSnapshot],
    now: datetime,
    strings: dict[str, str],
) -> str:
    """Render the AUTO block listing every HA scene."""
    lines: list[str] = [
        _format_attribution(strings, now),
        "",
        "## " + strings["section_scenes_count_template"].format(count=len(scenes)),
        "",
    ]
    if not scenes:
        lines.append(strings["empty_scenes"])
        return "\n".join(lines).rstrip() + "\n"

    lines.extend(f"- **{_md_escape(s.name)}** – `{s.entity_id}`" for s in scenes)
    return "\n".join(lines).rstrip() + "\n"


def render_integrations_auto_block(
    integrations: list[IntegrationSnapshot],
    now: datetime,
    strings: dict[str, str],
) -> str:
    """Render the AUTO block listing every installed integration / config entry."""
    lines: list[str] = [
        _format_attribution(strings, now),
        "",
        "## "
        + strings["section_integrations_count_template"].format(
            count=len(integrations),
        ),
        "",
    ]
    if not integrations:
        lines.append(strings["empty_integrations"])
        return "\n".join(lines).rstrip() + "\n"

    header = (
        f"| {strings['integration_col_name']} "
        f"| {strings['integration_col_title']} "
        f"| {strings['integration_col_state']} "
        f"| {strings['integration_col_source']} "
        f"| {strings['integration_col_devices']} "
        f"| {strings['integration_col_entities']} "
        f"| {strings['integration_col_docs']} |"
    )
    lines.extend([header, "| --- | --- | --- | --- | ---: | ---: | --- |"])
    docs_label = strings["integration_docs_link_label"]
    for i in integrations:
        docs_cell = (
            f"[{docs_label}]({i.documentation_url})" if i.documentation_url else "—"
        )
        lines.append(
            f"| `{i.domain}` | {_md_escape(i.title)} | {i.state} | {i.source} "
            f"| {i.device_count} | {i.entity_count} | {docs_cell} |",
        )
    return "\n".join(lines).rstrip() + "\n"


def render_network_auto_block(  # noqa: PLR0912, PLR0913, PLR0915 - cohesive renderer
    devices: list[DeviceSnapshot],
    now: datetime,
    strings: dict[str, str],
    unknown_clients: list[NetworkInfo] | None = None,
    topology: UnifiTopology | None = None,
    snapshot: HASnapshot | None = None,
) -> str:
    """
    Render the AUTO block of the standalone Network page.

    One row per device that carries a primary ``NetworkInfo``. Rows are
    pre-sorted by the caller (sync.py: VLAN then IP). UniFi-specific
    columns (AP/Switch-Port, OUI) only render when at least one device
    in the list has UniFi data — keeps the table lean for non-UniFi
    setups. ``unknown_clients`` (UniFi-only) get a dedicated section
    below the main table for cross-reference cleanup.
    """
    lines: list[str] = [
        _format_attribution(strings, now),
        "",
        "## " + strings["section_network_count_template"].format(count=len(devices)),
        "",
    ]
    if not devices:
        lines.append(strings["empty_network"])
        # Don't return here — unknown_clients / DHCP block below may still
        # have content when only UniFi sees the network but HA tracks
        # nothing as a Device.

    has_unifi = any(d.network and d.network.source_platform == "unifi" for d in devices)

    if devices and has_unifi:
        header = (
            f"| {strings['network_col_hostname']} "
            f"| {strings['network_col_mac']} "
            f"| {strings['network_col_ip']} "
            f"| {strings['network_col_connection']} "
            f"| {strings['network_col_vlan']} "
            f"| {strings['network_col_ap_switch']} "
            f"| {strings['network_col_oui']} "
            f"| {strings['network_col_last_seen']} |"
        )
        lines.extend([header, "| --- | --- | --- | --- | --- | --- | --- | --- |"])
    elif devices:
        header = (
            f"| {strings['network_col_hostname']} "
            f"| {strings['network_col_mac']} "
            f"| {strings['network_col_ip']} "
            f"| {strings['network_col_connection']} "
            f"| {strings['network_col_vlan']} "
            f"| {strings['network_col_last_seen']} |"
        )
        lines.extend([header, "| --- | --- | --- | --- | --- | --- |"])

    for device in devices:
        info = device.network
        if info is None:
            continue
        hostname = _md_escape(info.hostname or device.name)
        mac = info.mac or "—"
        ip = info.ip or "—"
        if info.connection_type == "wired":
            conn = strings["connection_wired"]
        elif info.connection_type == "wireless":
            conn = strings["connection_wireless"]
        else:
            conn = "—"
        vlan_or_ssid = _md_escape(info.ssid or info.vlan or "—")
        last_seen = info.last_seen or "—"
        if has_unifi:
            ap_switch = "—"
            if info.switch_mac:
                ap_switch = f"`{info.switch_mac}`" + (
                    f" / port {info.switch_port}" if info.switch_port else ""
                )
            elif info.ap_mac:
                ap_switch = f"`{info.ap_mac}`"
            oui = _md_escape(info.oui or "—")
            lines.append(
                f"| **{hostname}** | `{mac}` | {ip} | {conn} | {vlan_or_ssid} "
                f"| {ap_switch} | {oui} | {last_seen} |",
            )
        else:
            lines.append(
                f"| **{hostname}** | `{mac}` | {ip} | {conn} | {vlan_or_ssid} "
                f"| {last_seen} |",
            )

    # UniFi-Topologie ASCII-Baum (#29) — directly after the flat table.
    if topology and snapshot:
        lines.extend(render_topology_section(topology, snapshot, strings))

    # Unknown UniFi clients (#28 cross-reference)
    if unknown_clients:
        lines.extend(
            [
                "",
                "## "
                + strings["section_unknown_clients_template"].format(
                    count=len(unknown_clients),
                ),
                "",
                strings["section_unknown_clients_intro"],
                "",
                f"| {strings['network_col_hostname']} "
                f"| {strings['network_col_mac']} "
                f"| {strings['network_col_ip']} "
                f"| {strings['network_col_last_seen']} |",
                "| --- | --- | --- | --- |",
            ],
        )
        for client in unknown_clients:
            host = _md_escape(client.hostname or "—")
            mac = client.mac or "—"
            ip = client.ip or "—"
            last_seen = client.last_seen or "—"
            lines.append(f"| `{host}` | `{mac}` | {ip} | {last_seen} |")

    # DHCP-reservation export block (#28). Generic format, sortable for
    # paste into FritzBox / OPNsense / pfsense / UniFi controller.
    dhcp_eligible = [d for d in devices if d.network and d.network.mac and d.network.ip]
    if dhcp_eligible:
        lines.extend(
            [
                "",
                f"## {strings['section_dhcp_export']}",
                "",
                "```",
                "# Format: <MAC>  <IP>  <Hostname>",
            ],
        )
        for d in dhcp_eligible:
            info = d.network
            assert info is not None  # noqa: S101 - filtered above
            host = info.hostname or d.name
            lines.append(f"{info.mac}   {info.ip}   {host}")
        lines.append("```")

    return "\n".join(lines).rstrip() + "\n"


def _device_facts_table(device: DeviceSnapshot, strings: dict[str, str]) -> str:
    rows = [
        (strings["field_manufacturer"], _md_escape(device.manufacturer or "—")),
        (strings["field_model"], _md_escape(device.model or "—")),
        (strings["field_firmware"], _md_escape(device.sw_version or "—")),
        (strings["field_hardware"], _md_escape(device.hw_version or "—")),
        (
            strings["field_integrations"],
            _md_escape(", ".join(device.config_entries) or "—"),
        ),
        (strings["field_device_id"], device.device_id),
    ]
    header = f"| {strings['table_field_header']} | {strings['table_value_header']} |"
    out = [header, "| --- | --- |"]
    out.extend(f"| {key} | {value} |" for key, value in rows)
    return "\n".join(out)


_STATE_CLASS_LONG_TERM_STATS = frozenset(
    {"measurement", "total", "total_increasing"},
)


def _entity_lines(
    entities: list[EntitySnapshot],
    strings: dict[str, str],
) -> list[str]:
    state_label = strings["entity_state_label"]
    topic_label = strings["entity_topic_label"]
    disabled = strings["entity_disabled_marker"]
    stats_marker = strings["entity_stats_marker"]
    return [
        f"- `{e.entity_id}` – {_md_escape(e.name)}"
        + (f" ({state_label}: `{e.state}`)" if e.state is not None else "")
        + (f" ({topic_label}: `{e.mqtt_topic}`)" if e.mqtt_topic else "")
        + (
            f" {stats_marker}"
            if e.attributes.get("state_class") in _STATE_CLASS_LONG_TERM_STATS
            else ""
        )
        + (f" {disabled}" if e.disabled else "")
        for e in entities
    ]


def _automation_block(
    auto: AutomationSnapshot,
    strings: dict[str, str],
) -> list[str]:
    block = [
        f"### {_md_escape(auto.name)}",
        "",
        f"- {strings['field_entity']}: `{auto.entity_id}`",
    ]
    if auto.state is not None:
        block.append(f"- {strings['field_status']}: `{auto.state}`")
    if auto.mode:
        block.append(f"- {strings['field_mode']}: `{auto.mode}`")
    if auto.last_triggered:
        block.append(f"- {strings['field_last_triggered']}: {auto.last_triggered}")
    if auto.description:
        block.extend(["", f"> {auto.description}"])
    block.append("")
    return block


def _script_block(
    script: ScriptSnapshot,
    strings: dict[str, str],
) -> list[str]:
    block = [
        f"### {_md_escape(script.name)}",
        "",
        f"- {strings['field_entity']}: `{script.entity_id}`",
    ]
    if script.state is not None:
        block.append(f"- {strings['field_status']}: `{script.state}`")
    if script.last_triggered:
        block.append(f"- {strings['field_last_triggered']}: {script.last_triggered}")
    if script.description:
        block.extend(["", f"> {script.description}"])
    block.append("")
    return block


# Threshold above which a switch's wired-clients are grouped by VLAN
# rather than listed flat (#29 issue decision).
_TOPOLOGY_GROUP_BY_VLAN_THRESHOLD = 10


def render_topology_section(  # noqa: PLR0915 - cohesive recursive walk
    topology: UnifiTopology,
    snapshot: HASnapshot,
    strings: dict[str, str],
) -> list[str]:
    """
    Render the ASCII tree of UniFi infrastructure as section lines.

    Returns ``[]`` when the topology has no infrastructure nodes — the
    caller decides whether to skip the whole section.
    """
    if not topology.nodes:
        return []

    # device_id → DeviceSnapshot for quick lookup.
    snap_devices: dict[str, DeviceSnapshot] = {}
    for area in snapshot.areas:
        for d in area.devices:
            snap_devices[d.device_id] = d
    for d in snapshot.unassigned_devices:
        snap_devices[d.device_id] = d

    # Reverse map: infra_device_id → list[client device_ids]
    children_by_infra: dict[str, list[str]] = {}
    for client_id, infra_id in topology.client_to_infra.items():
        children_by_infra.setdefault(infra_id, []).append(client_id)

    lines: list[str] = ["", f"## {strings['section_topology']}", "", "```"]

    def role_label(role: str) -> str:
        return {
            "gateway": "Gateway",
            "switch": "Switch",
            "ap": "AP",
        }.get(role, role)

    def render_clients_under_infra(
        infra_id: str,
        prefix: str,
    ) -> list[str]:
        client_ids = sorted(
            children_by_infra.get(infra_id, []),
            key=lambda did: (
                snap_devices[did].network.vlan or ""
                if did in snap_devices and snap_devices[did].network
                else "",
                snap_devices[did].name.lower() if did in snap_devices else did,
            ),
        )
        out: list[str] = []
        if len(client_ids) >= _TOPOLOGY_GROUP_BY_VLAN_THRESHOLD:
            # Group by VLAN.
            by_vlan: dict[str, list[str]] = {}
            for cid in client_ids:
                d = snap_devices.get(cid)
                vlan = (d.network.vlan if d and d.network else None) or "—"
                by_vlan.setdefault(vlan, []).append(cid)
            sorted_vlans = sorted(by_vlan.items(), key=lambda kv: kv[0])
            for v_idx, (vlan, members) in enumerate(sorted_vlans):
                last_v = v_idx == len(sorted_vlans) - 1
                vlan_branch = "└──" if last_v else "├──"
                out.append(f"{prefix}{vlan_branch} VLAN {vlan} ({len(members)})")
                sub = prefix + ("    " if last_v else "│   ")
                for c_idx, cid in enumerate(members):
                    last_c = c_idx == len(members) - 1
                    branch = "└──" if last_c else "├──"
                    out.append(f"{sub}{branch} {render_client_label(cid)}")
        else:
            for c_idx, cid in enumerate(client_ids):
                last = c_idx == len(client_ids) - 1
                branch = "└──" if last else "├──"
                out.append(f"{prefix}{branch} {render_client_label(cid)}")
        return out

    def render_client_label(client_id: str) -> str:
        d = snap_devices.get(client_id)
        if d is None:
            return f"(unknown {client_id})"
        info = d.network
        if info is None:
            return d.name
        ip = info.ip or "—"
        conn = "WLAN" if info.connection_type == "wireless" else "LAN"
        port_suffix = (
            f" port {info.switch_port}"
            if info.switch_port and info.connection_type == "wired"
            else ""
        )
        return f"{d.name} ({ip}) [{conn}]{port_suffix}"

    def walk_infra(node_id: str, prefix: str, *, is_last: bool) -> None:
        node = topology.nodes[node_id]
        branch = "└──" if is_last else "├──"
        # Root nodes shouldn't get a tree branch; they're emitted as headers.
        header = f"{role_label(node.role)}: {node.name}"
        if node.mac:
            header += f" — `{node.mac}`"
        if prefix == "":
            lines.append(header)
        else:
            lines.append(f"{prefix}{branch} {header}")

        child_prefix = prefix + ("    " if is_last else "│   ") if prefix else ""

        # Mid-tier infra (switches under gateway, APs under switch/gateway):
        # render their child infra nodes first, then their clients.
        for c_idx, child_id in enumerate(node.child_device_ids):
            child_last = (
                c_idx == len(node.child_device_ids) - 1
                and node_id not in children_by_infra
            )
            walk_infra(child_id, child_prefix, is_last=child_last)

        # Then render clients connected to THIS infra node.
        client_lines = render_clients_under_infra(node_id, child_prefix)
        lines.extend(client_lines)

    for r_idx, root_id in enumerate(topology.root_device_ids):
        last_root = r_idx == len(topology.root_device_ids) - 1
        if r_idx > 0:
            lines.append("")
        walk_infra(root_id, "", is_last=last_root)

    lines.append("```")
    return lines


def render_bluetooth_auto_block(
    network: BluetoothNetwork,
    now: datetime,
    strings: dict[str, str],
) -> str:
    """Render the AUTO block of the standalone Bluetooth page (#32)."""
    lines: list[str] = [
        _format_attribution(strings, now),
        "",
        "## "
        + strings["section_bluetooth_count_template"].format(
            count=len(network.scanners),
        ),
        "",
    ]
    if not network.scanners:
        lines.append(strings["empty_bluetooth"])
        return "\n".join(lines).rstrip() + "\n"

    lines.append("```")
    for s_idx, scanner in enumerate(network.scanners):
        if s_idx > 0:
            lines.append("")
        if scanner.is_proxy:
            header = strings["bt_proxy_label_template"].format(name=scanner.name)
        else:
            header = strings["bt_local_label"]
        lines.append(header)
        for d_idx, dev in enumerate(scanner.devices_heard):
            last = d_idx == len(scanner.devices_heard) - 1
            branch = "└──" if last else "├──"
            lines.append(f"{branch} {dev.name} (`{dev.address}`)")
    lines.append("```")
    return "\n".join(lines).rstrip() + "\n"


# Temporary file — content will be appended to renderer.py and deleted.


# ----- #49 Services (notify + tts) --------------------------------------------


def render_services_auto_block(
    notify: list[ServiceInfo],
    tts: list[ServiceInfo],
    now: datetime,
    strings: dict[str, str],
) -> str:
    """Render the AUTO block of the standalone Services page (#49)."""
    lines: list[str] = [_format_attribution(strings, now), ""]
    if notify:
        notify_header = strings["section_notify_count_template"].format(
            count=len(notify),
        )
        lines.extend(
            [
                f"## {notify_header}",
                "",
                "| Service | Domain |",
                "| --- | --- |",
            ],
        )
        lines.extend(f"| `{s.domain}.{s.name}` | {s.domain} |" for s in notify)
        lines.append("")
    if tts:
        tts_header = strings["section_tts_count_template"].format(count=len(tts))
        lines.extend(
            [
                f"## {tts_header}",
                "",
                "| Service | Domain |",
                "| --- | --- |",
            ],
        )
        lines.extend(f"| `{s.domain}.{s.name}` | {s.domain} |" for s in tts)
    return "\n".join(lines).rstrip() + "\n"


# ----- #48 Recorder -----------------------------------------------------------


def render_recorder_auto_block(
    config: RecorderConfig,
    now: datetime,
    strings: dict[str, str],
) -> str:
    """Render the AUTO block of the Recorder configuration page (#48)."""
    lines: list[str] = [
        _format_attribution(strings, now),
        "",
        f"## {strings['section_recorder_basic']}",
        "",
        f"- {strings['recorder_field_engine']}: {_md_escape(config.db_engine or '—')}",
        f"- {strings['recorder_field_url']}: `{config.db_url_redacted or '—'}`",
        f"- {strings['recorder_field_keep_days']}: "
        f"{config.purge_keep_days if config.purge_keep_days is not None else '—'}",
    ]
    for label_key, items in (
        ("section_recorder_excluded_domains", config.excluded_domains),
        ("section_recorder_excluded_entities", config.excluded_entities),
        ("section_recorder_included_domains", config.included_domains),
        ("section_recorder_included_entities", config.included_entities),
    ):
        if not items:
            continue
        lines.extend(["", f"## {strings[label_key]}", ""])
        lines.extend(f"- `{item}`" for item in items)
    return "\n".join(lines).rstrip() + "\n"


# ----- #52 MQTT topic tree ----------------------------------------------------


def render_mqtt_auto_block(
    tree: MqttTopicTree,
    now: datetime,
    strings: dict[str, str],
) -> str:
    """Render the AUTO block of the MQTT topic tree page (#52)."""
    mqtt_header = strings["section_mqtt_count_template"].format(
        count=tree.total_entities,
    )
    lines: list[str] = [
        _format_attribution(strings, now),
        "",
        f"## {mqtt_header}",
        "",
        "```",
    ]

    def walk(node: MqttTopicNode, prefix: str, *, is_last: bool) -> None:
        if node is not tree.root:
            branch = "└── " if is_last else "├── "
            label = node.name + ("/" if node.children else "")
            entities_label = (
                f"  ({len(node.entities)} entit"
                f"{'y' if len(node.entities) == 1 else 'ies'})"
                if node.entities
                else ""
            )
            lines.append(f"{prefix}{branch}{label}{entities_label}")
            child_prefix = prefix + ("    " if is_last else "│   ")
        else:
            child_prefix = prefix
        children = sorted(node.children.items(), key=lambda kv: kv[0])
        for idx, (_seg, child) in enumerate(children):
            walk(child, child_prefix, is_last=idx == len(children) - 1)

    walk(tree.root, "", is_last=True)
    lines.append("```")
    return "\n".join(lines).rstrip() + "\n"


# ----- #46 Energy -------------------------------------------------------------


def render_energy_auto_block(
    config: EnergyConfig,
    now: datetime,
    strings: dict[str, str],
) -> str:
    """Render the AUTO block of the Energy-Dashboard page (#46)."""
    lines: list[str] = [_format_attribution(strings, now), ""]
    if config.sources:
        lines.extend(
            [
                f"## {strings['section_energy_sources']}",
                "",
                "| Typ | Bezeichnung | Verbrauch | Erzeugung | Kosten |",
                "| --- | --- | --- | --- | --- |",
            ],
        )
        lines.extend(
            f"| {_md_escape(s.type)} | {_md_escape(s.label)} "
            f"| `{s.consumption_entity or '—'}` "
            f"| `{s.production_entity or '—'}` "
            f"| `{s.cost_entity or '—'}` |"
            for s in config.sources
        )
    if config.individual_devices:
        lines.extend(
            [
                "",
                f"## {strings['section_energy_devices']}",
                "",
            ],
        )
        lines.extend(f"- `{entity_id}`" for entity_id in config.individual_devices)
    return "\n".join(lines).rstrip() + "\n"


# ----- #42 Helpers ------------------------------------------------------------


_HELPER_DOMAIN_LABELS = {
    "input_boolean": "Boolesche Schalter (input_boolean)",
    "input_number": "Zahlen-Helpers (input_number)",
    "input_select": "Auswahl-Helpers (input_select)",
    "input_text": "Text-Helpers (input_text)",
    "input_datetime": "Datum/Zeit-Helpers (input_datetime)",
    "input_button": "Button-Helpers (input_button)",
    "timer": "Timer",
    "counter": "Zähler (counter)",
    "schedule": "Zeitpläne (schedule)",
    "todo": "Aufgaben-Listen (todo)",
    "template": "Template-Helpers",
    "group": "Gruppen (group)",
}


def render_helpers_auto_block(
    groups: list[HelperGroup],
    now: datetime,
    strings: dict[str, str],
) -> str:
    """Render the AUTO block of the Helpers page (#42)."""
    lines: list[str] = [_format_attribution(strings, now), ""]
    if not groups:
        lines.append(strings["empty_helpers"])
        return "\n".join(lines).rstrip() + "\n"

    for group in groups:
        label = _HELPER_DOMAIN_LABELS.get(group.domain, group.domain)
        lines.extend(
            [
                f"## {label} ({len(group.entries)})",
                "",
                "| Name | Entity | State |",
                "| --- | --- | --- |",
            ],
        )
        for entry in group.entries:
            state = entry.state if entry.state is not None else "—"
            lines.append(
                f"| **{_md_escape(entry.name)}** | `{entry.entity_id}` | `{state}` |",
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
