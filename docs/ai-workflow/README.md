# KI-gestützter Entwicklungs-Workflow

Ideen, Bugs und Änderungswünsche landen als GitHub-Issues. Claude Code bewertet, plant und setzt sie
um. Ein Mensch entscheidet an zwei Stellen: **Plan freigeben** und **Merge**.

Werkzeuge: GitHub Free + Claude Code über das Claude-Abo (keine API-Kosten). Es wird nichts lokal
installiert, alles läuft über Issues, Kommentare und Labels. Das Prinzip ist Spec-Driven Development:
erst festlegen, woran man „fertig“ erkennt (Akzeptanzkriterien), dann planen, bauen und dagegen prüfen.
Hintergrund und Auswahl der Methoden: [methoden-und-skills.md](methoden-und-skills.md).

## Ablauf

```
Issue über Formular (Bug / Feature / Idee)          status:inbox
  ├─ Idee vage?  @claude /grill   → Rückfragen, mehrere Runden,
  │                                  am Ende Spec mit Akzeptanzkriterien   status:triaged
  ├─ Kommentar  @claude /triage   → Labels, Risiko, Rückfragen      status:triaged
  ├─ Kommentar  @claude /plan     → Plan + Goldfish-Prüfung         status:planned
  ├─ DU: Label  status:approved   → Claude setzt um, öffnet PR      status:in-progress → in-review
  │      (nicht bei needs-human – dort setzt ein Mensch um)
  ├─ PR: Build + Tests + Claude-Review (Akzeptanzkriterien, Code, Sicherheit)
  └─ DU: Merge                    → release.yml erstellt das Release
```

| Befehl / Label | Wo | Was passiert | Workflow / Prompt |
|---|---|---|---|
| `@claude /grill` | Issue-Kommentar, beliebig oft | 1–3 Rückfragen je Runde mit Vorschlag. Wenn alles klar ist, kommt eine Spec mit Akzeptanzkriterien | `claude.yml` → `grill.md` |
| `@claude /triage` | Issue-Kommentar | Duplikate prüfen, Typ/Bereich/Größe/Risiko setzen, Rückfragen | `claude.yml` → `.github/claude/triage.md` |
| `@claude /plan` | Issue-Kommentar | Plan: Akzeptanzkriterien → Tasks → Tests; ein frischer Subagent prüft ihn vor dem Posten | `claude.yml` → `plan.md` |
| Label `status:approved` | Issue | Branch `agent/…`, Umsetzung mit Tests, PR mit `Closes #N` | `claude.yml` → `implement.md` |
| automatisch | PR von `agent/*` | Review: jedes Akzeptanzkriterium einzeln, Korrektheit, Sicherheit | `claude-review.yml` → `review.md` |
| `@claude /review` | PR-Kommentar | dasselbe Review auf Zuruf, für beliebige PRs | `claude-review.yml` |
| `@claude <freier Text>` | Issue/PR | freie Anfrage (Fragen, kleine Fixes) | `claude.yml` (`mention`) |

Alle Befehle wirken **nur für den Repo-Owner**. Das Repo ist öffentlich, Fremde können Issues
anlegen, aber keinen Agenten starten.

### Risikoregel

Berührt ein Vorhaben Auth/2FA/Krypto, schreibenden Gerätezugriff (`*_admin.py`, `remote_admin.py`),
die LLM-Fähigkeitsgrenze (`tools.py`, `mcp_server.py`), Secret-Ausgabe der API, Deployment oder CI,
setzt die Triage `risk:high` + `needs-human`. Claude plant dann nur. Willst du trotzdem automatisch
umsetzen lassen, entferne `needs-human` bewusst, bevor du `status:approved` setzt.

### Kontingent schonen

Jeder Lauf verbraucht Kontingent des Claude-Abos. Darum startet die Triage nicht automatisch, sie
läuft mit Sonnet, und pro Issue läuft immer nur ein Auftrag. Wird das Kontingent knapp, gehen die
Schritte auch von Hand in einer Claude-Code-Sitzung (lokal oder claude.ai/code):
„Lies `.github/claude/plan.md` und plane Issue #N.“

## Einrichtung (einmalig)

1. **Claude GitHub App installieren:** in Claude Code `/install-github-app` ausführen oder
   <https://github.com/apps/claude> öffnen und das Repo auswählen. Wichtig: Nur über den Token der
   App lösen von Claude geöffnete PRs die Build-, Test- und Review-Workflows aus.
2. **Abo-Token anlegen:** einmalig auf einem Rechner mit Claude Code CLI `claude setup-token`
   ausführen (die einzige Stelle, an der etwas außerhalb von GitHub nötig ist) und das Ergebnis unter
   *Settings → Secrets and variables → Actions* als `CLAUDE_CODE_OAUTH_TOKEN` speichern.
3. **Labels anlegen:** *Actions → Labels → Run workflow* (danach automatisch bei Änderungen an
   `.github/labels.yml`). Ohne diesen Schritt ignorieren die Issue-Formulare ihre Labels.
4. **Projekt-Board (optional):** *Projects → New project → Board*, Spalten Inbox, Triaged, Planned,
   Approved, In Progress, In Review, Done. Repo verknüpfen. Unter *Workflows* „Item added to
   project“ für das Repo einschalten. Die Spalten stellst du per Filter auf das `status:`-Label ein
   oder schiebst Karten von Hand.

## Prüfen, ob alles läuft

1. Je Formular ein Test-Issue anlegen → Labels `type:*` und `status:inbox` sind gesetzt.
   Auf das Ideen-Issue `@claude /grill` → Rückfragen. Antworten, erneut `/grill` → Spec-Kommentar.
2. Auf einem Test-Issue „Datum auf der Startseite falsch formatiert“ `@claude /triage` → `risk:low`.
   Auf „2FA abschaltbar machen“ → `risk:high` + `needs-human`.
3. Auf dem ersten Issue `@claude /plan` → Plankommentar mit Abschnitt „Goldfish-Prüfung“.
4. `status:approved` setzen → Fortschrittskommentar, Branch `agent/…`, PR. Build, Test und Review
   laufen auf dem PR.
5. Läuft das Review auf Agenten-PRs nicht an (Job übersprungen), prüfe im Log des Laufs, unter
   welchem Bot-Namen die App pusht, und passe `allowed_bots` in `claude-review.yml` an.

## Bekannte Unsicherheiten

- Dass Claude den PR per `gh pr create` selbst öffnet, steht nicht in der Doku der Action.
  Klappt es nicht, postet Claude einen Link zum Anlegen des PRs, und du klickst ihn.
- Ein Subagent für die Goldfish-Prüfung setzt voraus, dass das Task-/Agent-Tool in der Action
  verfügbar ist. Fehlt es, steht das im Abschnitt „Goldfish-Prüfung“ des Plans. Dann funktioniert der Plan
  trotzdem, nur ohne unabhängige Gegenprüfung. Das Review am PR ist dann der erste fremde Blick.
