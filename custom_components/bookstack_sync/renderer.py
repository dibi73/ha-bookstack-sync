"""
Deterministic markdown rendering for BookStack pages.

The renderer is intentionally simple string composition rather than Jinja2:
templates would add an external file dependency for very little gain at this
size, and string composition makes it trivial to keep output byte-identical
when nothing changed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .const import ATTRIBUTION

if TYPE_CHECKING:
    from datetime import datetime

    from .extractor import (
        AreaSnapshot,
        AutomationSnapshot,
        DeviceSnapshot,
        EntitySnapshot,
        HASnapshot,
        IntegrationSnapshot,
        SceneSnapshot,
        ScriptSnapshot,
    )


def _format_attribution(now: datetime) -> str:
    return f"_{ATTRIBUTION} – Stand {now.strftime('%Y-%m-%d %H:%M')} UTC._"


def render_tombstone_auto_block(now: datetime) -> str:
    """
    Render the AUTO block for a page whose HA object no longer exists.

    The MANUAL block stays untouched - the tombstone only replaces the AUTO
    half so that the user's notes remain available for review or deletion.
    """
    return (
        f"_{ATTRIBUTION} – letzter Sync {now.strftime('%Y-%m-%d %H:%M')} UTC._\n"
        f"\n"
        f"> ⚠️ **Diese Seite ist verwaist.**\n"
        f">\n"
        f"> Das zugehörige Objekt existiert seit {now.strftime('%Y-%m-%d')} "
        f"nicht mehr in Home Assistant.\n"
        f">\n"
        f"> Der manuelle Block unten bleibt unangetastet. Wenn die Notizen "
        f"dort nicht mehr relevant sind, kannst du diese Seite manuell "
        f"löschen.\n"
    )


def render_overview_auto_block(snapshot: HASnapshot, now: datetime) -> str:
    """Render the AUTO block of the overview page."""
    total_devices = sum(len(area.devices) for area in snapshot.areas) + len(
        snapshot.unassigned_devices,
    )
    total_entities = sum(
        len(d.entities) for area in snapshot.areas for d in area.devices
    ) + sum(len(d.entities) for d in snapshot.unassigned_devices)

    lines: list[str] = [
        _format_attribution(now),
        "",
        "## Statistik",
        "",
        f"- Areas: **{len(snapshot.areas)}**",
        f"- Geräte: **{total_devices}**",
        f"- Entities: **{total_entities}**",
        f"- Integrationen: **{len(snapshot.integrations)}**",
        f"- Automatisierungen: **{len(snapshot.automations)}**",
        f"- Skripte: **{len(snapshot.scripts)}**",
        f"- Szenen: **{len(snapshot.scenes)}**",
        "",
        "## Räume",
        "",
    ]
    if snapshot.areas:
        lines.extend(
            f"- **{area.name}** – {len(area.devices)} Geräte" for area in snapshot.areas
        )
    else:
        lines.append("_Keine Areas konfiguriert._")

    if snapshot.unassigned_devices:
        lines.extend(
            [
                "",
                "## Geräte ohne Raum-Zuordnung",
                "",
            ],
        )
        lines.extend(f"- {device.name}" for device in snapshot.unassigned_devices)

    return "\n".join(lines)


def render_area_auto_block(area: AreaSnapshot, now: datetime) -> str:
    """Render the AUTO block of one area page."""
    lines: list[str] = [
        _format_attribution(now),
        "",
        f"## Geräte in {area.name}",
        "",
    ]
    if area.devices:
        for device in area.devices:
            lines.extend([f"### {device.name}", "", _device_facts_table(device)])
            if device.entities:
                lines.extend(
                    [
                        "",
                        "**Entities**",
                        "",
                        *_entity_lines(device.entities),
                    ],
                )
            lines.append("")
    else:
        lines.append("_Keine Geräte in diesem Raum._")

    if area.orphan_entities:
        lines.extend(
            [
                "",
                "## Entities ohne Geräte-Zuordnung",
                "",
                *_entity_lines(area.orphan_entities),
            ],
        )
    return "\n".join(lines).rstrip() + "\n"


def render_device_auto_block(device: DeviceSnapshot, now: datetime) -> str:
    """Render the AUTO block of one device page."""
    lines: list[str] = [
        _format_attribution(now),
        "",
        "## Stammdaten",
        "",
        _device_facts_table(device),
        "",
        "## Entities",
        "",
    ]
    if device.entities:
        lines.extend(_entity_lines(device.entities))
    else:
        lines.append("_Keine Entities zu diesem Gerät._")
    return "\n".join(lines).rstrip() + "\n"


def _device_facts_table(device: DeviceSnapshot) -> str:
    rows = [
        ("Hersteller", device.manufacturer or "—"),
        ("Modell", device.model or "—"),
        ("Firmware", device.sw_version or "—"),
        ("Hardware", device.hw_version or "—"),
        ("Integrationen", ", ".join(device.config_entries) or "—"),
        ("Device-ID", device.device_id),
    ]
    out = ["| Feld | Wert |", "| --- | --- |"]
    out.extend(f"| {key} | {value} |" for key, value in rows)
    return "\n".join(out)


def _entity_lines(entities: list[EntitySnapshot]) -> list[str]:
    return [
        f"- `{e.entity_id}` – {e.name}"
        + (f" (State: `{e.state}`)" if e.state is not None else "")
        + (" _[disabled]_" if e.disabled else "")
        for e in entities
    ]


def render_automations_auto_block(
    automations: list[AutomationSnapshot],
    now: datetime,
) -> str:
    """Render the AUTO block listing every HA automation."""
    lines: list[str] = [
        _format_attribution(now),
        "",
        f"## Automatisierungen ({len(automations)})",
        "",
    ]
    if not automations:
        lines.append("_Keine Automatisierungen vorhanden._")
        return "\n".join(lines).rstrip() + "\n"

    for auto in automations:
        lines.extend(_automation_block(auto))
    return "\n".join(lines).rstrip() + "\n"


def render_scripts_auto_block(
    scripts: list[ScriptSnapshot],
    now: datetime,
) -> str:
    """Render the AUTO block listing every HA script."""
    lines: list[str] = [
        _format_attribution(now),
        "",
        f"## Skripte ({len(scripts)})",
        "",
    ]
    if not scripts:
        lines.append("_Keine Skripte vorhanden._")
        return "\n".join(lines).rstrip() + "\n"

    for script in scripts:
        lines.extend(_script_block(script))
    return "\n".join(lines).rstrip() + "\n"


def render_scenes_auto_block(
    scenes: list[SceneSnapshot],
    now: datetime,
) -> str:
    """Render the AUTO block listing every HA scene."""
    lines: list[str] = [
        _format_attribution(now),
        "",
        f"## Szenen ({len(scenes)})",
        "",
    ]
    if not scenes:
        lines.append("_Keine Szenen vorhanden._")
        return "\n".join(lines).rstrip() + "\n"

    lines.extend(f"- **{s.name}** – `{s.entity_id}`" for s in scenes)
    return "\n".join(lines).rstrip() + "\n"


def render_integrations_auto_block(
    integrations: list[IntegrationSnapshot],
    now: datetime,
) -> str:
    """Render the AUTO block listing every installed integration / config entry."""
    lines: list[str] = [
        _format_attribution(now),
        "",
        f"## Integrationen ({len(integrations)})",
        "",
    ]
    if not integrations:
        lines.append("_Keine Integrationen geladen._")
        return "\n".join(lines).rstrip() + "\n"

    lines.extend(
        [
            "| Integration | Titel | Status | Quelle | Geräte | Entities |",
            "| --- | --- | --- | --- | ---: | ---: |",
        ],
    )
    lines.extend(
        f"| `{i.domain}` | {i.title} | {i.state} | {i.source} "
        f"| {i.device_count} | {i.entity_count} |"
        for i in integrations
    )
    return "\n".join(lines).rstrip() + "\n"


def _automation_block(auto: AutomationSnapshot) -> list[str]:
    block = [
        f"### {auto.name}",
        "",
        f"- Entity: `{auto.entity_id}`",
    ]
    if auto.state is not None:
        block.append(f"- Status: `{auto.state}`")
    if auto.mode:
        block.append(f"- Modus: `{auto.mode}`")
    if auto.last_triggered:
        block.append(f"- Letzter Trigger: {auto.last_triggered}")
    if auto.description:
        block.extend(["", f"> {auto.description}"])
    block.append("")
    return block


def _script_block(script: ScriptSnapshot) -> list[str]:
    block = [
        f"### {script.name}",
        "",
        f"- Entity: `{script.entity_id}`",
    ]
    if script.state is not None:
        block.append(f"- Status: `{script.state}`")
    if script.last_triggered:
        block.append(f"- Letzter Trigger: {script.last_triggered}")
    if script.description:
        block.extend(["", f"> {script.description}"])
    block.append("")
    return block
