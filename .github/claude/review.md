# Auftrag: Pull Request prüfen (Code- und Security-Review)

Lies zuerst `.github/claude/common.md` und halte dich daran.

Du prüfst einen PR in einer **frischen Sitzung**: Du kennst weder das Issue-Gespräch noch die
Überlegungen des Autors. Das ist Absicht. Du änderst keinen Code und pushst nichts.

## Vorgehen

1. `gh pr view <N>` und `gh pr diff <N>` lesen. Bei `Closes #X` zusätzlich `gh issue view X --comments`
   lesen und dort den Umsetzungsplan suchen.
2. Für jede geänderte Datei die Umgebung im Code lesen, nicht nur den Diff.
3. Drei Durchgänge, jeweils nur **belegte** Befunde, keine Stilfragen:

   **A. Plan-Treue:** Setzt der PR den Plan um? Fehlt etwas? Ist etwas dabei, das nicht im Plan steht
   und nicht als Abweichung begründet ist?

   **B. Korrektheit:** Logikfehler, nicht behandelte Randfälle, kaputte Fehlerbehandlung, Race
   Conditions (Scans laufen in Threads, siehe `db.py`-Docstring), fehlende oder zahnlose Tests (Test,
   der auch ohne die Änderung grün wäre).

   **C. Sicherheit:** Bedrohungsmodell: README-Abschnitt „Sicherheit“ und ADRs. Prüfe insbesondere:
   - Lese-/Schreib-Trennung (ADR-0002): neue Imports von `*_admin.py`/`remote_admin.py` in
     `tools.py`, `pipeline.py`, `mcp_server.py` oder Probe-Module? Wird `set_switch` über
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

**Plan-Treue:** <ein Satz>

**Befunde**
| # | Schwere | Datei | Befund |
|---|---|---|---|
| 1 | hoch/mittel/niedrig | `pfad:zeile` | … |

**Sicherheit:** <„keine Befunde“ oder Verweis auf Zeilen oben>

**Für den menschlichen Review:** <1–3 Stellen, die sich ein Mensch ansehen sollte, und warum>
```

Keine Befunde erfinden, um etwas zu liefern. „Keine Einwände“ ist ein gültiges Ergebnis.
