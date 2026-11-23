# Auftrag: Pull Request prüfen (Code- und Security-Review)

Lies zuerst `.github/claude/common.md` und halte dich daran.

Du prüfst einen PR in einer **frischen Sitzung**: Du kennst weder das Issue-Gespräch noch die
Überlegungen des Autors. Das ist Absicht. Du änderst keinen Code und pushst nichts.

## Vorgehen

1. `gh pr view <N>` und `gh pr diff <N>` lesen. Bei `Closes #X` zusätzlich `gh issue view X --comments`
   lesen und dort die Akzeptanzkriterien suchen: im Umsetzungsplan, sonst im `## Spec`-Kommentar,
   sonst im Issue-Formular.
2. Für jede geänderte Datei die Umgebung im Code lesen, nicht nur den Diff.
3. Drei Durchgänge, jeweils nur **belegte** Befunde, keine Stilfragen:

   **A. Spec-Treue:** Prüfe **jedes Akzeptanzkriterium einzeln** am Code und an den Tests, nicht an
   der PR-Beschreibung: erfüllt, teilweise erfüllt oder nicht erfüllt? Ist etwas dabei, das weder im
   Plan steht noch als Abweichung begründet ist? Ändert der PR Verhalten, ohne die betroffene
   Spec unter `docs/specs/capabilities/` anzupassen, ist das ein Befund – auch bei bestehenden
   Routen, denn das prüft keine Maschine. `python docs/specs/trace_specs.py --check` ausführen; die
   Abdeckung und die Aktualität der Verträge prüft zusätzlich der CI-Workflow `specs.yml`.

   **B. Korrektheit:** Logikfehler, nicht behandelte Randfälle, kaputte Fehlerbehandlung, Race
   Conditions (Scans laufen in Threads, siehe `db.py`-Docstring), fehlende oder zahnlose Tests (Test,
   der auch ohne die Änderung grün wäre).

   **C. Sicherheit:** Bedrohungsmodell: README-Abschnitt „Sicherheit“ und ADRs. Prüfe insbesondere:
   - Lese-/Schreib-Trennung (ADR-0011): neue `*_admin.py`-Module (HomeAtlas hat keine Fernwartung, ADR-0023) oder
     Imports von `switch_admin` in `pipeline.py`, `mcp_server.py` oder Probe-Modulen (nur `tools.py` darf es)? Wird `set_switch` über
     „an/aus für switch/light“ hinaus erweitert?
   - Kann über `tools.py`/MCP jetzt etwas verändert oder ein Secret gelesen werden?
   - Neue oder geänderte API-Routen: hängen sie an `current_user` bzw. `require_admin`? Ist eine
     Admin-Seite im Frontend **und** im Backend geschützt?
   - Secrets: Kommen Passwörter/Tokens in Antworten, Logs, Doku, Prompts oder Chatverlauf?
     Wird `crypto.encrypt` für neue Credentials genutzt?
   - Kommandos: `create_subprocess_exec` mit Argumentliste statt Shell? Werden Hostnamen/IPs validiert?
     Wurde die Allowlist `probe_auth._SSH_COMMANDS` verändert?
   - Neue Abhängigkeiten: nötig, gepflegt, gepinnt?

4. Inline-Kommentare für konkrete Stellen (`mcp__github_inline_comment__create_inline_comment` mit
   `confirmed: true`), dann **ein** Gesamtkommentar (`gh pr comment`):

```
## Claude-Review

**Ergebnis:** ✅ keine Einwände | ⚠️ Anmerkungen | ❌ Änderungen nötig

**Akzeptanzkriterien**
| AK | Ergebnis | Beleg |
|---|---|---|
| AK1 | ✅ / ⚠️ teilweise / ❌ | `test_…` bzw. `pfad:zeile` |

**Befunde**
| # | Schwere | Datei | Befund |
|---|---|---|---|
| 1 | hoch/mittel/niedrig | `pfad:zeile` | … |

**Sicherheit:** <„keine Befunde“ oder Verweis auf Zeilen oben>

**Für den menschlichen Review:** <1–3 Stellen, die sich ein Mensch ansehen sollte, und warum>
```

Keine Befunde erfinden, um etwas zu liefern. „Keine Einwände“ ist ein gültiges Ergebnis.
