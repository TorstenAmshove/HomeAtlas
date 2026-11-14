# Auftrag: Issue bewerten (Triage)

Lies zuerst `.github/claude/common.md` und halte dich daran.

Du bewertest ein einzelnes Issue. Du änderst **keinen Code** und legst keine Branches an.

## Schritte

1. Issue lesen: `gh issue view <N> --comments`.
2. **Duplikate prüfen:** `gh issue list --state all --search "<Stichworte>" --limit 20`. Ist es ein
   klares Duplikat, nenne das Original und setze kein `status:triaged`.
3. **Im Code nachsehen**, welche Module betroffen wären (Grep/Read). Rate nicht, wenn du nachsehen kannst.
4. **Labels setzen** (`gh issue edit`):
   - genau ein `type:*` (bug/feature/idea/chore). Passe es an, wenn das Formular falsch gewählt war.
   - ein bis zwei `area:*`
   - `size:S` | `size:M` | `size:L`. `L` heißt: zu groß für einen PR, muss geteilt werden.
   - `risk:low` | `risk:high`, nach der Risikoregel in `common.md`. Bei `risk:high` auch `needs-human`.
   - Status: `status:inbox` → `status:triaged`. Gibt es offene Fragen, ohne die man nicht planen kann,
     bleibt es bei `status:inbox`.
5. **Einen Kommentar** posten (`gh issue comment`) mit genau diesen Abschnitten:

```
### Triage

**Verständnis:** <1–2 Sätze, was gewollt ist – in eigenen Worten>

**Bewertung**
- Nutzen: <hoch/mittel/gering + ein Satz warum>
- Aufwand: <S/M/L + ein Satz warum>
- Risiko: <low/high + welche Module/Regel>
- Betroffene Stellen: `pfad/datei.py` (`funktion`), …

**Offene Fragen** (falls vorhanden; nummeriert, jede mit deinem Vorschlag als Default)
1. …? – Vorschlag: …

**Nächster Schritt:** <z. B. „bereit für `@claude /plan`“ | „bitte Fragen beantworten“ |
„Idee schärfen mit `@claude /grill`“ | „in Teil-Issues zerlegen“>
```

Halte den Kommentar kurz. Ist das Issue vage (typisch `type:idea`), stell keine eigene Fragenliste,
sondern empfiehl `@claude /grill` als nächsten Schritt.
