# BookStack Sync für Home Assistant

> Verfügbar in: **Deutsch** · [English](README.md)
>
> *(Die HA-UI der Integration selbst ist seit v0.12.0 in 28 Sprachen lokalisiert — diese README gibt es in DE + EN.)*

Eine Home-Assistant-Custom-Integration, die dein gesamtes HA-Setup automatisch in
ein bestehendes Book deiner [BookStack](https://www.bookstackapp.com/)-Wiki-Instanz
synchronisiert. Manuell hinzugefügte Inhalte in den Wiki-Pages bleiben dabei
zuverlässig erhalten.

## Status

Produktionsreif für den persönlichen Gebrauch. **V0.16** zum Stand dieser
README, mit Zielrichtung HA Quality Scale **Platinum**:

- Vollständige HA-Datenextraktion (Areas, Devices, Entities, Automationen,
  Skripte, Szenen, Integrationen, Add-ons, Netzwerk, Bluetooth, Recorder,
  Energie, MQTT, Helpers, Backups, Labels)
- Geräte-Deduplizierung für Geräte, die von mehreren Integrationen parallel
  angelegt werden (HA 2026.8+)
- Marker-Block-Merge mit Hash-basierter Tampering-Erkennung
- Mehrstufiges Overview-Rendering mit internen Cross-Links
- Status-Sensor, Persistent Notifications, strukturierte Services
- Reauth-Flow + User-initiierter Reconfigure-Flow (URL / Token / TLS)
- Diagnostics-Endpoint (redaktierter Dump für Bug-Reports)
- TLS-Verify-Toggle, MQTT-Topic-Anzeige, UI in 28 Sprachen lokalisiert
- Admin-only Services (`run_now`, `preview`, `export_markdown`)
- 260+ Tests für Merge-Logik, Renderer-Determinismus, API-Client,
  Config-Flow, Coordinator, Sync-Orchestrator

### Quality Scale

Selbst-deklariert (`manifest.json`), da Hassfest Gold/Platinum-Regeln für
Custom-Integrationen nicht formal validiert:

- ✅ **Bronze / Silver**: Config-Flow, Unique-IDs, Runtime-Data-Storage,
  Reauth-Flow, Integration-Owner, Log-when-unavailable, Test-Coverage
- ✅ **Gold**: Diagnostics, Reconfigure-Flow, Entity-Categories, Dynamic
  Devices, Repair-Issues (Tampering / Marker-Verlust / Unreachable-Ziel,
  jeweils mit `translation_key`), übersetzte Laufzeit-Exceptions,
  vollständige Doku-Abschnitte, UI in 28 Locales
- ⚪ **`stale-devices`**: bewusst nicht anwendbar — die Integration besitzt
  ein synthetisches HA-Device pro Config-Entry (wird nie stale); die
  eigentlich getrackten "Quell-Devices" leben als BookStack-Pages und
  werden bereits weich gelöscht (tombstoned), sobald ihr HA-Objekt
  verschwindet. Das ist der Sinn der Regel, nur nicht was sie wörtlich prüft.
- ✅ **Platinum**: `strict-typing` (`py.typed` + `mypy --strict`-CI-Gate,
  seit v0.16.2), `inject-websession` (nutzt durchgehend HAs eigene
  `async_get_clientsession`/`async_create_clientsession`, nie eine
  selbstgebaute Session), `async-dependency` (N/A — `requirements: []`,
  keine externe PyPI-Abhängigkeit zu prüfen)

## Funktionsumfang

- **Daten aus HA**: Areas, Devices, Entities, Automationen, Skripte, Szenen,
  Integrationen, Add-ons, Netzwerk-/Bluetooth-Topologie, Recorder- und
  Energie-Konfiguration, MQTT-Topics, Helpers und Backups werden über die
  HA-Registries und HAs eigene Manager-APIs gelesen.
- **Pages in BookStack**:
  - eine reine Navigations-Übersichtsseite
  - eine Page pro Area
  - eine Page pro physischem Device (über mehrere Integrationen gemergt,
    falls HA dasselbe Gerät mehrfach anlegt — siehe "Auch bekannt als"
    auf der Device-Page)
  - eine Page pro HA-Label
  - Bundle-Pages für Automationen, Skripte, Szenen, Integrationen, Add-ons,
    Netzwerk, Bluetooth, Recorder, Energie, MQTT, Helpers, Backup
- **Netzwerk-Topologie-Baum ist UniFi-spezifisch**: der ASCII-Baum auf der
  Netzwerk-Seite (Gateway → Switch → Access Points → Clients) funktioniert
  nur mit Ubiquiti/UniFi-Hardware über HAs `unifi`-Integration — sowohl die
  Geräterollen-Erkennung als auch die Switch↔Gateway-/AP↔Switch-Verkabelung
  stammen aus UniFi-spezifischen Datenfeldern, die andere Hersteller-
  Integrationen (FritzBox, TP-Link Omada, MikroTik, Cisco Meraki, …) nicht
  in gleicher Form bereitstellen. Bei anderen Herstellern zeigt die
  Netzwerk-Seite weiterhin die flache Geräte-Tabelle mit IP/MAC/Verbindung,
  nur eben ohne Topologie-Baum.
- **Kabelgebundene (LAN-)Geräte hängen sich nicht unter den Switch, auch
  nicht bei UniFi**: HAs `unifi`-Integration meldet, an welchem Access Point
  ein *WLAN*-Client hängt (`ap_mac`) — WLAN-Geräte erscheinen deshalb korrekt
  unter ihrem AP. Ein entsprechendes Attribut für den Switch-Port eines
  *kabelgebundenen* Clients liefert sie aber nicht — das ist eine
  Datenlücke in HAs `unifi`-Integration selbst, die sich nicht umgehen
  lässt. Kabelgebundene Geräte tauchen trotzdem überall sonst korrekt auf
  (eigene Device-Page, flache Netzwerk-Tabelle, DHCP-Export). Upstream
  gemeldet: [home-assistant/core#180499](https://github.com/home-assistant/core/issues/180499).
- **Bluetooth-Peripheriegeräte lassen sich ebenfalls keinem bestimmten
  Proxy zuordnen**: Der Bluetooth-Baum gruppiert Scanner (lokaler
  HA-Adapter + ESPHome-BT-Proxies) und die von ihnen gehörten Geräte —
  HAs `via_device_id` bei einem Bluetooth-verbundenen Gerät verknüpft
  aber ausschließlich einen Scanner/Adapter mit seinem physischen Host,
  niemals ein entdecktes BLE-Peripheriegerät mit dem Proxy, der es
  gehört hat. Das ist architekturbedingt: Ein BLE-Gerät kann von
  mehreren Proxies gleichzeitig empfangen werden, es gibt also anders
  als bei WLAN/AP-Zuordnung kein Eltern-Kind-Konzept dafür. Deshalb
  erscheint jedes echte Peripheriegerät (Sensoren, Beacons etc.)
  unter "local", unabhängig davon, welcher ESPHome-Proxy es tatsächlich
  erkannt hat.
- **Schutz manueller Inhalte**: jede Page hat zwei Marker-Blöcke –
  `<!-- BEGIN AUTO-GENERATED -->` und `<!-- BEGIN MANUAL -->`. Nur der
  Auto-Block wird vom Sync angefasst. Wenn der Auto-Block manuell editiert
  wurde (Hash-Check), überspringt der Sync die Page mit Warnung.
- **Idempotenter Renderer**: identischer HA-State → byte-identische Markdown-
  Ausgabe → keine BookStack-Revisionen ohne echte Änderung.
- **Mapping-Persistenz**: Zuordnung HA-ID ↔ BookStack-Page-ID liegt in
  `.storage/bookstack_sync.<entry_id>.mapping`.
- **Services**:
  - `bookstack_sync.run_now` – sofortiger Sync
  - `bookstack_sync.preview` – Dry-Run, schreibt nichts und loggt nur
  - `bookstack_sync.export_markdown` – Opt-in: schreibt jede gemanagte
    BookStack-Page zusätzlich als Markdown-Datei mit YAML-Frontmatter in
    einen Ordner (z. B. als RAG/LLM-Input). **Standardmäßig deaktiviert**
    — siehe Abschnitt *Markdown-Export für RAG* weiter unten.

## Markdown-Export für RAG (Opt-in, seit v0.13.0)

Die Integration kann den vereinten Inhalt (AUTO-Block + deine MANUAL-
Notizen) zusätzlich als reine Markdown-Dateien mit YAML-Frontmatter in
einen Ordner zurückschreiben — universal für RAG/LLM-Pipelines wie
LangChain `ObsidianLoader`, LlamaIndex `ObsidianReader`, Open WebUI
Knowledge Base etc.

> **Standardmäßig aus.** Der Export verbraucht Speicherplatz und CPU bei
> jedem Lauf. BookStack allein deckt die meisten Use-Cases ab — die
> separate Markdown-Kopie ist nur sinnvoll, wenn du tatsächlich einen
> nachgelagerten RAG-Indexer fütterst. Bewusst aktivieren unter
> *Konfigurieren → Markdown-Export aktivieren*.

Vollständige Spezifikation: [docs/EXPORT.md](docs/EXPORT.md).

## Installation (HACS)

1. In HACS → *Custom repositories* dieses Repo hinzufügen (Kategorie
   *Integration*).
2. *BookStack Sync* installieren.
3. Home Assistant neu starten.
4. *Einstellungen → Geräte & Dienste → Integration hinzufügen* → "BookStack Sync".

## Konfiguration

Im Config-Flow werden zwei Schritte durchlaufen:

1. **Verbindung**: BookStack-URL plus API-Token-ID + Secret. Das Token legst du
   in BookStack unter *My Profile → API Tokens* an. Es muss Lese- und
   Schreibrechte auf das Ziel-Book haben.
2. **Ziel**: Auswahl des Books, in das synchronisiert wird, sowie das
   Sync-Intervall (stündlich / täglich / nur manuell).

Spätere Anpassungen (anderes Book, anderes Intervall) gehen über
*Konfigurieren* in der Integrationskachel.

## Manuelle Notizen pflegen

Pro Page sieht der gemerge­te Markdown so aus:

```markdown
<!-- BEGIN AUTO-GENERATED -->
... wird bei jedem Sync neu generiert ...
<!-- END AUTO-GENERATED -->

<!-- BEGIN MANUAL -->
Hier kannst du Notizen, Quirks oder Cross-Refs zu Vaultwarden eintragen.
Diese Sektion wird vom Sync nicht angefasst.
<!-- END MANUAL -->
```

Solange du nur **innerhalb** des MANUAL-Blocks editierst, bleibt alles erhalten.
Editierst du im AUTO-Block, erkennt der Sync das beim nächsten Lauf am Hash
und überspringt die Page mit einer Warnung im HA-Log.

> **⚠ Pages NUR im Markdown-Editor bearbeiten — nicht im WYSIWYG-Editor.**
> BookStacks WYSIWYG-Editor (TinyMCE) konvertiert Markdown → HTML →
> Markdown beim Wechseln und verwirft dabei stillschweigend
> HTML-Kommentare wie `<!-- BEGIN AUTO-GENERATED -->`. Sobald die
> Marker weg sind, kann der Sync nicht mehr unterscheiden was AUTO und
> was MANUAL ist. Seit v0.14.9 erkennt die Integration das und
> überspringt betroffene Pages — du siehst dann ein Repair-Issue
> *„Marker-Kommentare einer Page fehlen"*. Recovery: Page im
> Markdown-Editor öffnen, MANUAL-Block-Notizen woanders sichern, dann
> *Sofort synchronisieren* mit aktiviertem *Geänderte Seiten erzwungen
> überschreiben* aufrufen. Die Integration setzt zusätzlich bei jedem
> Write `editor: "markdown"`, um den WYSIWYG-Toggle zu deaktivieren —
> ältere BookStack-Versionen ignorieren das Feld aber.

## Entwicklung

Repo ist auf das ludeeus-Devcontainer-Layout aufgesetzt:

```bash
scripts/develop  # startet HA mit dieser Integration unter ./config
scripts/lint     # ruff check + format
```

Der CI-Workflow validiert hassfest + HACS auf jedem Push.

## Nicht-Ziele

- Keine Passwortverwaltung – Vaultwarden bleibt strikt getrennt.
- Kein bidirektionaler Sync – Daten fließen nur HA → BookStack.
- Kein Edit-Konflikt-Resolver – Konflikte werden geloggt, nicht aufgelöst.

## Lizenz

MIT – siehe [LICENSE](LICENSE).
