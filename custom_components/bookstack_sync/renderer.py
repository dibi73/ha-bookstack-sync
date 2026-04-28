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

from typing import TYPE_CHECKING

from .const import ATTRIBUTION

if TYPE_CHECKING:
    from datetime import datetime

    from .extractor import (
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


def _format_attribution(strings: dict[str, str], now: datetime) -> str:
    return strings["attribution_template"].format(
        attribution=ATTRIBUTION,
        timestamp=now.strftime("%Y-%m-%d %H:%M"),
    )


def _md_escape(value: str) -> str:
    """
    Escape characters that would break a markdown table or inject HTML.

    BookStack renders markdown safely by default but we don't want a device
    named ``Living Room | <script>`` to either break the table layout or end
    up as an inline HTML tag if a user enables raw-HTML in BookStack.
    """
    if not value:
        return value
    return (
        value.replace("\\", "\\\\")
        .replace("|", "\\|")
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
        ("addons:_", strings["bundle_addons"]),
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


def render_area_auto_block(
    area: AreaSnapshot,
    now: datetime,
    strings: dict[str, str],
) -> str:
    """Render the AUTO block of one area page."""
    lines: list[str] = [
        _format_attribution(strings, now),
        "",
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
    return "\n".join(lines).rstrip() + "\n"


def render_device_auto_block(
    device: DeviceSnapshot,
    now: datetime,
    strings: dict[str, str],
) -> str:
    """Render the AUTO block of one device page."""
    lines: list[str] = [
        _format_attribution(strings, now),
        "",
        f"## {strings['section_master_data']}",
        "",
        _device_facts_table(device, strings),
        "",
        f"## {strings['section_entities']}",
        "",
    ]
    if device.entities:
        lines.extend(_entity_lines(device.entities, strings))
    else:
        lines.append(strings["empty_entities_in_device"])
    return "\n".join(lines).rstrip() + "\n"


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
        f"| {strings['integration_col_entities']} |"
    )
    lines.extend([header, "| --- | --- | --- | --- | ---: | ---: |"])
    lines.extend(
        f"| `{i.domain}` | {_md_escape(i.title)} | {i.state} | {i.source} "
        f"| {i.device_count} | {i.entity_count} |"
        for i in integrations
    )
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


def _entity_lines(
    entities: list[EntitySnapshot],
    strings: dict[str, str],
) -> list[str]:
    state_label = strings["entity_state_label"]
    topic_label = strings["entity_topic_label"]
    disabled = strings["entity_disabled_marker"]
    return [
        f"- `{e.entity_id}` – {_md_escape(e.name)}"
        + (f" ({state_label}: `{e.state}`)" if e.state is not None else "")
        + (f" ({topic_label}: `{e.mqtt_topic}`)" if e.mqtt_topic else "")
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
