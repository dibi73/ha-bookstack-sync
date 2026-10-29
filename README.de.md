# BookStack Sync für Home Assistant

[![HACS Default](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://hacs.xyz/)
[![GitHub release](https://img.shields.io/github/v/release/dibi73/ha-bookstack-sync)](https://github.com/dibi73/ha-bookstack-sync/releases)
[![Tests](https://github.com/dibi73/ha-bookstack-sync/actions/workflows/test.yml/badge.svg)](https://github.com/dibi73/ha-bookstack-sync/actions/workflows/test.yml)
[![Lint](https://github.com/dibi73/ha-bookstack-sync/actions/workflows/lint.yml/badge.svg)](https://github.com/dibi73/ha-bookstack-sync/actions/workflows/lint.yml)

> Verfügbar in: [English](README.md) · **Deutsch**
>
> *(Die HA-Oberfläche der Integration ist in 28 Sprachen übersetzt — diese README gibt es auf Deutsch und Englisch, beide werden synchron gehalten.)*

Eine Custom-Integration für Home Assistant (installierbar über HACS),
die dein gesamtes HA-Setup als Markdown-Seiten in ein bestehendes Buch
deines [BookStack](https://www.bookstackapp.com/)-Wikis schreibt und
aktuell hält.

Das Besondere: **Manuell ergänzte Wiki-Inhalte bleiben bei jedem Sync
erhalten.** Jede Seite ist durch Markdown-Marker in einen automatisch
erzeugten und einen manuellen Teil getrennt. Die Integration schreibt
ausschließlich den automatischen Teil neu — deine Notizen, Eigenheiten,
Verweise auf Passwörter und „warum wir Option X gesetzt haben“-Kommentare
bleiben im manuellen Teil dauerhaft bestehen.

**Inhalt:**
[Was dokumentiert wird](#was-dokumentiert-wird) ·
[Warum](#warum) ·
[Status](#status) ·
[Voraussetzungen](#voraussetzungen) ·
[Installation](#installation) ·
[Konfiguration](#konfiguration) ·
[So läuft ein Sync ab](#so-läuft-ein-sync-ab) ·
[Seitenaufbau](#seitenaufbau-mit-marker-blöcken) ·
[Services](#services) ·
[Markdown-Export](#markdown-export-für-rag-opt-in) ·
[Entitäten, Reparaturen und Benachrichtigungen](#entitäten-reparaturen-und-benachrichtigungen) ·
[Anwendungsfälle](#anwendungsfälle) ·
[Beispiele](#beispiele) ·
[Fehlersuche](#fehlersuche) ·
[Bekannte Einschränkungen](#bekannte-einschränkungen) ·
[Integration entfernen](#integration-entfernen) ·
[Nicht-Ziele](#nicht-ziele) ·
[Entwicklung](#entwicklung) ·
[Sicherheit](#sicherheit) ·
[Lizenz](#lizenz)

## Was dokumentiert wird

Die Seiten werden in Kapiteln deines Ziel-Buchs organisiert:

- **Übersicht** — reine Navigation mit Links auf alle anderen Seiten
  (keine Statistiken — die stehen auf den Seiten, die sie beschreiben)
- Kapitel **Räume** — eine Seite pro Bereich mit allen Geräten und
  Entitäten darin
- Kapitel **Geräte** — eine Seite pro physischem Gerät mit Hersteller,
  Modell, Firmware-Version, zugehörigen Integrationen, Netzwerkdaten und
  jeder Entität samt aktuellem Zustand und (bei MQTT-Geräten) dem Topic.
  Geräte, die Home Assistant (seit HA 2026.8) auf mehrere Integrationen
  aufteilt, werden automatisch zu einer Seite zusammengeführt — unter
  „Auch bekannt als“ auf der Geräteseite stehen die einzelnen
  Registry-Einträge, die zusammengefasst wurden. Die Seite nennt außerdem
  die Dashboard-Ansichten, auf denen eine Entität des Geräts zu sehen ist,
  mit Link zur Ansicht („Angezeigt auf Dashboards“); die
  Dashboard-Konfiguration selbst wird nicht kopiert — die liegt im
  HA-Backup
- Kapitel **Labels** — eine Seite pro HA-Label mit allen Geräten, die es
  tragen (direkt oder über eine ihrer Entitäten)
- **Integrationen**, **Automationen**, **Skripte**, **Szenen** — je eine
  Sammelseite mit jedem Eintrag samt Beschreibung, Modus, letzter
  Auslösung usw. Jede Automation und jedes Skript bekommt außerdem eine
  lesbare Zusammenfassung ihrer Auslöser, Bedingungen und Aktionen (bei
  Skripten: Eingabefelder und Ablauf), mit Entitäten, Geräten und Räumen
  beim Namen. Das rohe YAML wird nicht kopiert — das liegt bereits im
  HA-Backup. Bei Aktionsdaten stehen Werte nur für unbedenkliche Felder
  wie `message`, `brightness_pct` oder `temperature`; alle anderen
  Felder erscheinen nur mit Namen, weil ihre Werte aus `!secret` stammen
  können. Webhook-IDs erscheinen nie. Eine Automation oder ein Skript
  aus einem Blueprint zeigt stattdessen den Blueprint und seine Eingaben
  mit ihren Anzeigenamen (Eingaben, deren Name nach Zugangsdaten
  klingt, bleiben verborgen), und beide Seiten enden mit einer Liste
  **Blueprints**: jeder installierte Blueprint mit Datei, Autor, Quelle,
  kurzer Beschreibung und den Automationen bzw. Skripten, die ihn nutzen
  — auch unbenutzte
- **Netzwerk** — Tabelle aller Geräte mit Netzwerkdaten, dazu ein
  UniFi-Topologiebaum und ein Exportblock für DHCP-Reservierungen, wo
  möglich
- **Bluetooth** — die Liste der BT-Proxys (ESPHome-BT-Proxy-Knoten und
  ähnliche) plus eine Tabelle aller per Bluetooth erfassten Geräte mit
  aktuellem Status (erreichbar / nicht erreichbar) und letzter
  Aktivität, die zuletzt aktiven zuerst
- **Recorder**, **Energie**, **MQTT-Topics**, **Helfer** — je eine Seite,
  wenn die jeweilige HA-Funktion eingerichtet ist
- **Backup** — letztes erfolgreiches/versuchtes Backup plus eine Tabelle
  aller gespeicherten Backups mit Ziel(en) und Größe pro Ziel
- **Add-ons** — Liste der Supervisor-Add-ons (nur unter HassOS /
  Supervised)

Die Ausgabesprache folgt standardmäßig der Sprache deiner HA-Oberfläche
(Deutsch und Englisch werden unterstützt); in den Optionen lässt sie
sich fest einstellen.

**Der Netzwerk-Topologiebaum ist UniFi-spezifisch.** Der ASCII-Baum auf
der Netzwerkseite (Gateway → Switch → Access Points → Clients)
funktioniert nur mit Ubiquiti/UniFi-Hardware über HAs
`unifi`-Integration — sowohl die Erkennung der Geräterolle als auch die
Verkabelung Switch↔Gateway/AP↔Switch stammen aus UniFi-spezifischen
Datenfeldern, die andere Hersteller-Integrationen (FritzBox, TP-Link
Omada, MikroTik, Cisco Meraki, …) nicht in dieser Form liefern. Mit
anderer Hardware zeigt die Netzwerkseite weiterhin die flache
Gerätetabelle mit IP/MAC/Verbindung — nur ohne Topologiebaum.

**Kabelgebundene (LAN-)Clients hängen nicht unter dem Switch, auch nicht
bei UniFi.** HAs `unifi`-Integration meldet, an welchem Access Point ein
*WLAN*-Client hängt (`ap_mac`), deshalb erscheinen WLAN-Geräte korrekt
unter ihrem AP. Für den Switch-Port eines *kabelgebundenen* Clients gibt
es kein entsprechendes Attribut, daher können kabelgebundene Clients
nicht unter dem Switch eingeordnet werden — eine Datenlücke in HAs
`unifi`-Integration selbst, die sich hier nicht umgehen lässt.
Kabelgebundene Geräte erscheinen überall sonst korrekt (eigene
Geräteseite, flache Netzwerktabelle, DHCP-Export). Upstream gemeldet:
[home-assistant/core#180499](https://github.com/home-assistant/core/issues/180499).

**UniFi-„Geister“-Clients erscheinen auf der Netzwerkseite mit lauter
Strichen.** Ein UniFi-Controller merkt sich jede MAC-Adresse, die sich
je verbunden hat — auch das Handy eines Gasts, das einmal im WLAN war,
ein Nachbargerät, das kurz angefragt hat, oder ein IoT-Gerät von vor
Jahren — und HA legt für jede davon ein Gerät an. Ein aktuell
getrennter Client hat keine aktuelle IP (korrekt, kein Fehler), und
viele dieser Zufallseinträge hatten nie einen Hostnamen. Sie landen
deshalb als anonyme MAC ohne weitere Angaben auf der Netzwerkseite. Die
Integration kann das nicht von einem echten, aktuell relevanten Gerät
unterscheiden — UniFi meldet „das ist alte Netzwerk-Historie“ nicht als
eigenes Signal, deshalb bleiben diese Zeilen sichtbar statt still
ausgeblendet zu werden.

**Bluetooth-Geräte lassen sich keinem bestimmten Proxy zuordnen.** HAs
`via_device_id` verknüpft bei Bluetooth nur einen Scanner/Adapter mit
dem physischen Host, auf dem er läuft — nie ein entdecktes BLE-Gerät mit
dem Proxy, der es gehört hat. Das ist architekturbedingt: Ein BLE-Gerät
kann gleichzeitig in Reichweite mehrerer Proxys sein, es gibt also —
anders als bei der WLAN/AP-Zuordnung — kein einzelnes Elternteil. Die
Bluetooth-Seite führt Proxys und erfasste Geräte deshalb getrennt: einen
Abschnitt „Bluetooth-Proxys“, der jeden BT-Proxy-Host nennt (damit
zumindest sichtbar ist, welche Proxys es gibt), und eine Gerätetabelle
nur mit Status (erreichbar/nicht erreichbar) und Zeitpunkt der letzten
Aktivität — ohne zu behaupten, welcher Proxy welches Gerät gehört hat.
Eine frühere Version dieser Seite teilte Geräte binär in „gesehen“ und
„sollte da sein, aber nicht gefunden“ — das war irreführend: Ein
passiver BLE-Sensor ist nach jedem HA-Neustart für Sekunden bis zig
Minuten `unavailable`, während sein Proxy sich neu verbindet, und das
heißt nicht, dass das Gerät weg ist. Ein normaler Neustart ließ die
ganze Seite so aussehen, als wären alle Geräte verschwunden. Status plus
Zeitstempel vermeiden diesen Fehlalarm und überlassen dir die
Bewertung.

## Warum

- **Ein Smart Home, das sich selbst dokumentiert.** Jedes Gerät, jeder
  Raum, jede Automation steht im Wiki — immer aktuell.
- **Übersteht manuelle Änderungen.** Ergänze Querverweise, Eigenheiten,
  „Warum“-Notizen auf jeder Seite — sie bleiben bei künftigen Syncs
  erhalten. Eine Hash-basierte Erkennung protokolliert (und überspringt)
  jede Seite, deren automatischer Teil außerhalb von HA geändert wurde.
- **Idempotent.** Gleicher HA-Zustand → byte-identisches Markdown →
  keine unnötigen BookStack-Revisionen. Mit ausgeschalteten aktuellen
  Werten erzeugt nur eine echte Änderung an der Einrichtung eine neue
  Revision.
- **Weiches Löschen.** Verschwindet ein Gerät aus HA, wird seine Seite
  nicht gelöscht. Stattdessen ersetzt ein Hinweis „verwaist — Gerät weg
  seit JJJJ-MM-TT“ den automatischen Teil; der manuelle Teil bleibt.
- **Übersteht BookStack-Neustarts und HA-Umzüge.** Die Zuordnung
  HA-ID ↔ BookStack-Seiten-ID liegt in HAs Speicher
  (`.storage/bookstack_sync.<entry_id>.mapping`).

## Status

Produktionsreif und im HACS-Standard-Store gelistet. Aktuelle Version
und Änderungen je Version stehen unter
[Releases](https://github.com/dibi73/ha-bookstack-sync/releases). Ziel ist
die Stufe **Platinum** der HA Quality Scale:

- Vollständige Auswertung der HA-Daten (Räume, Geräte, Entitäten,
  Automationen, Skripte, Szenen, Integrationen, Add-ons, Netzwerk,
  Bluetooth, Recorder, Energie, MQTT, Helfer, Backups, Labels)
- Zusammenführung von Geräten, die auf mehrere Integrationen aufgeteilt
  sind (HA 2026.8+)
- Marker-Block-Merge mit Hash-basierter Erkennung fremder Änderungen
- Mehrstufiger Aufbau der Übersicht mit internen Seitenlinks
- Status-Sensor mit Live-Fortschritt, Buttons für Sync / Vorschau /
  erzwungenen Sync, Benachrichtigungen mit Links zu den betroffenen
  Seiten, Reparaturmeldungen mit Ein-Klick-Lösung
- Ganze Integrationen, einzelne Geräte oder alles in HA Deaktivierte von
  der Dokumentation ausschließen
- Wahlweise aktuelle Werte (Zustände, Zeitstempel) weglassen, damit sich
  Seiten nur ändern, wenn sich die Einrichtung ändert
- Reauth-Flow und Neu-konfigurieren-Flow (URL / Token / TLS)
- Diagnose-Endpunkt (geschwärzter Dump für Fehlerberichte)
- TLS-Prüfung abschaltbar, Anzeige der MQTT-Topics, Oberfläche in 28
  Sprachen
- Services nur für Admins (`run_now`, `preview`, `export_markdown`)
- Umfangreiche Testsuite für Merge-Logik, deterministisches Rendering,
  API-Client, Config-Flow, Coordinator und Sync-Ablauf

### Quality Scale

Selbst erklärt (`manifest.json`), da Hassfest die Gold-/Platinum-Regeln
bei Custom-Integrationen nicht formal prüft:

- ✅ **Bronze / Silver**: Config-Flow, eindeutige IDs, Runtime-Data,
  Reauth-Flow, Integration-Owner, Log-when-unavailable, Testabdeckung
- ✅ **Gold**: Diagnose, Neu-konfigurieren-Flow, Entity-Kategorien,
  dynamische Geräte, Reparaturmeldungen (fremde Änderung / Marker
  verloren / Ziel nicht erreichbar, jeweils mit `translation_key`),
  übersetzte Laufzeitfehler, vollständige Doku-Abschnitte, Oberfläche in
  28 Sprachen
- ⚪ **`stale-devices`**: bewusst nicht anwendbar — die Integration
  besitzt ein synthetisches HA-Gerät pro Config-Eintrag (wird nie
  veraltet); die eigentlich erfassten „Quellgeräte“ leben als
  BookStack-Seiten, die schon weich gelöscht (als verwaist markiert)
  werden, wenn ihr HA-Objekt verschwindet. Das ist der Sinn der Regel,
  nur nicht das, was sie wörtlich prüft.
- ✅ **Platinum**: `strict-typing` (`py.typed` plus `mypy --strict` als
  CI-Prüfung, seit v0.16.2), `inject-websession` (nutzt immer HAs eigene
  `async_get_clientsession`/`async_create_clientsession`, nie eine selbst
  gebaute Session), `async-dependency` (nicht anwendbar —
  `requirements: []`, keine externe PyPI-Abhängigkeit)

## Voraussetzungen

- **Home Assistant**: Die CI testet gegen Home Assistant 2026.8; im
  Alltag läuft die Integration auf aktuellen Versionen (2026.10). Sie
  berücksichtigt die Änderung an der Geräte-Registry in 2026.9, ältere
  und neuere Versionen funktionieren also beide.
- **BookStack** mit einer REST-API, die von Home Assistant aus erreichbar
  ist. Bekannt funktionierend mit dem BookStack-Add-on für Home Assistant
  (5.0.x) und mit eigenständigen Installationen, auch hinter dem Reverse
  Proxy eines NAS.
- **Ein BookStack-Buch** als Ziel und ein **API-Token** mit Lese- und
  Schreibrechten darauf (*My Profile → API Tokens*; der Benutzer braucht
  die Berechtigung „Access system API“).
- Optional: Supervisor (HAOS / Supervised) für die Add-on-Seite.

## Installation

### Über HACS (empfohlen)

BookStack Sync ist im HACS-Standard-Store:

1. **HACS** → nach **BookStack Sync** suchen → **Herunterladen**
2. Home Assistant neu starten
3. **Einstellungen → Geräte & Dienste → Integration hinzufügen →
   „BookStack Sync“**

Findet die Suche die Integration nicht (sehr altes HACS), füge sie als
benutzerdefiniertes Repository hinzu: HACS → oben rechts **⋮** →
**Benutzerdefinierte Repositories** →
`https://github.com/dibi73/ha-bookstack-sync`, Typ **Integration**.

### Manuelle Installation

Kopiere `custom_components/bookstack_sync/` aus diesem Repo in das
Verzeichnis `config/custom_components/` deiner HA-Installation, starte
HA neu und füge die Integration über die Oberfläche hinzu.

## Konfiguration

Die Einrichtung fragt zwei Seiten ab:

**Schritt 1 — Verbindung**
- **BookStack-URL**: z. B. `https://bookstack.example.com` oder
  `http://192.168.0.11:6875`
- **API-Token-ID + Secret**: in BookStack unter *My Profile → API
  Tokens* anlegen. Das Token braucht Lese- und Schreibrechte auf das
  Ziel-Buch.
- **TLS-Zertifikat prüfen**: eingeschaltet lassen, außer du nutzt ein
  selbst signiertes Zertifikat (häufig bei Synology / NAS).

**Schritt 2 — Ziel**
- Das Buch, in das synchronisiert wird (Auswahl aller lesbaren Bücher)
- Sync-Intervall: stündlich / täglich / nur manuell

**Neu konfigurieren** (Integrationskachel → **⋮** → *Neu konfigurieren*)
ändert die Verbindung später, ohne die Integration zu entfernen:
- **BookStack-URL**, **API-Token-ID + Secret**, **TLS-Zertifikat
  prüfen** — wie in Schritt 1
- **Externe BookStack-URL** (optional): die Adresse, unter der Menschen
  BookStack öffnen, falls sie von der URL oben abweicht (z. B. eine
  öffentliche Domain, während die Integration über eine LAN-Adresse
  spricht). Wird für Links genutzt, die außerhalb von BookStack gelesen
  werden: Reparaturmeldungen, Benachrichtigungen, der „Besuchen“-Link
  auf der Gerätekarte und die Liste „Verwaiste Seiten“.

Der Dialog **Optionen** (Integrationskachel → *Konfigurieren*) umfasst:
- Buch und Sync-Intervall — wie in Schritt 2
- Ausgabesprache (`Auto` folgt HA, oder fest `Deutsch` / `Englisch`)
- Markdown-Rückexport (standardmäßig aus) und Export-Ordner
- Ganze Integrationen von der Dokumentation ausschließen (Mehrfachauswahl,
  z. B. eine Aufgabenlisten-Integration wie Vikunja — ihre Geräte und
  Entitäten erscheinen gar nicht im Wiki, die Integration selbst bleibt
  aber auf der Integrationsseite gelistet, als ausgeschlossen markiert)
- Zusätzlich einzelne Geräte ausschließen, unabhängig von der Integration
- Alles weglassen, was in HA deaktiviert ist: deaktivierte Entitäten,
  deaktivierte Geräte und (weil HA deren Geräte und Entitäten mit
  deaktiviert) deaktivierte Integrationen. Standardmäßig aus; hilfreich,
  wenn eine Integration tausende deaktivierte Entitäten anlegt und ihre
  Geräteseiten riesig werden
- Aktuelle Werte nicht dokumentieren: lässt alles weg, was nur ein
  Messwert zum Zeitpunkt des Syncs ist, also Zustände der Entitäten,
  *Letzter Trigger* von Automationen und Skripten, Werte der Helfer,
  Bluetooth-Erreichbarkeit und jedes *Zuletzt gesehen*. Die passenden
  Tabellenspalten entfallen. Erhalten bleiben der Ein/Aus-Status einer
  Automation, der Zustand der Integrationen und IP-Adressen.
  Standardmäßig aus; einschalten, wenn BookStack nur bei echten
  Änderungen Revisionen bekommen und der Sync schneller sein soll (siehe
  *So läuft ein Sync ab*)

## So läuft ein Sync ab

**Wann ein Sync läuft**
- Im eingestellten Intervall (stündlich oder täglich; `manuell` schaltet
  es ab)
- Wenn du *Jetzt synchronisieren* oder *Sync erzwingen* drückst oder
  `run_now` aufrufst
- Für eine einzelne Seite, wenn du bei einer Reparaturmeldung auf
  *Reparieren* klickst
- *Sync-Vorschau* und `preview` protokollieren nur, was sich ändern würde

**Was ein Sync macht**
1. Liest die Registries von Home Assistant (Räume, Geräte, Entitäten,
   Labels, Automationen, …) und baut daraus den automatischen Teil jeder
   Seite.
2. Vergleicht jede Seite mit dem, was zuletzt geschrieben wurde.
   Unveränderte Seiten werden nicht geschrieben, BookStack bekommt also
   keine leeren Revisionen. Der Zeitstempel oben auf einer Seite zeigt
   deshalb, wann sich ihr Inhalt zuletzt geändert hat.
   Standardmäßig zeigen die Seiten auch aktuelle Werte (Zustände der
   Entitäten, *Letzter Trigger*, …), und die ändern sich zwischen fast
   jedem Sync. In einer typischen Installation schreibt das bei jedem
   Lauf etwa ein Fünftel aller Seiten neu. Mit *Aktuelle Werte nicht
   dokumentieren* schreibt ein Sync bei unveränderter Einrichtung nichts.
3. Schreibt geänderte Seiten, bis zu 5 gleichzeitig, und bleibt dabei
   unter BookStacks Standardgrenze von 180 API-Anfragen pro Minute.
   Netzwerkaussetzer und Antworten wegen Ratenbegrenzung werden mit
   Wartezeit wiederholt; sehr große Seiten bekommen beim Schreiben mehr
   Zeit und werden vor einer Wiederholung geprüft, damit sie nie doppelt
   gesendet werden.
4. Markiert Seiten, deren HA-Objekt verschwunden ist, als verwaist (siehe
   *Bekannte Einschränkungen*) und aktualisiert die Liste „Verwaiste
   Seiten“.
5. Schreibt die Exportdateien, wenn der Markdown-Export eingeschaltet
   ist.
6. Aktualisiert den Status-Sensor; bei Fehlern oder Konflikten erscheint
   zusätzlich eine Benachrichtigung.

Ein Sync liest nur aus Home Assistant und schreibt nur nach BookStack.
In Home Assistant wird nichts verändert.

## Seitenaufbau mit Marker-Blöcken

Jede Seite, die die Integration schreibt, ist so aufgebaut:

```markdown
<!-- BEGIN AUTO-GENERATED -->
... wird bei jedem Sync von der Integration neu erzeugt ...
<!-- END AUTO-GENERATED -->

<!-- BEGIN MANUAL -->
Deine Notizen, Eigenheiten, Querverweise — werden nie überschrieben.
<!-- END MANUAL -->
```

Bearbeite in BookStack nur den **MANUAL**-Block. Die Integration
berechnet bei jedem Schreiben einen SHA-256-Hash des automatischen Teils
und vergleicht ihn mit dem zuletzt geschriebenen — hat sich unerwartet
etwas geändert (z. B. hat jemand im automatischen Teil editiert), wird
die Seite mit einer Warnung übersprungen statt überschrieben.

## Services

- **`bookstack_sync.run_now`** — startet sofort einen Sync. Nützlich,
  nachdem ein neues Gerät dazugekommen ist. Parameter **`force`**
  (Standard `false`): überschreibt auch Seiten, deren automatischer Teil
  in BookStack geändert wurde; der manuelle Teil bleibt. Entspricht dem
  Button *Sync erzwingen*.
- **`bookstack_sync.preview`** — Probelauf. Protokolliert im HA-Log, was
  angelegt / aktualisiert würde, schreibt aber nichts nach BookStack.
  Nimmt denselben Parameter **`force`**, um zu sehen, was ein
  erzwungener Sync überschreiben würde.
- **`bookstack_sync.export_markdown`** — Opt-in: schreibt jede verwaltete
  BookStack-Seite zusätzlich als reine Markdown-Datei in einen Ordner,
  etwa als Eingabe für RAG / LLM. **Standardmäßig deaktiviert** — siehe
  *Markdown-Export für RAG* unten.

Alle drei sind unter *Entwicklerwerkzeuge → Aktionen* oder in
Automationen verfügbar.

## Markdown-Export für RAG (Opt-in)

Seit v0.13.0 kann die Integration den zusammengeführten Inhalt
(automatischer Teil + deine manuellen Notizen) zusätzlich als reine
Markdown-Dateien mit YAML-Frontmatter in einen Ordner zurückschreiben —
das universelle Eingabeformat für RAG-/LLM-Pipelines (LangChain
`ObsidianLoader`, LlamaIndex `ObsidianReader`, Open WebUI Knowledge
Base, …).

> **Standardmäßig aus.** Der Export kostet bei jedem Lauf Speicherplatz
> und CPU, und für die meisten reichen die BookStack-Seiten allein. Schalte
> ihn bewusst ein, wenn du wirklich eine separate Markdown-Kopie für einen
> externen Indexer brauchst. Der Schalter liegt im Dialog **Konfigurieren**
> der Integration unter *Markdown-Export aktivieren*.

Eingeschaltet entsteht eine flache Ordnerstruktur (Standard
`<config>/bookstack_export/`):

```
bookstack_export/
├── _index.md                    ← Liste aller exportierten Seiten
├── devices/
│   ├── light-living-room.md
│   └── ...
├── areas/
│   └── living-room.md
└── automations/
    └── away-mode.md
```

Jede Datei sieht so aus:

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

[automatischer Teil — Hersteller, Modell, Firmware, Entitätenliste,
aktuelle Zustände, MQTT-Topic, …]

---

[deine manuellen Notizen — unverändert aus BookStack übernommen]
```

Auslösung:

Sobald `export_enabled` eingeschaltet ist, schreibt jeder erfolgreiche
Sync auch die Markdown-Dateien — eine Automation ist nicht nötig. Der
Service `bookstack_sync.export_markdown` bleibt für Aufrufe zwischendurch
verfügbar (z. B. „jetzt sofort neu exportieren“).

```yaml
# Optional: zusätzlicher Export zu einer festen Uhrzeit.
automation:
  - alias: BookStack-Export um 03:30
    trigger:
      - platform: time
        at: "03:30:00"
    action:
      - service: bookstack_sync.export_markdown
```

Vollständiges Schema und Beispiele für einzelne Werkzeuge in
[docs/EXPORT.md](docs/EXPORT.md).

## Entitäten, Reparaturen und Benachrichtigungen

Jede eingerichtete BookStack-Instanz bekommt ein Gerät mit diesen
Entitäten:

**Status-Sensor**
- **Zustand**: `ok` / `error` / `never_run`, und während eines Laufs der
  Live-Fortschritt, z. B. `Sync läuft 33/453` und danach
  `Export läuft 120/486` (zu Beginn kurz `syncing`)
- **Attribute**: `last_run`, `created`, `updated`, `unchanged`,
  `tombstoned`, `skipped_conflict`, `errors`, `total_pages`, dazu die
  Export-Zähler, wenn der Markdown-Export eingeschaltet ist

**Buttons**
- **Jetzt synchronisieren** — ein vollständiger Sync, wie `run_now`
- **Sync-Vorschau (Dry-Run)** — protokolliert, was sich ändern würde,
  schreibt nichts
- **Sync erzwingen** — ein vollständiger Sync, der auch Seiten
  überschreibt, deren automatischer Teil in BookStack geändert wurde (der
  manuelle Teil bleibt). **Standardmäßig deaktiviert**, damit er nicht
  versehentlich gedrückt wird; bei Bedarf in den Einstellungen der
  Entität aktivieren.

**Reparaturmeldungen** (*Einstellungen → System → Reparaturen*)
- *Seite außerhalb von Home Assistant geändert* — eine pro Seite, mit
  einem Button **Reparieren**, der nur den automatischen Teil dieser
  Seite überschreibt
- *Marker-Kommentare fehlen* — die Seite wurde im WYSIWYG-Editor
  geöffnet; **Reparieren** legt die Seite neu an (manuelle Notizen
  vorher sichern)
- *Viele Seiten im Konflikt* — nach einem Update, das die Darstellung
  der Seiten ändert; **Reparieren** erzwingt den Sync aller Seiten auf
  einmal
- *BookStack nicht erreichbar* — nach drei fehlgeschlagenen Syncs in
  Folge; verschwindet von selbst nach dem nächsten erfolgreichen Sync

**Benachrichtigung** — nur nach einem Lauf mit Fehlern oder Konflikten.
Sie nennt die Zahlen und darunter die betroffenen Seiten, jeweils
verlinkt auf die BookStack-Seite und, bei Geräten und Räumen, auf das
Objekt in Home Assistant.

## Anwendungsfälle

- **Übergabemappe fürs Haus**: Verkaufst du das Haus oder übergibst es
  an eine Betreuung, listet das Wiki schon jedes smarte Gerät, jede
  Raumzuordnung, jede Automation — das Buch als PDF exportieren, und du
  hast ein druckbares Handbuch.
- **„Warum ist das Gerät offline?“**: Die Wiki-Seite des Geräts zeigt
  Hersteller / Modell / Firmware *und* deine Notizen („Batterie
  2024-10 getauscht“, „nach Router-Neustart Zigbee neu koppeln“)
  nebeneinander.
- **Partner / Familie einweisen**: Das Kapitel Räume zeigt, welche
  Lampen zu welchem Raum gehören, die Automationsseite, was bei
  Sonnenuntergang läuft, und im manuellen Teil jeder Seite erklärst du
  die Absicht.
- **Umzug vorbereiten**: Bevor du eine neue HA-Box aufsetzt, ist das
  Wiki deine unabhängige Aufzeichnung, welche Integrationen es gibt, wie
  sie heißen und welche Entitäten zu ihnen gehören — übersteht auch eine
  missglückte Konfigurations-Wiederherstellung.

## Beispiele

**Sync über eine Button-Karte auslösen:**

```yaml
type: button
name: Wiki synchronisieren
tap_action:
  action: call-service
  service: bookstack_sync.run_now
```

**Täglicher Sync um 03:00 statt des eingebauten Intervalls:**

```yaml
automation:
  - alias: BookStack täglicher Sync
    trigger:
      - platform: time
        at: "03:00:00"
    action:
      - service: bookstack_sync.run_now
```

(Vorher das Intervall der Integration auf `manuell` stellen.)

**Bei Sync-Fehlern benachrichtigen:**

```yaml
automation:
  - alias: BookStack-Sync-Fehler
    trigger:
      - platform: state
        entity_id: sensor.bookstack_sync_status
        to: "error"
    action:
      - service: notify.mobile_app_my_phone
        data:
          message: >
            BookStack-Sync fehlgeschlagen:
            {{ state_attr('sensor.bookstack_sync_status', 'errors') }}
```

## Fehlersuche

**„BookStack rejected the API token“** — Token in BookStack neu anlegen
(*My Profile → API Tokens*) und prüfen, dass es Lese- und Schreibrechte
auf das Ziel-Buch hat. Die Integration zeigt unter Geräte & Dienste eine
Karte zur erneuten Anmeldung; anklicken, neue ID + Secret einfügen,
fertig.

**„BookStack nicht erreichbar“** — meist eines davon: falsche URL (Port
vergessen?), TLS-Prüfung eingeschaltet trotz selbst signiertem
Zertifikat (unter *Konfigurieren* abschalten), Reverse Proxy liefert
mitten im Sync 502 (die Integration wiederholt solche Fehler dreimal mit
steigender Wartezeit — klappt es dann noch nicht, holt der nächste Sync
es nach).

**„AUTO-Block wurde außerhalb von Home Assistant geändert“** — jemand hat
den automatischen Teil in BookStack bearbeitet. Die Integration
*überspringt* diese Seite, statt die Änderung zu überschreiben. Mach die
Änderung in BookStack rückgängig oder verschiebe den Inhalt in den
manuellen Teil, dann erneut synchronisieren.

**Benachrichtigung „X Fehler“** — den Diagnose-Dump der Integration
herunterladen (Zahnrad → *Diagnose herunterladen*) und an ein
GitHub-Issue anhängen. Der Dump schwärzt URL und Token automatisch.

**Seiten liegen auf Buchebene statt in ihrem Kapitel** — bekannter Fehler
aus v0.1.x, behoben in v0.4.0. Nach einem Update verschiebt der nächste
Sync sie automatisch ins richtige Kapitel.

## Bekannte Einschränkungen

- **⚠ Seiten nur im Markdown-Editor bearbeiten — nie im WYSIWYG-Editor.**
  BookStacks WYSIWYG-Editor (TinyMCE) wandelt Markdown über HTML hin und
  zurück und verwirft dabei still die HTML-Kommentar-Marker
  (`<!-- BEGIN AUTO-GENERATED -->` usw.). Danach kann die Integration
  nicht mehr unterscheiden, welcher Teil der Seite dir gehört und welcher
  automatisch erzeugt ist. Seit v0.14.9 erkennt die Integration das und
  überschreibt betroffene Seiten nicht — du siehst dann in HA die
  Reparaturmeldung *Marker-Kommentare einer Page fehlen*. Lösung: Seite
  im Markdown-Editor öffnen, manuelle Notizen woanders sichern und *Sync
  erzwingen* drücken (oder `run_now` mit `force: true` aufrufen), damit
  die Seite mit frischen Markern neu entsteht. Die Integration setzt bei
  jedem Schreiben zusätzlich `editor: "markdown"`, um den
  WYSIWYG-Schalter zu verhindern, ältere BookStack-Versionen behandeln
  das Feld aber nur als Empfehlung. Seit v0.22.0 hat die
  Reparaturmeldung selbst einen Button **Reparieren** (Einstellungen →
  System → Reparaturen), der dasselbe nur für diese eine Seite statt für
  den ganzen Config-Eintrag macht — manuelle Notizen vorher sichern, sie
  werden auf den Standard-Platzhalter zurückgesetzt und lassen sich
  nicht automatisch wiederherstellen. Derselbe Button behebt auch eine
  Meldung *page_tampered*, dort ohne den manuellen Teil zurückzusetzen.
  Ein Update, das die Darstellung des automatischen Teils ändert, kann
  viele Seiten auf einmal so blockieren (Hash-Abweichung, keine echte
  Fremdänderung) — seit v0.24.0 erscheint dafür zusätzlich eine
  Sammel-Reparaturmeldung (sobald mehr als eine Handvoll Seiten im
  selben Lauf betroffen sind) mit eigenem Button **Reparieren**, der alle
  Seiten auf einmal erzwungen synchronisiert, statt jede einzeln
  durchzuklicken.
- **Kein bidirektionaler Sync.** Änderungen in BookStack außerhalb des
  manuellen Teils werden erkannt, protokolliert und die Seite
  übersprungen — sie fließen nicht nach HA zurück.
- **Der Sync folgt dem HA-Zustand.** Benennst du einen Raum oder ein
  Gerät um, wird beim nächsten Sync die Seite umbenannt; die alte Seite
  wird verwaist und bekommt einen Hinweis. Das Aufräumen verwaister
  Seiten bleibt dir überlassen — eine eigene Seite **„Verwaiste Seiten“**
  (verlinkt von der Übersicht unter „Weitere Seiten“) listet bei jedem
  Sync alle aktuell verwaisten Seiten mit direktem Link und dem Datum
  „verwaist seit“ — ganz ohne BookStack-Kenntnisse. Jede verwaiste Seite
  trägt zusätzlich den Tag `bookstack_sync = orphaned`, sodass auch
  BookStacks eigene Tag-Suche (`[bookstack_sync=orphaned]`) funktioniert.
- **Seiteninhalte nur auf Deutsch und Englisch.** Die Oberfläche der
  Integration ist in 28 Sprachen übersetzt (seit v0.12.0), der *Inhalt*
  der BookStack-Seiten ist aber Deutsch oder Englisch. Eine weitere
  Inhaltssprache heißt `_strings.py` befüllen; PRs willkommen.
- **Aktuelle Werte sind eine Momentaufnahme.** Zustände und
  Zeitstempel auf den Seiten sind die Werte zum Zeitpunkt des letzten
  Syncs, keine Live-Daten — dafür ist HA da. Auch mit ausgeschalteten
  aktuellen Werten kann sich die Netzwerkseite ändern, wenn ein
  WLAN-Client zu einem anderen Access Point oder VLAN wechselt, und die
  Integrationsseite, wenn eine Integration nach einem Neustart in
  `setup_retry` hängt.
- **Das API-Token hat Zugriff auf Buchebene.** BookStack kennt keine
  Tokens pro Seite; die Integration nutzt, was das Token erreichen kann.

> *Mehrere BookStack-Bücher / mehrere BookStack-Instanzen **werden**
> unterstützt* — die Integration einmal pro Ziel hinzufügen. Jeder
> Config-Eintrag ist an seine Basis-URL gebunden und hat eigenen
> Coordinator, Speicher und Status-Sensor.

## Integration entfernen

1. **Einstellungen → Geräte & Dienste → BookStack Sync** → **⋮** neben
   dem Eintrag → **Löschen**. Für jede eingerichtete BookStack-Instanz
   wiederholen.
2. Bei Installation über HACS: **HACS → BookStack Sync → ⋮ → Entfernen**,
   dann Home Assistant neu starten. Bei manueller Installation
   `config/custom_components/bookstack_sync/` löschen und neu starten.

Was mit deinen Daten passiert:
- **Die BookStack-Seiten bleiben** samt deiner manuellen Notizen
  erhalten. Lösche sie in BookStack, wenn du sie nicht mehr brauchst;
  die Seiten der Integration tragen den Tag `bookstack_sync`, die
  Tag-Suche `[bookstack_sync]` findet sie also.
- **Reparaturmeldungen** des gelöschten Eintrags werden automatisch
  entfernt.
- **Der Markdown-Export-Ordner** (Standard `config/bookstack_export/`)
  bleibt; lösche ihn von Hand, falls du den Export genutzt hast.
- **Das API-Token** bleibt in BookStack gültig; widerrufe es unter *My
  Profile → API Tokens*.

## Nicht-Ziele

- **Keine Passwortablage** in BookStack — Zugangsdaten gehören in einen
  richtigen Passwortmanager (Vaultwarden / Bitwarden / 1Password). Die
  Integration schreibt bewusst nirgendwohin Zugangsdaten.
- **Kein bidirektionaler Sync** — Daten fließen nur HA → BookStack.
- **Keine automatische Konfliktauflösung** — manuelle Änderungen im
  automatischen Teil werden erkannt und protokolliert, auflösen musst du
  sie selbst.

## Entwicklung

Das Repo baut auf dem Devcontainer von
[ludeeus/integration_blueprint](https://github.com/ludeeus/integration_blueprint)
auf:

```bash
scripts/develop      # startet HA mit ./config und dieser Integration
scripts/lint         # ruff check + format
pytest tests/        # komplette Testsuite
```

Die CI führt bei jedem Push und PR hassfest, die HACS-Prüfung, ruff,
`mypy --strict` und pytest aus. Beiträge sind willkommen — siehe
[CONTRIBUTING.md](CONTRIBUTING.md) und den
[Verhaltenskodex](CODE_OF_CONDUCT.md).

## Sicherheit

Sicherheitsprobleme bitte vertraulich über GitHubs
[private vulnerability reporting](https://github.com/dibi73/ha-bookstack-sync/security/advisories/new)
melden, nicht in einem öffentlichen Issue. Siehe [SECURITY.md](SECURITY.md).

## Lizenz

MIT — siehe [LICENSE](LICENSE).
