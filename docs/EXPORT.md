# Markdown Export for RAG / LLM Pipelines

Since v0.13.0, ha-bookstack-sync can write the merged content of every
managed BookStack page (auto block **plus** your manual notes) back to a
folder of plain Markdown files with YAML frontmatter. The folder format
is intentionally generic — every modern RAG framework (LangChain,
LlamaIndex, Open WebUI, etc.) ingests it natively.

## Opt-in by design

The export is **disabled by default**. Reasons:

- It costs disk space — on a 200-device setup, a few MB on every export
  run.
- It costs CPU and BookStack API round-trips — one GET per managed page.
- Most users only need the BookStack pages themselves; a separate
  Markdown copy is only useful if you actually have a downstream RAG /
  LLM pipeline.

To turn it on, open the integration's *Configure* dialog
(**Settings → Devices & Services → BookStack Sync → Configure**) and
enable **Markdown-Export aktivieren** (*Enable Markdown back-export*).
You can then either call the service `bookstack_sync.export_markdown`
manually / from automations, or enable **Export nach jedem Sync
automatisch ausführen** to chain the export after every successful sync.

## Output layout

```
<output>/                           ← default: <HA-config>/bookstack_export/
├── _index.md                       ← always regenerated, lists every file
├── devices/
│   ├── light-living-room.md
│   ├── sensor-hallway.md
│   └── ...
├── areas/
│   └── living-room.md
└── automations/
    └── away-mode.md
```

- **One folder per BookStack chapter.** Folder names are slugs of the
  chapter name (`Devices` → `devices/`).
- **One file per page.** Filename is a slug of the page title.
- **`_index.md`** lists everything that was exported, grouped by folder.
  Useful as a single landing page for a RAG indexer that wants a
  hierarchy hint.

## File format

```markdown
---
title: <BookStack page title>
bookstack_page_id: <int>
bookstack_book_id: <int>
bookstack_chapter_id: <int | null>
bookstack_chapter: <string | null>
bookstack_tags:
  - <user-added tag value>
  - ...
bookstack_created_at: "<ISO-8601>"
bookstack_updated_at: "<ISO-8601>"
ha_object_kind: <device | area | overview | bundle | ...>
ha_object_id: <string | null>
last_synced: "<ISO-8601>"
tombstoned: <bool>
export_version: "1"
content_hash: "<sha256-hex>"
---

[auto block — verbatim from the BookStack AUTO-GENERATED region,
 marker comments removed]

---

[manual block — verbatim from the BookStack MANUAL region]
```

Field semantics:

| Field | Type | Notes |
|---|---|---|
| `title` | str | BookStack page name |
| `bookstack_page_id` | int | Stable across renames |
| `bookstack_book_id` | int | Configured target book |
| `bookstack_chapter_id` | int \| null | `null` for book-level pages (e.g. overview) |
| `bookstack_chapter` | str \| null | Chapter display name |
| `bookstack_tags` | list[str] | User-added tag *values*. The internal `bookstack_sync = managed` marker is stripped. |
| `ha_object_kind` | str | Parsed from the storage mapping key — `device`, `area`, `automation`, `script`, `scene`, `integration`, `addon`, `overview`, `bundle`, `network`, `mqtt`, `energy`, `helpers`, `bluetooth`, `services`, `recorder` |
| `ha_object_id` | str \| null | UUID for devices/areas; null for chapter-level overview pages |
| `last_synced` | str | ISO timestamp of the last successful sync that wrote this page |
| `tombstoned` | bool | `true` once HA's device-side disappears (BookStack page tagged `bookstack_sync = orphaned`); the manual block is preserved either way |
| `export_version` | str | Schema version, currently `"1"` — bumped on incompatible changes |
| `content_hash` | str | SHA-256 of `frontmatter + body`; used for idempotent re-export |

## Slug rules

Slugs are derived from BookStack page titles using these steps:

1. German umlauts mapped manually: `ä → ae`, `ö → oe`, `ü → ue`,
   `ß → ss` (uppercase variants too).
2. Unicode NFKD normalisation.
3. ASCII-fold: everything non-ASCII is dropped (emojis, CJK, …).
4. Lowercased.
5. `[^a-z0-9]+` → `-`.
6. Leading / trailing `-` trimmed.
7. Truncated to 80 characters.
8. Empty result → `untitled`.

Examples:

| Input | Slug |
|---|---|
| `Wohnzimmer` | `wohnzimmer` |
| `Büro/Wärmesensor 💡` | `buero-waermesensor` |
| `Light` (twice in same folder) | `light.md`, `light-2.md` |

## Idempotency

The export module hashes each rendered file (frontmatter + body) and
stores the hash in `.storage/bookstack_sync.{entry_id}.export`. On every
subsequent run:

- If the hash matches the previous run **and** the target filename
  hasn't changed → file is left untouched, counted as `unchanged`.
- If the hash differs → file is rewritten atomically (temp file +
  `os.replace`).
- If the filename has changed (page renamed in BookStack) → new file is
  written, **old file is deleted**, counted as `deleted_old`.

This means: running the export once a minute is wasteful, but harmless.

## Tombstone behaviour

When a device disappears from HA, ha-bookstack-sync soft-deletes the
BookStack page (auto block replaced with an *orphaned-since* notice; tag
flips from `managed` to `orphaned`). The export keeps these pages — the
filename does **not** change, only `tombstoned: true` appears in the
frontmatter. Reasons:

- The manual block is still there, your notes are still useful
  ("yes, that was the old hallway PIR — replaced with the Aqara P1").
- RAG queries can intentionally surface tombstones ("what was the device
  in the hallway before?") with a `tombstoned: true` filter.
- External indexers don't break: every previously-exported file is still
  at its known path.

If you want a clean folder, delete `<output>/` and re-export — the
ledger in `.storage/` will rebuild from scratch.

## Stack-specific snippets

### LangChain (`ObsidianLoader`)

```python
from langchain_community.document_loaders import ObsidianLoader

loader = ObsidianLoader("/config/bookstack_export")
docs = loader.load()
# docs[i].metadata is the YAML frontmatter
# docs[i].page_content is the auto+manual body
```

### LlamaIndex (`ObsidianReader`)

```python
from llama_index.core import SimpleDirectoryReader
from llama_index.readers.obsidian import ObsidianReader

docs = ObsidianReader("/config/bookstack_export").load_data()
```

### Open WebUI Knowledge Base

1. Open WebUI → Workspace → Knowledge → **+ Create**.
2. Name it (e.g. *Smart Home*).
3. **Upload Directory** → point at `/config/bookstack_export/`.
4. The frontmatter fields appear as metadata — Open WebUI will let you
   filter by `ha_area`, `ha_object_kind`, etc. when querying.

### Filtered Qdrant query (e.g. ground floor only)

```python
from qdrant_client.http.models import Filter, FieldCondition, MatchValue

results = qdrant.search(
    collection_name="smart_home",
    query_vector=embed("Bewegungsmelder"),
    query_filter=Filter(
        must=[
            FieldCondition(
                key="ha_area",
                match=MatchValue(value="Erdgeschoss – Gang"),
            ),
            FieldCondition(
                key="tombstoned",
                match=MatchValue(value=False),
            ),
        ],
    ),
)
```

## Storage location

Per config entry, the export ledger lives at:

```
<HA-config>/.storage/bookstack_sync.<entry_id>.export
```

Same shape and lifecycle as the existing
`bookstack_sync.<entry_id>.mapping` file. Removing it forces a full
re-export on the next run; the BookStack pages and your manual notes
are untouched.
