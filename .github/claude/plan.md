# Auftrag: Umsetzungsplan erstellen (mit Goldfish-Prüfung)

Lies zuerst `.github/claude/common.md` und halte dich daran.

Du erstellst einen Plan für ein Issue. Du änderst **keinen Code**, legst keine Branches an und schreibst
keine Dateien. Der Plan wird als Issue-Kommentar gepostet. Erst nach menschlicher Freigabe
(Label `status:approved`) setzt ein **anderer Agent-Lauf ohne dein Gedächtnis** ihn um. Der Plan muss
also für sich allein verständlich sein.

## Schritte

1. Issue samt Kommentaren lesen (`gh issue view <N> --comments`), einschließlich Triage und Antworten.
   Ist Wesentliches offen, schreib Fragen (mit Vorschlag) statt eines Plans und hör auf, oder
   empfiehl `@claude /grill`.
   **Akzeptanzkriterien bestimmen:** Gibt es einen `## Spec`-Kommentar, übernimm dessen
   Akzeptanzkriterien wörtlich. Sonst nimm die aus dem Issue-Formular. Fehlen sie ganz, formuliere
   selbst 2–5 prüfbare Kriterien und kennzeichne sie mit „(vorgeschlagen)“. Sie sind der Maßstab für
   Umsetzung und Review.
2. Code gründlich lesen: betroffene Module, deren Docstrings, ähnliche vorhandene Lösungen, die
   wiederverwendet werden können, und die passenden Tests in `backend/tests/`.
3. **Plan entwerfen** (Format unten). Prinzipien:
   - **Vertikale Slices:** jeder Task liefert etwas Prüfbares, nicht „erst alles Backend“.
   - **Test zuerst:** jeder Backend-Task nennt den Test, der vorher rot und danach grün ist.
   - Bestehende Funktionen wiederverwenden und mit Pfad nennen.
   - Ist das Vorhaben zu groß für einen PR (mehr als ca. 400 geänderte Zeilen oder mehr als ein
     Feature), schlage stattdessen eine Aufteilung in Teil-Issues vor (Titel + je ein Satz).
4. **Goldfish-Prüfung, bevor du postest.** Starte einen Subagent (Task-/Agent-Tool), der **nur** den
   Planentwurf (als Text im Prompt) und das Repo bekommt, **nicht** das Issue und nicht deine Überlegungen.
   Auftrag an ihn:
   > „Du bekommst einen Umsetzungsplan für das Repo im aktuellen Verzeichnis. Du kennst das Ticket
   > nicht. (1) Erkläre in 3–5 Sätzen, was gebaut wird und wie. (2) Liste jede Stelle, an der du beim
   > Umsetzen raten müsstest. (3) Prüfe den Plan gegen `CLAUDE.md` und `docs/adr/` und nenne
   > Widersprüche. (4) Nenne fehlende Tests oder Randfälle. (5) Gibt es ein Akzeptanzkriterium,
   > das kein Task abdeckt oder das sich nicht prüfen lässt? Antworte knapp als Liste.“

   Vergleiche seine Zusammenfassung mit deiner Absicht. Überarbeite den Plan, bis keine wesentlichen
   Ratestellen oder Widersprüche übrig sind (höchstens 2 Runden). Was offen bleibt, kommt unter
   „Offene Punkte“.
5. Plan als **einen** Kommentar posten. Labels: `status:triaged`/`status:inbox` → `status:planned`.
   Ist das Issue `risk:high`, steht oben im Plan:
   „⚠️ risk:high – Umsetzung nur durch einen Menschen oder nach ausdrücklicher Entfernung von `needs-human`.“

## Format

```
## Umsetzungsplan

**Ziel:** <ein Satz>
**Ansatz:** <2–4 Sätze, inkl. warum dieser Weg und nicht der naheliegende andere>
**Risiko:** <low/high> – <Begründung>
**Betroffene Dateien:** `…`, `…`
**Wiederverwendet:** `pfad::funktion` – wofür

### Akzeptanzkriterien
- [ ] AK1: <prüfbar> – geprüft durch Task <n> / Test `…`
- [ ] AK2: …

### Tasks
- [ ] **1. <Titel>**
  - Erfüllt: AK<n>
  - Test: `backend/tests/test_….py::test_…` – <was er prüft>
  - Änderung: <konkret, mit Datei und Funktion>
- [ ] **2. …**

### Doku
<README/CLAUDE.md/ADR – was angepasst werden muss, oder „keine“>

### Verifikation
- `cd backend && python -m pytest -q`
- `cd frontend && npm run build`
- <manueller Check, falls UI: welche Seite, was sollte man sehen>

### Goldfish-Prüfung
<1–2 Sätze: was der unabhängige Leser verstanden hat und was daraufhin geändert wurde>

### Offene Punkte
<oder „keine“>

---
Freigeben mit Label `status:approved`. Änderungswünsche als Kommentar, dann erneut `@claude /plan`.
```
