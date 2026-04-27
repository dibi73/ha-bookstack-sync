# BookStack Sync – Home Assistant Custom Integration

## Projektziel

Eine Home-Assistant-Custom-Integration (installierbar via HACS), die das gesamte Home-Assistant-Setup automatisiert in eine bestehende **BookStack-Wiki-Instanz** dokumentiert und täglich synchronisiert. Manuell hinzugefügte Inhalte im Wiki müssen dabei zuverlässig erhalten bleiben.

## Kontext / Setup des Users

- **BookStack** läuft bereits als Docker-Container auf einer **Synology NAS via Portainer**
- **Home Assistant** läuft produktiv mit Geräten via Zigbee, Matter, MQTT (Tasmota, Shelly), WLAN-IoT
- **Passwörter** werden separat in **Vaultwarden** verwaltet (nicht in BookStack, nicht in dieser Integration)
- **GitHub-User**: `dibi73`
- **Repo**: `https://github.com/dibi73/ha-bookstack-sync` (erstellt via "Use this template" aus `ludeeus/integration_blueprint`)
- **Entwicklungs-Umgebung**: Windows + VS Code (mit Dev Containers Extension geplant)

## Repo-Status

- Blueprint bereits geklont, aber noch nicht umbenannt
- Es existiert ein PowerShell-Rename-Skript (`rename-blueprint.ps1`) das folgende Ersetzungen durchführt:
  - Domain: `integration_blueprint` → `bookstack_sync`
  - Anzeigename: `Integration Blueprint` → `BookStack Sync`
  - Repo-Pfad: `ludeeus/integration_blueprint` → `dibi73/ha-bookstack-sync`
  - Code-Owner: `@ludeeus` → `@dibi73`
  - Ordner-Rename: `custom_components/integration_blueprint/` → `custom_components/bookstack_sync/`

## Funktionale Anforderungen

### Konfiguration (Config-Flow in HA-UI)

Der User soll die Integration komplett über die HA-UI einrichten können:

1. **BookStack Base-URL** (z.B. `https://bookstack.synology.local`)
2. **BookStack API Token ID + Secret** (zwei Felder, BookStack nutzt diese Trennung)
3. **Ziel-Book** in BookStack – per Dropdown via API laden, in das die generierten Pages geschrieben werden
4. **Sync-Intervall** – täglich / stündlich / nur manuell
5. **Filter** (optional, später) – welche Areas oder Integrationen exportiert werden sollen

### Daten, die aus HA gezogen werden

- **Areas** (Räume) – via WebSocket: `config/area_registry/list`
- **Devices** – via WebSocket: `config/device_registry/list` (mit Hersteller, Modell, Firmware, Area-Zuordnung)
- **Entities** – via WebSocket: `config/entity_registry/list` (mit Geräte-/Area-Zuordnung)
- **States** – via REST: `/api/states` (aktuelle Werte und Attribute)
- **Integrationen / Konfig-Entries** – via WebSocket: `config_entries/get`
- **Automatisierungen, Skripte, Szenen** – aus den entsprechenden Storage-Bereichen oder YAML-Files
- **Add-ons** (falls Supervisor verfügbar) – via Supervisor-API: `/api/hassio/addons`

Da das Code als HA-Integration läuft, hat sie nativen Zugriff auf die Registries ohne API-Umweg – das ist eleganter als REST-Calls und sollte bevorzugt werden, wo möglich.

### Output: Struktur in BookStack

Pro Synchronisation werden generiert:

- **Übersichts-Page**: Statistiken (Anzahl Geräte, Entities, Automationen pro Integration), Inhaltsverzeichnis, Zeitstempel des letzten Syncs
- **Eine Page pro Raum/Area**: Liste aller Geräte in diesem Raum mit Entities
- **Eine Page pro Gerät**: Hersteller, Modell, Firmware, Integration, alle zugehörigen Entities mit aktuellem State, MQTT-Topic (falls vorhanden)
- **Eine Page pro Automation/Skript** (optional, könnte auch als Liste gebündelt werden)

Die genaue Aufteilung sollte in einem frühen Design-Schritt mit dem User abgestimmt werden, nicht hartkodiert.

## Kritische Design-Anforderung: Schutz manueller Inhalte

**Wichtigste Anforderung**: Inhalte, die der User manuell in BookStack zu einer Page hinzugefügt hat, dürfen vom Sync **niemals überschrieben werden**. Beispiel: zur Auto-generierten Shelly-Page fügt der User Notizen hinzu wie "Spezialkonfig: Custom-Trigger für Doppelklick weil ..." – diese Notizen müssen Sync-fest sein.

### Empfohlene Strategie: Marker-Blöcke + Hash-Verifikation

Jede generierte Page hat klar abgegrenzte Bereiche:

```markdown
<!-- BEGIN AUTO-GENERATED -->
... von der Integration generiert ...
<!-- END AUTO-GENERATED -->

<!-- BEGIN MANUAL -->
... vom User gepflegt, wird nie angefasst ...
<!-- END MANUAL -->
```

**Sync-Algorithmus**:
1. Existierende Page von BookStack holen
2. `MANUAL`-Block extrahieren (mit Regex auf die Marker)
3. Neuen `AUTO`-Block aus aktuellen HA-Daten generieren
4. Beide Blöcke zusammenfügen und zurückschreiben
5. Hash des zuletzt generierten `AUTO`-Blocks lokal speichern
6. Bei nächstem Sync: wenn aktueller `AUTO`-Block-Hash NICHT zum gespeicherten passt (also: jemand hat im Auto-Block manuell editiert), Konflikt loggen statt überschreiben

### Page-Identität / Mapping

- Geräte in HA haben stabile UUIDs
- Eine Mapping-Tabelle `HA-Device-ID ↔ BookStack-Page-ID` muss persistiert werden (HA-Storage: `.storage/bookstack_sync.mapping`)
- Ohne dieses Mapping würden bei Umbenennungen oder Wiederholtem Sync Duplikate entstehen

### Soft-Delete

Wenn ein Gerät aus HA verschwindet (Integration entfernt, Gerät getauscht):
- Page **nicht** löschen
- Auto-Block überschreiben mit Warnhinweis "Dieses Gerät existiert nicht mehr in HA seit YYYY-MM-DD"
- Manueller Block bleibt unangetastet
- User entscheidet selbst, ob er die Page löscht

## Weitere wichtige Design-Punkte

### Idempotenz

- Renderer muss **deterministisch** sein (keine zufällige Reihenfolge in Dictionaries, sortierte Listen)
- BookStack speichert jede Änderung als Revision – wenn der Output bei gleichem Input nicht byte-identisch ist, entstehen jeden Sync neue Revisionen ohne echte Änderung
- Hash-Vergleich vor jedem Schreiben: nur Pages anfassen, deren Auto-Block-Hash sich tatsächlich geändert hat

### Rate-Limiting / Performance

- BookStack-API ist nicht für massenhafte parallele Calls ausgelegt
- Bei vielen Geräten: Batching mit Pausen zwischen Calls
- Pages, die sich nicht geändert haben, gar nicht erst anfassen

### Dry-Run-Modus

- Service `bookstack_sync.preview` der nur ins HA-Log schreibt, was passieren *würde*, aber nichts tatsächlich verändert
- Nützlich beim ersten Setup und nach Code-Änderungen

### Manuelle Triggerung

- Service `bookstack_sync.run_now` für Sofort-Sync ohne auf Schedule zu warten
- Sinnvoll für "neues Gerät hinzugefügt → sofort dokumentieren"

## Infos, die kein Script aus HA ziehen kann

Bewusst akzeptieren: Folgendes ist **nicht** automatisch dokumentierbar und gehört in den `MANUAL`-Block:

- "Warum" hinter Spezialkonfigurationen (z.B. warum ein bestimmtes Tasmota-`SetOption` gesetzt ist)
- Bekannte Macken / Quirks von Geräten
- Cross-Referenzen wie "Passwort siehe Vaultwarden-Eintrag XY"
- Tasmota-`Backlog`-Strings als Backup
- Shelly-`/settings`-Dump als Backup

Ein Tipp aus der HA-Community, der hier eingebaut werden sollte: Das `description`-Feld in Automatisierungen und Notes-Felder bei Helpers können automatisch in den Auto-Block übernommen werden – das gibt dem User einen Anreiz, "Warum"-Begründungen direkt in HA zu pflegen, statt im Wiki.

## Empfohlener Entwicklungs-Approach

Vor dem Code:

1. **Datenmodell als Markdown-Doc** im Repo definieren (welche Felder pro Page, welche Templates, welche Page-Hierarchie)
2. **Architektur-Entscheidungen** als ADRs (Architecture Decision Records) festhalten – v.a. die Marker-Strategie und das Mapping-Konzept

Code-Reihenfolge:

1. **BookStack-Client** als eigenständige Klasse (mit pytest-Tests, kann gegen lokale BookStack-Instanz getestet werden)
2. **Markdown-Renderer** mit Jinja2-Templates (deterministisch, gut testbar)
3. **HA-Datenextraktion** (Registries lesen)
4. **Merge-Logik** (Marker-Blöcke parsen, kombinieren, Hash prüfen)
5. **Config-Flow** (UI für Setup)
6. **Coordinator + Scheduler** (täglicher Sync)
7. **Services** (`run_now`, `preview`)

Realistische Aufwandsschätzung: **4–8 Wochen Abend-Arbeit** für eine V1, die wirklich rund läuft. Nicht unterschätzen: HA-spezifische Patterns (async/await, DataUpdateCoordinator, Config-Flow-Schemas) sind nicht intuitiv und nur teilweise gut dokumentiert.

## Existierende Lösungen (Recherche-Stand April 2026)

- Es existiert ein BookStack-**Add-on** für HA (`hassio-addons/addon-bookstack`) – das ist BookStack als Service neben HA, **nicht** ein Sync-Tool
- Eine HA→BookStack-Sync-Integration ist meines Wissens **noch nicht** vorhanden
- Feature-Request "Export devices and entities" auf der HA-Community ist seit 2020 offen, ohne offizielle Umsetzung
- Damit wäre dieses Projekt potenziell ein nützlicher Beitrag für die Community (HACS-Publishing als V2-Ziel)

## Nicht-Ziele (bewusste Abgrenzung)

- **Keine Passwort-Verwaltung** in BookStack oder dieser Integration – Vaultwarden bleibt strikt getrennt
- **Kein bidirektionaler Sync** – Daten fließen nur HA → BookStack, niemals zurück
- **Kein Edit-Konflikt-Resolver** – bei erkannten Konflikten wird gelogged, der User löst manuell auf
- **Keine eigene UI** außerhalb des Standard-HA-Config-Flows
- **Kein Frontend-Custom-Card** in V1
