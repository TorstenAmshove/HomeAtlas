# Auftrag: Freigegebenen Plan umsetzen

Lies zuerst `.github/claude/common.md` und halte dich daran.

Ein Mensch hat den Plan in diesem Issue freigegeben (Label `status:approved`). Setze **genau diesen
Plan** um: den jüngsten Kommentar, der mit `## Umsetzungsplan` beginnt, plus spätere Kommentare des
Repo-Owners, die ihn ändern.

## Vorab-Prüfungen (abbrechen mit Kommentar, wenn eine fehlschlägt)

- Das Issue hat **nicht** das Label `needs-human`.
- Es gibt einen Umsetzungsplan. Ohne Plan wird nichts improvisiert.
- Labels: `status:approved` → `status:in-progress`.

## Umsetzung

1. Arbeite auf dem Branch, den die Action angelegt hat (`agent/…`). Nie direkt auf `master`.
2. Arbeite die Tasks der Reihe nach ab, jeweils:
   - Test schreiben bzw. anpassen → `cd backend && python -m pytest -q <testdatei>` → muss **rot** sein
   - Implementieren → Test **grün**
   - Haken im Plan gedanklich setzen und mit dem nächsten Task weitermachen
3. Für Aufgaben, die nicht trivial sind, darfst du Subagents (Task-/Agent-Tool) für einzelne Tasks
   einsetzen. Gib ihnen den Task-Text und die betroffenen Dateien mit, nicht das ganze Issue.
4. **Abweichungen vom Plan** sind erlaubt, wenn der Plan sich beim Umsetzen als falsch herausstellt.
   Jede Abweichung kommt in die PR-Beschreibung, mit Grund. Wird es grundlegend anders, hör auf und
   kommentiere im Issue, statt einen anderen Plan umzusetzen.
5. Doku anpassen, wo der Plan es sagt und wo sich Verhalten für Nutzer ändert (`README.md`). Bei
   einer neuen Architekturentscheidung ein neues ADR anlegen (`docs/adr/`).

## Abschluss: alles muss grün sein

```bash
cd backend && ruff check . && python -m pytest -q
cd frontend && npm ci && npm run build      # nur wenn frontend/ geändert wurde
```

Committen mit Conventional Commits (`feat(discovery): …`, `fix(auth): …`). Kleine, sinnvolle Commits.
Den Commit-Typ bewusst wählen, denn `feat`/`fix` lösen beim Merge ein Release aus (siehe `release.yml`).

## Pull Request

Öffne den PR mit `gh pr create --base master --title "<conventional title>" --body-file <datei>`.
Klappt das nicht, poste stattdessen den Link zum Anlegen des PRs als Issue-Kommentar.
PR-Beschreibung:

```
Closes #<N>

## Was
<2–4 Stichpunkte>

## Akzeptanzkriterien
- [x] AK1: <Text> – <wie belegt: Test/Datei/manuell>
- [ ] AK2: <falls nicht erfüllt: warum>

## Abweichungen vom Plan
<oder „keine“>

## Verifikation
- [x] `ruff check` ✔
- [x] `pytest` – <Anzahl> passed
- [x] `npm run build` ✔ / nicht betroffen
- [ ] Manuell zu prüfen: <was ein Mensch sich ansehen sollte>
```

Danach Labels im Issue: `status:in-progress` → `status:in-review`.
