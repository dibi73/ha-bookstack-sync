"""
YAML frontmatter builder for the markdown back-export (issue #61, A3).

Schema v1 keeps only the fields that are cheap to populate without a
fresh HA registry walk: BookStack-side metadata (page id, chapter,
tags, timestamps) plus the HA-side identity parsed from the mapping
key (``device:UUID``, ``area:UUID``, ``overview:_``, …). Richer fields
(manufacturer, model, entity_states, …) are already in the page's
markdown body and would only duplicate them — the frontmatter exists
for filterable RAG queries, not as a second copy of the content.

If a future release wants the rich HA metadata in the frontmatter,
``build`` can take a snapshot argument; the schema is forward-compatible
because ``yaml.safe_dump`` ignores unknown fields on load.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import yaml

from .const import EXPORT_FORMAT_VERSION, TAG_NAME


@dataclass(frozen=True)
class ExportFrontmatter:
    """v1 frontmatter schema. Order matters — drives YAML output order."""

    title: str
    bookstack_page_id: int
    bookstack_book_id: int
    bookstack_chapter_id: int | None
    bookstack_chapter: str | None
    bookstack_tags: list[str] = field(default_factory=list)
    bookstack_created_at: str = ""
    bookstack_updated_at: str = ""

    ha_object_kind: str = ""  # "device" | "area" | "overview" | "bundle" | …
    ha_object_id: str | None = None

    last_synced: str = ""
    tombstoned: bool = False
    export_version: str = EXPORT_FORMAT_VERSION
    content_hash: str = ""


def parse_mapping_key(key: str) -> tuple[str, str | None]:
    """
    Split a storage mapping key into ``(kind, id_or_none)``.

    Examples: ``device:abc123`` → ``("device", "abc123")``;
    ``overview:_`` → ``("overview", None)``;
    ``bundle:automations`` → ``("bundle", "automations")``.
    """
    if ":" not in key:
        return key, None
    kind, _, rest = key.partition(":")
    return kind, rest if rest and rest != "_" else None


def _bookstack_tag_values(tags: list[dict[str, Any]] | None) -> list[str]:
    """Return user-visible tag values; drop the ``bookstack_sync`` marker."""
    if not tags:
        return []
    return [
        str(tag.get("value", ""))
        for tag in tags
        if tag.get("name") != TAG_NAME and tag.get("value")
    ]


def build(  # noqa: PLR0913 - keyword-only args; flat list is clearer than a wrapper struct
    *,
    mapping_key: str,
    bookstack_page: dict[str, Any],
    book_id: int,
    chapter_lookup: dict[int, str],
    tombstoned: bool,
    last_synced: str,
) -> ExportFrontmatter:
    """
    Build the v1 frontmatter for a single page.

    ``chapter_lookup`` maps BookStack chapter id → chapter name; passed in
    so the caller can fetch chapters once per export run instead of once
    per page.
    """
    chapter_id_raw = bookstack_page.get("chapter_id")
    chapter_id = int(chapter_id_raw) if chapter_id_raw else None
    chapter_name = chapter_lookup.get(chapter_id) if chapter_id else None

    kind, object_id = parse_mapping_key(mapping_key)

    return ExportFrontmatter(
        title=str(bookstack_page.get("name", "")),
        bookstack_page_id=int(bookstack_page["id"]),
        bookstack_book_id=book_id,
        bookstack_chapter_id=chapter_id,
        bookstack_chapter=chapter_name,
        bookstack_tags=_bookstack_tag_values(bookstack_page.get("tags")),
        bookstack_created_at=str(bookstack_page.get("created_at", "")),
        bookstack_updated_at=str(bookstack_page.get("updated_at", "")),
        ha_object_kind=kind,
        ha_object_id=object_id,
        last_synced=last_synced,
        tombstoned=tombstoned,
    )


def to_yaml(fm: ExportFrontmatter, content_hash: str) -> str:
    """
    Serialise the frontmatter as YAML.

    ``content_hash`` is filled here (not on the dataclass) because the
    hash is computed over the body+frontmatter; threading it through the
    dataclass would require two passes.

    YAML options: ``allow_unicode=True`` so umlauts stay as umlauts in
    the file (UTF-8 encoding); ``sort_keys=False`` so the output order
    matches the dataclass declaration; ``default_flow_style=False`` so
    list values render as block lists, not inline JSON.
    """
    payload = asdict(fm)
    payload["content_hash"] = content_hash
    return yaml.safe_dump(
        payload,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
