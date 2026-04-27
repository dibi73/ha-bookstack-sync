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
        AddonSnapshot,
        AreaSnapshot,
        DeviceSnapshot,
        EntitySnapshot,
        HASnapshot,
    )


def _format_attribution(now: datetime) -> str:
    return f"_{ATTRIBUTION} – Stand {now.strftime('%Y-%m-%d %H:%M')} UTC._"


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
        f"- Add-ons: **{len(snapshot.addons)}**",
        "",
        "## Räume",
        "",
    ]
    if snapshot.areas:
        lines.extend(
            f"- **{_md_escape(area.name)}** – {len(area.devices)} Geräte"
            for area in snapshot.areas
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
        lines.extend(
            f"- {_md_escape(device.name)}" for device in snapshot.unassigned_devices
        )

    return "\n".join(lines)


def render_area_auto_block(area: AreaSnapshot, now: datetime) -> str:
    """Render the AUTO block of one area page."""
    lines: list[str] = [
        _format_attribution(now),
        "",
        f"## Geräte in {_md_escape(area.name)}",
        "",
    ]
    if area.devices:
        for device in area.devices:
            lines.extend(
                [f"### {_md_escape(device.name)}", "", _device_facts_table(device)],
            )
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


def render_addons_auto_block(
    addons: list[AddonSnapshot],
    now: datetime,
) -> str:
    """Render the AUTO block listing every Supervisor add-on."""
    lines: list[str] = [
        _format_attribution(now),
        "",
        f"## Add-ons ({len(addons)})",
        "",
    ]
    if not addons:
        lines.append(
            "_Kein Supervisor verfügbar oder keine Add-ons installiert._",
        )
        return "\n".join(lines).rstrip() + "\n"

    lines.extend(
        [
            "| Add-on | Slug | Version | Status | Update |",
            "| --- | --- | --- | --- | --- |",
        ],
    )
    lines.extend(
        f"| {_md_escape(a.name)} | `{a.slug}` | {a.version or '—'} "
        f"| {a.state or '—'} | {'Ja' if a.update_available else 'nein'} |"
        for a in addons
    )
    return "\n".join(lines).rstrip() + "\n"


def _device_facts_table(device: DeviceSnapshot) -> str:
    rows = [
        ("Hersteller", _md_escape(device.manufacturer or "—")),
        ("Modell", _md_escape(device.model or "—")),
        ("Firmware", _md_escape(device.sw_version or "—")),
        ("Hardware", _md_escape(device.hw_version or "—")),
        (
            "Integrationen",
            _md_escape(", ".join(device.config_entries) or "—"),
        ),
        ("Device-ID", device.device_id),
    ]
    out = ["| Feld | Wert |", "| --- | --- |"]
    out.extend(f"| {key} | {value} |" for key, value in rows)
    return "\n".join(out)


def _entity_lines(entities: list[EntitySnapshot]) -> list[str]:
    return [
        f"- `{e.entity_id}` – {_md_escape(e.name)}"
        + (f" (State: `{e.state}`)" if e.state is not None else "")
        + (f" (Topic: `{e.mqtt_topic}`)" if e.mqtt_topic else "")
        + (" _[disabled]_" if e.disabled else "")
        for e in entities
    ]
