# Auftrag: Idee schärfen (asynchrones „grill-me“)

Lies zuerst `.github/claude/common.md` und halte dich daran.

Das Issue ist noch zu vage zum Planen. Du klärst es im Dialog über Kommentare. Jeder Lauf ist eine
frische Sitzung, dein Gedächtnis ist der Kommentarverlauf. Du änderst **keinen Code**.

## Schritte

1. Issue samt aller Kommentare lesen: `gh issue view <N> --comments`. Frühere `### Rückfragen`-Runden
   und die Antworten des Owners darauf sind beschlossene Sache. Frag sie nicht erneut.
   Antwortet der Owner nur mit „ok“ oder lässt eine Frage aus, gilt dein Vorschlag als angenommen.
2. **Fakten selbst nachsehen** (Grep/Read), statt sie zu erfragen. Wie etwas heute funktioniert, wo
   es im Code steht, ob es Ähnliches schon gibt: das ist deine Aufgabe, nicht die des Owners.
3. Prüfe, was für eine planbare Spec noch fehlt:
   - Welches Problem für wen, in welcher Situation?
   - Was genau soll passieren (Verhalten aus Sicht des Nutzers)?
   - Woran erkennt man, dass es fertig ist (prüfbare Akzeptanzkriterien)?
   - Was ausdrücklich **nicht** (Nicht-Ziele, Grenzen)?
   - Gibt es Konflikte mit ADRs, mit dem Sicherheitsmodell oder mit bestehendem Verhalten?
4. **Sind noch Entscheidungen offen:** Poste die **1–3 wichtigsten** als Kommentar. Am wichtigsten ist,
   was die Richtung am stärksten verändert. Keine Fragen auf Vorrat.

```
### Rückfragen (Runde <n>)

<ein Satz: was bisher feststeht>

1. **<Frage>?**
   Vorschlag: <deine Empfehlung> – weil <kurzer Grund>.
   Alternativen: <a> / <b>
2. …

Antworte einfach im Kommentar („1 ok, 2: lieber …“), dann erneut `@claude /grill`.
```

5. **Ist nichts Wesentliches mehr offen:** Poste die Spec und setze Labels: `status:inbox` → `status:triaged`,
   dazu `type:feature` statt `type:idea`, wenn es jetzt ein konkretes Vorhaben ist. Fehlen `area:*`, `size:*`
   oder `risk:*`, setze sie nach den Regeln in `triage.md`.

```
## Spec

**Problem:** <für wen, in welcher Situation>
**Ziel:** <ein Satz>

**Verhalten**
- <aus Sicht des Nutzers, konkret>

**Akzeptanzkriterien**
- [ ] AK1: <prüfbar formuliert>
- [ ] AK2: …

**Nicht-Ziele**
- …

**Entscheidungen aus der Diskussion**
- <Frage> → <Entscheidung>

---
Bereit für `@claude /plan`.
```
