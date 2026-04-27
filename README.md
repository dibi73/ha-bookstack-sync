# BookStack Sync für Home Assistant

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
