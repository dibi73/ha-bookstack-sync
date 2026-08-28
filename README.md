# BookStack Sync for Home Assistant

> Available in: **English** · [Deutsch](README.de.md)
>
> *(The integration's HA UI itself is localised in 28 languages since v0.12.0 — this README exists in DE + EN.)*

A Home Assistant custom integration (installable via HACS) that
documents your entire HA setup as markdown pages inside an existing
[BookStack](https://www.bookstackapp.com/) wiki book and keeps it in
sync.

The killer feature: **manually added wiki content stays preserved
across syncs.** Every page is split into an auto-generated section and
a manual section by markdown markers. The integration only ever
rewrites the auto block — your notes, quirks, password references and
"why we set option X" comments live in the manual block forever.

## What gets documented

Pages are organised into chapters inside your target book:

- **Overview** — pure navigation, links to every other page (no
  stats/aggregates — those live on the pages they describe)
- **Areas** chapter — one page per area listing all devices and
  entities it contains
- **Devices** chapter — one page per physical device with manufacturer,
  model, firmware version, configured integrations, network info, and
  every entity including current state and (for MQTT devices) the
  topic. Devices split across multiple integrations by Home Assistant
  (since HA 2026.8) are automatically merged into a single page — see
  "Also known as" on the device page for the individual registry
  entries that got folded together
- **Labels** chapter — one page per HA label, listing every device
  that carries it (directly or via one of its entities)
- **Integrations**, **Automations**, **Scripts**, **Scenes** — one
  bundled page each, listing every entry with description, mode, last
  triggered etc.
- **Network** — table of every device with network data, plus a UniFi
  topology tree and a DHCP-reservation export block, when applicable
- **Bluetooth** — table of every BT-tracked device with its current
  status (reachable / unreachable) and when it was last active, sorted
  most-recently-active first
- **Recorder**, **Energy**, **MQTT topics**, **Helpers** — one page
  each, when the corresponding HA feature is configured
- **Backup** — last successful/attempted backup, plus a table of every
  stored backup with its target(s) and size per target
- **Add-ons** — Supervisor add-on listing (only on HassOS / Supervised)

Output language follows your HA UI language by default (German and
English supported); you can override it in the options flow.

**The network topology tree is UniFi-specific.** The ASCII tree on the
Network page (Gateway → Switch → Access Points → Clients) only works
with Ubiquiti/UniFi hardware via HA's `unifi` integration — both the
device-role detection and the Switch↔Gateway/AP↔Switch wiring come from
UniFi-specific data fields that other vendor integrations (FritzBox,
TP-Link Omada, MikroTik, Cisco Meraki, …) don't expose in the same
shape. With other hardware, the Network page still shows the flat
device table with IP/MAC/connection info — just without the topology
tree.

**Wired (LAN) clients don't nest under the Switch, even with UniFi.**
HA's `unifi` integration reports the access point a *wireless* client
is on (`ap_mac`), so WLAN devices correctly show up nested under their
AP. It does not expose an equivalent attribute for which switch port a
*wired* client is plugged into, so wired clients can't be placed under
the Switch node — this is a data gap in HA's `unifi` integration
itself, not something this integration can work around. Wired devices
still show up correctly everywhere else (their own device page, the
flat Network table, DHCP export). Reported upstream:
[home-assistant/core#180499](https://github.com/home-assistant/core/issues/180499).

**Bluetooth peripherals can't be attributed to a specific proxy.**
HA's `via_device_id` for a Bluetooth-connected device only ever links
a scanner/adapter to the physical host it runs on — it never links a
discovered BLE peripheral to the proxy that heard it. This is
architectural: a BLE device can be in range of several proxies at
once, so there's no single-parent concept for it, unlike WiFi/AP
association. So the Bluetooth page doesn't group by scanner at all —
just a status (reachable/unreachable) and a last-active timestamp per
device. An early version of this page instead split devices into a
binary "seen" vs. "should be there, but not found" — that turned out
to be actively misleading: a passive BLE sensor is normally
`unavailable` for anywhere from seconds to tens of minutes after any
HA restart while its proxy reconnects, which isn't the same as the
device actually being gone. A routine restart made the whole page
look like every device had vanished. The plain status + timestamp
avoids that false alarm and lets you judge for yourself.

## Why use it

- **Self-documenting smart home**. Every device, area, automation
  always present in your wiki. Always current.
- **Survives manual edits**. Add cross-references, quirks, "why" notes
  to any page — they stay through future syncs. Hash-based tampering
  detection logs (and skips) any page where the auto block was edited
  outside of HA.
- **Idempotent**. Same HA state → byte-identical markdown → no
  spurious BookStack revisions.
- **Soft-delete**. When a device disappears from HA, its page is not
  deleted. Instead the auto block is replaced with an "orphaned —
  device gone since YYYY-MM-DD" notice; the manual block stays.
- **Survives BookStack restarts and HA migrations**. Mapping between
  HA-IDs and BookStack page IDs is persisted in HA's storage.

## Status

Production-ready for personal use. **V0.16** as of this README,
targeting the HA Quality Scale **Platinum** tier:

- Full HA-data extraction (areas, devices, entities, automations,
  scripts, scenes, integrations, add-ons, network, Bluetooth, recorder,
  energy, MQTT, helpers, backups, labels)
- Device-group deduplication for devices split across multiple
  integrations (HA 2026.8+)
- Marker-block merge with hash-based tampering detection
- Multi-pass overview render with internal page links
- Status sensor, persistent notifications, structured services
- Reauth flow + user-initiated reconfigure flow (URL / token / TLS)
- Diagnostics endpoint (redacted dump for bug reports)
- TLS-verify toggle, MQTT-topic display, UI localised in 28 languages
- Admin-only services (`run_now`, `preview`, `export_markdown`)
- 260+ tests covering merge logic, renderer determinism, API client,
  config flow, coordinator, sync orchestrator

### Quality Scale

Self-declared (`manifest.json`), since Hassfest doesn't formally
validate Gold/Platinum rules for custom integrations:

- ✅ **Bronze / Silver**: config flow, unique IDs, runtime-data storage,
  reauth flow, integration owner, log-when-unavailable, test coverage
- ✅ **Gold**: diagnostics, reconfigure flow, entity categories, dynamic
  devices, repair issues (tampering / marker loss / unreachable target,
  each with a `translation_key`), translated runtime exceptions, full
  docs sections, UI in 28 locales
- ⚪ **`stale-devices`**: intentionally not applicable — this
  integration owns one synthetic HA device per config entry (never
  stale); the actual tracked "source devices" live as BookStack pages,
  which already get soft-deleted (tombstoned) when their HA object
  disappears. That's the rule's intent, just not what it literally
  checks.
- ✅ **Platinum**: `strict-typing` (`py.typed` + a `mypy --strict` CI
  gate, since v0.16.2), `inject-websession` (always uses HA's own
  `async_get_clientsession`/`async_create_clientsession`, never a
  self-rolled session), `async-dependency` (N/A — `requirements: []`,
  no external PyPI dependency to check)

## Installation

### Via HACS (recommended)

1. HACS → top-right **⋮** → **Custom repositories**
2. **Repository**: `https://github.com/dibi73/ha-bookstack-sync`
3. **Type**: `Integration`
4. Click **Add**, then **Download** on the BookStack Sync card
5. Restart Home Assistant
6. **Settings → Devices & Services → Add Integration → "BookStack Sync"**

### Manual install

Copy `custom_components/bookstack_sync/` from this repo into your HA
`config/custom_components/` directory, then restart HA and add the
integration via the UI.

## Configuration

The config flow asks two screens of questions:

**Step 1 — Connection**
- **BookStack URL**: e.g. `https://bookstack.example.com` or
  `http://192.168.0.11:6875`
- **API Token ID + Secret**: create in BookStack under
  *My Profile → API Tokens*. The token needs read+write on the target
  book.
- **Verify TLS certificate**: leave checked unless you use a
  self-signed cert (common on Synology / NAS setups).

**Step 2 — Target**
- Pick the book to sync into (dropdown of all readable books)
- Sync interval: hourly / daily / manual only

After setup the **Options** dialog (gear icon on the integration card)
adds:
- Excluded areas (multi-select; their devices skip the wiki entirely)
- Output language (`Auto` follows HA, or pick `German` / `English`
  explicitly)

## Page structure with marker blocks

Every page the integration writes follows this shape:

```markdown
<!-- BEGIN AUTO-GENERATED -->
... regenerated by the integration on every sync ...
<!-- END AUTO-GENERATED -->

<!-- BEGIN MANUAL -->
Your notes, quirks, cross-references — never overwritten.
<!-- END MANUAL -->
```

Stay inside the **MANUAL** block when editing in BookStack. The
integration computes a SHA-256 hash of the auto block on every write
and compares it to what it last wrote — if anything changed
unexpectedly (e.g. someone edited inside the auto block), the page is
skipped with a warning rather than clobbered.

## Services

- **`bookstack_sync.run_now`** — kick off a sync immediately. Useful
  after adding a new device.
- **`bookstack_sync.preview`** — dry run. Logs to the HA log what
  would be created / updated, but writes nothing to BookStack.
- **`bookstack_sync.export_markdown`** — opt-in: write every managed
  BookStack page back to a folder of plain Markdown files for use as
  RAG / LLM input. **Disabled by default** — see *Markdown export for
  RAG* below.

All three available from *Developer Tools → Actions* or via automations.

## Markdown export for RAG (opt-in)

Since v0.13.0 the integration can also write the merged content (auto
block + your manual notes) back to a folder of plain Markdown files
with YAML frontmatter — the universal input format for RAG / LLM
pipelines (LangChain `ObsidianLoader`, LlamaIndex `ObsidianReader`,
Open WebUI Knowledge Base, …).

> **Default off.** The export costs disk space and CPU on every run,
> and the BookStack pages on their own already serve most users. Turn
> it on consciously when you actually want a separate Markdown copy
> for an external indexer. The switch lives in the integration's
> **Configure** dialog under *Markdown-Export aktivieren*.

When enabled, a flat folder structure is produced (default
`<config>/bookstack_export/`):

```
bookstack_export/
├── _index.md                    ← list of every exported page
├── devices/
│   ├── light-living-room.md
│   └── ...
├── areas/
│   └── living-room.md
└── automations/
    └── away-mode.md
```

Each file looks like:

```markdown
---
title: Bewegungsmelder Gang
bookstack_page_id: 142
bookstack_book_id: 1
bookstack_chapter: Devices
bookstack_tags: [zigbee, sicherheit]
ha_object_kind: device
ha_object_id: a1b2c3d4
last_synced: "2026-05-01T03:00:00+00:00"
tombstoned: false
content_hash: 7f3a...
---

[auto block — manufacturer, model, firmware, entity list, current
states, MQTT topic, …]

---

[your manual notes — preserved verbatim from BookStack]
```

Trigger:

Once `export_enabled` is on, every successful sync also writes the
Markdown files — no automation needed. The
`bookstack_sync.export_markdown` service stays available for ad-hoc
triggers (e.g. „force a fresh export now").

```yaml
# Optional: trigger an extra export at a specific time.
automation:
  - alias: BookStack export at 03:30
    trigger:
      - platform: time
        at: "03:30:00"
    action:
      - service: bookstack_sync.export_markdown
```

Full schema and stack-specific snippets in
[docs/EXPORT.md](docs/EXPORT.md).

## Status sensor

Each configured BookStack instance gets a sensor:

- **State**: `ok` / `error` / `never_run` / `syncing`
- **Attributes**: `last_run`, `created`, `updated`, `unchanged`,
  `tombstoned`, `skipped_conflict`, `errors`, `total_pages`

Drop it on a dashboard or feed it into automations.

## Use cases

- **House-handover dossier**: when you sell a house or hand it to a
  caretaker, the wiki already lists every smart device, every area
  assignment, every automation — pdf-export the book and you have a
  printable manual.
- **"Why is this device offline" forensics**: open the device's wiki
  page, see the manufacturer / model / firmware *and* your manual notes
  ("replaced battery 2024-10", "needs zigbee re-pairing after router
  reboot") next to each other.
- **Onboarding a partner / family member**: the Areas chapter tells
  them which lights belong to which room, the Automations page tells
  them what runs at sunset, the manual block under each page is where
  you explain the intent.
- **Migration prep**: before flashing a new HA box, the wiki is your
  out-of-band record of which integrations exist, what they're called,
  and which entities they own — survives a config restore gone wrong.

## Examples

**Trigger a sync from a button card:**

```yaml
type: button
name: Sync wiki
tap_action:
  action: call-service
  service: bookstack_sync.run_now
```

**Daily sync at 03:00 instead of the built-in interval:**

```yaml
automation:
  - alias: BookStack daily sync
    trigger:
      - platform: time
        at: "03:00:00"
    action:
      - service: bookstack_sync.run_now
```

(Set the integration's interval to `manual` first.)

**Notify on sync errors:**

```yaml
automation:
  - alias: BookStack sync error
    trigger:
      - platform: state
        entity_id: sensor.bookstack_sync_status
        to: "error"
    action:
      - service: notify.mobile_app_my_phone
        data:
          message: >
            BookStack sync failed:
            {{ state_attr('sensor.bookstack_sync_status', 'errors') }}
```

## Troubleshooting

**"BookStack rejected the API token"** — re-create the token in
BookStack (*My Profile → API Tokens*), make sure it has read+write on
the target book. The integration will surface a reauth card on the
Devices & Services page; click it, paste the new ID + secret, done.

**"BookStack unreachable"** — usually one of: wrong URL (forgot the
port?), TLS verify on against a self-signed cert (toggle it off in
*Configure*), reverse proxy returning 502 mid-sync (the integration
retries transient errors three times with exponential backoff — if it
still fails, the next sync will pick up).

**"AUTO block was edited outside of Home Assistant"** — somebody
edited the auto section in BookStack. The integration *skips* that
page rather than clobbering the edit. Either undo the edit in
BookStack or move the content into the manual block, then re-sync.

**Persistent notification "X errors"** — open the integration's
Diagnostics dump (gear icon → *Download diagnostics*) and attach it to
a GitHub issue. The dump redacts the URL + token automatically.

**Pages stuck at book level instead of in their chapter** — known
finding from v0.1.x; fixed in v0.4.0. If you upgraded, the next sync
moves them to the right chapter automatically.

## Known limitations

- **⚠ Edit pages in the markdown editor only — never WYSIWYG.**
  BookStack's TinyMCE-based WYSIWYG editor round-trips Markdown
  through HTML and silently drops HTML-comment markers
  (`<!-- BEGIN AUTO-GENERATED -->` etc.). Once that happens, the
  integration can no longer tell which part of the page is yours and
  which is auto-generated. Since v0.14.9 the integration detects this
  and refuses to overwrite affected pages — you'll see a *Marker-Kommentare
  einer Page fehlen* repair issue in HA. Recovery: open the page in
  the markdown editor, save your manual notes elsewhere, and re-run
  *Sync now* with *Force overwrite tampered pages* enabled to recreate
  the page with fresh markers. The integration also pins
  `editor: "markdown"` on every write to deter the WYSIWYG toggle, but
  BookStack treats that field as advisory in older versions.
- **No bidirectional sync.** Edits in BookStack outside the manual
  block are detected, logged, and the page is skipped — not merged
  back into HA.
- **Sync is HA-state-driven.** Renaming an area or device renames the
  page on next sync; the old page becomes orphan and gets a tombstone
  banner. Manual cleanup of tombstoned pages is left to the user.
- **Page-output languages: DE + EN only.** The integration UI itself
  is localised in 28 languages (since v0.12.0), but the *content*
  written into BookStack pages is German or English. Adding a content
  language is a matter of populating `_strings.py`; PRs welcome.
- **API token has full book-level access.** BookStack does not offer
  per-page tokens; the integration uses whatever the token can reach.

> *Multiple BookStack books / multiple BookStack instances **are**
> supported* — add the integration once per target. Each config entry
> is keyed by base URL and gets its own coordinator, storage and
> status sensor.

## Non-goals

- **No password storage** in BookStack — keep credentials in a proper
  password manager (Vaultwarden / Bitwarden / 1Password). The
  integration intentionally never writes credentials anywhere.
- **No bidirectional sync** — data flows HA → BookStack only.
- **No automatic conflict resolution** — manual edits inside the auto
  block are detected and logged, but the user resolves them.

## Development

The repo is set up around the
[ludeeus/integration_blueprint](https://github.com/ludeeus/integration_blueprint)
devcontainer:

```bash
scripts/develop      # starts HA against ./config with this integration
scripts/lint         # ruff check + format
pytest tests/        # full test suite
```

CI runs hassfest, HACS validation, ruff and pytest on every push and PR.

## License

MIT — see [LICENSE](LICENSE).
