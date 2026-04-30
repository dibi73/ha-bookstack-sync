# HACS-default Submission — Cheat Sheet

Schritte zum Submitten von `dibi73/ha-bookstack-sync` an
[`hacs/default`](https://github.com/hacs/default).

## Voraussetzungen (alle erfüllt — Stand v0.8.2)

- ✅ Hassfest validation grün
- ✅ HACS validation grün
- ✅ Quality scale: gold (manifest.json)
- ✅ Public Repo mit Description + Topics
- ✅ Tagged release auf GitHub
- ✅ `custom_components/bookstack_sync/brand/icon.png` (256×256, transparent)
- ✅ `custom_components/bookstack_sync/brand/icon@2x.png` (512×512)
- ⚪ `logo.png` ist optional und nicht vorhanden — OK so

Seit HA 2026.3 ist **kein PR an `home-assistant/brands`** mehr nötig
(custom integrations dürfen brand assets im eigenen Repo unter
`brand/` liefern, und `home-assistant/brands` lehnt PRs für custom
integrations sowieso ab).

## Schritt-für-Schritt

### 1. Fork

`https://github.com/hacs/default` → Fork-Button. Empfangener Fork:
`https://github.com/dibi73/default` (Annahme).

### 2. File editieren

Im Fork: `integration` (Datei im Repo-Root, ohne Endung — JSON-Array
mit einem Eintrag pro Zeile).

Insert in **alphabetischer Reihenfolge** zwischen `dib0/...` und
`diego7marques/...`:

```diff
   "dib0/ha-elro-connects-realtime",
+  "dibi73/ha-bookstack-sync",
   "diego7marques/ha-aws-cost",
```

Über die GitHub-Web-UI (Edit-Pencil auf der `integration`-Datei) ist
das ein 30-Sekunden-Edit.

### 3. Commit + PR

Commit-Message: `Add dibi73/ha-bookstack-sync` (lokale-Branch-Variante
oder via Web-UI direkt auf `master` des Forks).

PR-Body (kopierbar):

```markdown
Add `dibi73/ha-bookstack-sync` — a Home Assistant custom integration
that documents the entire HA setup as markdown pages inside an
existing BookStack wiki and keeps it in sync.

- Repo: https://github.com/dibi73/ha-bookstack-sync
- Latest release: https://github.com/dibi73/ha-bookstack-sync/releases/latest
- Quality scale: gold (manifest)
- Hassfest + HACS validation grün auf main
- Brand image local at `custom_components/bookstack_sync/brand/icon.png`
- 100+ tests covering merge logic, renderer determinism, API client,
  config flow, coordinator, sync orchestrator
- Available since v0.1; current v0.8.2

This fills a long-standing community need
(see https://community.home-assistant.io/t/feature-request-export-devices-and-entities/)
for a structured, persistent, manually-extendable HA documentation
that survives manual user edits via marker-block protection with
SHA-256 tampering detection.
```

### 4. Bot-Validation

Nach Open des PRs läuft automatisch der HACS-Action-Bot. Er prüft:
- hassfest auf neuestem main-Tag
- HACS-Validation
- Brand-Image (lokal oder im brands-Repo)
- Versionierung
- Repo-Description + Topics

Falls red: Bot kommentiert mit konkreten Fehlern, fixen, push, Bot
re-runs automatisch.

### 5. Human-Review

Nach Bot-grün geht der PR in die Human-Review-Queue der
HACS-Maintainers. Dauert typisch Tage bis Wochen.

### 6. Nach Merge

User-Update für unser eigenes README:
- "Custom Repository hinzufügen"-Anleitung kann raus
- Stattdessen "In HACS nach BookStack Sync suchen"-Anleitung rein

## Status-Tracking

Issue: https://github.com/dibi73/ha-bookstack-sync/issues/17
