# BookStack Sync für Home Assistant

> Verfügbar in: **Deutsch** · [English](README.md)
>
> *(Die HA-UI der Integration selbst ist seit v0.12.0 in 28 Sprachen lokalisiert — diese README gibt es in DE + EN.)*

Eine Home-Assistant-Custom-Integration, die dein gesamtes HA-Setup automatisch in
ein bestehendes Book deiner [BookStack](https://www.bookstackapp.com/)-Wiki-Instanz
synchronisiert. Manuell hinzugefügte Inhalte in den Wiki-Pages bleiben dabei
zuverlässig erhalten.

## Status

V0 – funktionales Grundgerüst. Sync von Areas, Devices und Entities funktioniert,
inklusive Marker-Block-Merge mit Hash-Verifikation. Automationen, Skripte und
Add-on-Inhalte folgen in einer späteren Version (siehe `anforderungsdokument.md`).

## Funktionsumfang

- **Daten aus HA**: Areas, Devices (mit Hersteller / Modell / Firmware) und
  Entities (mit aktuellem State) werden über die HA-Registries gelesen.
- **Pages in BookStack**:
  - eine Übersichtsseite mit Statistik
  - eine Page pro Area
  - eine Page pro Device
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
