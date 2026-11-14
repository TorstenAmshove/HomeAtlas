### Befehle im Issue-Workflow

| Befehl / Label | Wann | Was passiert |
|---|---|---|
| `@claude /grill` | Idee ist noch vage | 1–3 Rückfragen mit Vorschlag. Antworten, dann erneut `/grill`. Am Ende steht eine **Spec** mit Akzeptanzkriterien |
| `@claude /triage` | neues, klares Issue | Labels (Typ, Bereich, Größe, Risiko), Duplikate, Rückfragen |
| `@claude /plan` | Issue ist klar | Umsetzungsplan: Akzeptanzkriterien → Tasks → Tests, von einem unabhängigen Subagent gegengeprüft |
| Label **`status:approved`** | Plan passt | Claude setzt um und öffnet einen PR (nicht bei `needs-human`) |
| `@claude /review` | im PR | Review: Akzeptanzkriterien, Korrektheit, Sicherheit (läuft bei Agenten-PRs automatisch) |
| `@claude <Text>` | jederzeit | freie Frage oder kleiner Auftrag |
| `@claude /help` | jederzeit | diese Übersicht |

**Typischer Weg:** Idee → `/grill` (mehrere Runden) → `/plan` → `status:approved` → PR prüfen → Merge.
Bei klaren Bugs: `/triage` → `/plan` → …

Befehle wirken nur für den Repo-Owner. Zum Ändern eines Plans: Kommentar mit Änderungswunsch, dann erneut `/plan`.
Ausführlich: [docs/ai-workflow/README.md](../blob/master/docs/ai-workflow/README.md)
