# Methoden und Skills für die KI-gestützte Entwicklung von HomeAtlas

Stand: November 2026. Grundlage ist eine Web-Recherche (Quellen am Ende) und der Ist-Zustand des
Repos.

**Grundannahme:** Gearbeitet wird **nur über GitHub-Issues**, nicht in lokalen Sitzungen. Alles, was nur
interaktiv im Terminal läuft (Plugins, lokal installierte Skills), hilft daher nicht. Die Methoden sind
deshalb als Prompts in `.github/claude/` eingebaut und laufen in der GitHub Action.

**Umgesetzt im Repo:** Spec-Driven Development über Issues (1), grill-me als `@claude /grill` (2),
Goldfish-Prüfung im `/plan` (3), ADRs (4), ruff + Hooks (5), Security-Review im PR (6). Der Ablauf
steht in [README.md](README.md).

## Kurzfassung

| # | Baustein | Wofür | Status |
|---|---|---|---|
| 1 | **Spec-Driven Development** über Issues | erst festlegen, was „fertig“ heißt, dann planen und bauen | **umgesetzt** (Issue = Spec, `/plan`, Review gegen Akzeptanzkriterien) |
| 2 | **grill-me**-Prinzip | vage Ideen per Rückfragen zu einer Spec schärfen | **umgesetzt** als `@claude /grill` |
| 3 | **Elephant/Goldfish** (Google) | Plan von einer frischen Sitzung ohne Vorwissen prüfen lassen | **umgesetzt** in `/plan` |
| 4 | **ADRs** (`docs/adr/`) | Architekturentscheidungen dauerhaft festhalten | **umgesetzt** |
| 5 | **Linter + Hooks** (ruff, tsc) | deterministische Prüfungen statt Bitten in CLAUDE.md | **umgesetzt** |
| 6 | **Security-Review** | Review vor dem Merge mit Blick aufs Bedrohungsmodell | **umgesetzt** in `claude-review.yml` |
| 7 | **to-issues**-Prinzip | große Features in vertikale Slices als Issues zerlegen | teilweise: `/plan` schlägt bei Übergröße Teil-Issues vor |
| 8 | Superpowers, Spec Kit, OpenSpec, BMAD | fertige Frameworks für Spec-Driven Development | **nicht nötig**, siehe Abschnitt 9 |

Wichtigste Regel: **wenige Bausteine, die sich nicht überschneiden.**

---

## 1. Spec-Driven Development: was es ist und wie es hier läuft

Die Idee: **Bevor Code entsteht, wird schriftlich festgelegt, was gebaut wird und woran man erkennt,
dass es fertig ist.** Plan, Code und Review richten sich danach. Ohne Spec rät der Agent, was gemeint
ist. Mit Spec prüft er gegen etwas Festes.

Alle Frameworks folgen im Kern denselben Schritten:

1. **Spec, also das Was und Warum:** Problem, Ziel, Akzeptanzkriterien, Nicht-Ziele. Noch keine Technik.
2. **Plan, also das Wie:** betroffene Dateien, Vorgehen, Risiken.
3. **Tasks:** kleine, einzeln prüfbare Schritte mit Test.
4. **Umsetzung**, danach das **Review gegen die Spec**: Ist jedes Akzeptanzkriterium erfüllt?

So bildet der Issue-Workflow das ab:

| Schritt | In HomeAtlas |
|---|---|
| Spec | Issue-Formular (Problem, Vorschlag, Akzeptanzkriterien), bei vagen Ideen per `/grill` geschärft. Am Ende steht ein `## Spec`-Kommentar |
| Plan + Tasks | `@claude /plan`: übernimmt die Akzeptanzkriterien und ordnet jedem Task ein Kriterium und einen Test zu |
| Freigabe | Label `status:approved` |
| Umsetzung | Claude auf `agent/*`, Test zuerst. Die PR-Beschreibung belegt jedes Akzeptanzkriterium |
| Review | `claude-review.yml` prüft jedes Akzeptanzkriterium einzeln am Code, dazu Korrektheit und Sicherheit |

Die Spec lebt im Issue, nicht als Datei im Repo. Nach dem Merge verweist der PR per `Closes #N`
darauf. Für ein Ein-Personen-Projekt reicht das. Dauerhafte Spec-Dateien (wie bei OpenSpec) lohnen
sich erst, wenn mehrere Leute am selben Verhalten arbeiten.

## 2. grill-me als `@claude /grill`

Das Original (Skill von Matt Pocock) lässt Claude in einer Sitzung **eine Frage nach der anderen**
stellen, jeweils mit einer empfohlenen Antwort, bis alles geklärt ist. Fakten aus dem Code schlägt
Claude selbst nach und fragt nur nach echten Entscheidungen.

Hier läuft dasselbe **asynchron über Kommentare** (`.github/claude/grill.md`):

1. Unter eine vage Idee `@claude /grill` kommentieren.
2. Claude postet die 1–3 wichtigsten offenen Fragen, jede mit Vorschlag und Alternativen.
3. Im Kommentar antworten. „ok“ heißt: Vorschlag angenommen.
4. Wieder `@claude /grill`. Claude liest den ganzen Verlauf und fragt weiter.
5. Ist nichts Wesentliches mehr offen, postet Claude die **Spec** mit Akzeptanzkriterien und
   Nicht-Zielen und setzt `status:triaged`. Danach kommt `/plan`.

Jeder Lauf ist eine frische Sitzung, das Gedächtnis ist der Kommentarverlauf.

## 3. Elephant/Goldfish: der Plan muss für Fremde verständlich sein

Methode von Google (Dave Rensin), seit Oktober 2026 als Open-Source-Plugin:

- **Elephant**: die lange Sitzung mit dem ganzen Kontext. Sie schreibt das Design-Dokument.
- **Goldfish**: eine frische Sitzung ohne Vorwissen. Sie liest **nur** das Dokument und die darin
  genannten Dateien. Versteht sie den Plan nicht oder findet Lücken, geht er zurück an den Elephant.
  Code wird erst geschrieben, wenn der Goldfish den Plan versteht.

**Warum das zu HomeAtlas passt:** Die Umsetzung in der GitHub Action läuft ohnehin in einer frischen
Sitzung, also als Goldfish. Ein Plan, den ein Goldfish nicht versteht, wird auch schlecht umgesetzt.

**Empfehlung:** Das Prinzip ohne Plugin übernehmen. `/plan` lässt nach dem Entwurf einen Subagent
ohne Vorwissen den Plan prüfen: Verständnis, Lücken, Widersprüche zu CLAUDE.md und ADRs. Erst danach
wird der Plan gepostet. Das zusätzliche Plugin ist optional, falls dir das nicht reicht.

## 4. ADRs (Architecture Decision Records)

HomeAtlas hat viele **bewusste** Entscheidungen, die ein Agent leicht „wegrefaktoriert“:
`network_mode: host`, die Trennung von Lese- und Schreibmodulen, kein ORM, kein Vendor-SDK für LLMs,
Topologie als SVG auf dem Server, keine Sampling-Parameter an Anthropic.

Heute steht das in CLAUDE.md und in Modul-Docstrings. ADRs ergänzen das:

- `docs/adr/NNNN-titel.md`, kurz: Kontext → Entscheidung → Konsequenzen → Status.
- **Nie still ändern**, sondern ein neues ADR anlegen, das das alte ablöst. Sonst lügen alte
  Entscheidungen den Agenten an.
- CLAUDE.md bekommt einen Satz: „Vor Architekturänderungen `docs/adr/` lesen. Wer einer Entscheidung
  widerspricht, schlägt ein neues ADR vor statt sie zu umgehen.“
- Für den Anfang reichen 5–7 ADRs, die die vorhandenen Entscheidungen nachträglich festhalten.

## 5. Linter, Typprüfung und Hooks

Was nicht maschinell geprüft wird, ist für einen Agenten nur ein Vorschlag.

- **Backend:** `pytest` (vorhandene Suite) und `ruff` mit kleinem Regelsatz laufen in der CI
  (`test.yml`). Später möglich: mehr ruff-Regeln, `mypy`/`pyright`, schrittweise.
- **Frontend:** `npm run build` (tsc) läuft im Docker-Build. ESLint ist optional.
- **Claude-Code-Hooks** in `.claude/settings.json` (greifen auch in der GitHub Action):
  - `PostToolUse` nach Edit/Write auf `*.py` → `ruff check --fix`, verbleibende Fehler gehen an Claude zurück.
  - `PreToolUse` für `deploy.sh` (ändern oder ausführen) → immer Rückfrage. In der Action heißt das: nein.
  - Faustregel: Was **immer** gelten muss, gehört in einen Hook oder in die CI. CLAUDE.md beschreibt
    Kontext und Gründe.

## 6. Review: Code und Sicherheit

Claude Code hat eingebaute Skills `/code-review` und `/security-review`. Statt sich darauf zu
verlassen, dass sie in der Action verfügbar sind, steckt ihr Inhalt projektspezifisch in
`.github/claude/review.md`: Akzeptanzkriterien, Korrektheit und Sicherheit gegen das Bedrohungsmodell
(README „Sicherheit“, ADRs). Das ist **wichtig für HomeAtlas**, weil das Projekt Zugangsdaten,
SSH-Zugänge und den Docker-Socket verwaltet. Das Review läuft automatisch bei jedem Agenten-PR und
auf `@claude /review` bei jedem anderen.

## 7. Große Vorhaben zerlegen (to-issues-Prinzip)

Der Skill `to-issues` (Matt Pocock) zerlegt einen großen Plan in **vertikale Slices**: kleine Issues,
die jeweils für sich lauffähig sind, quer durch Backend und Frontend statt erst nur Backend. Hier
übernimmt das `/plan`. Ist ein Vorhaben zu groß für einen PR, schlägt es Teil-Issues vor, statt einen
Riesenplan zu schreiben. Die Teil-Issues legst du an, oder du bittest per `@claude` darum.

Ein späterer Ausbau wäre ein `@claude /architecture`, das gelegentlich die Codebasis auf
Refactoring-Bedarf prüft und Vorschläge als Issues anlegt. Vorbild ist `improve-codebase-architecture`.

## 8. Sprach- und Stack-spezifische Skills

Nach meiner Recherche bringen sprachspezifische Skills hier wenig. Die Modelle kennen FastAPI und React
gut. Der Hebel liegt bei **Werkzeugen** (ruff, pytest, tsc) und **projekteigenen Regeln** (CLAUDE.md,
ADRs). Lohnend sind höchstens:

- **frontend-design** (Anthropic-Plugin): für neue Seiten und Redesigns, damit die UI nicht generisch
  aussieht. Ließe sich über das `plugins`-Input der Action einbinden, falls UI-Arbeit häufiger wird.
- **Playwright-Screenshots im PR:** Die Action könnte die App starten und Screenshots geänderter Seiten
  anhängen. Lohnt sich, sobald regelmäßig Frontend-PRs kommen.
- Nicht empfohlen: Sammlungen wie „50 Python-Skills“. Sie überschneiden sich und konkurrieren um
  dieselben Auslöser.

## 9. Fertige Frameworks: bewusst nicht im Einsatz

Alle laufen als Plugins bzw. Slash-Commands in interaktiven Sitzungen. Bei reiner Arbeit über Issues
kommen sie nicht zum Zug, und ihre Methode steckt bereits in den Prompts.

- **Superpowers** (obra): leichtgewichtiges Spec-Driven Development (brainstorming → Spec →
  writing-plans → Umsetzung mit Subagents und TDD). Gute Vorlage, deren Ideen hier übernommen sind:
  Test zuerst, frischer Kontext je Task, Review gegen die Spec. Die alten Dateien unter
  `docs/superpowers/` bleiben als Dokumentation der damaligen Änderung liegen.
- **GitHub Spec Kit**: mächtig, aber viele Dateien und Zeremonie (constitution → specify → plan →
  tasks → implement).
- **OpenSpec**: schlank, mit dauerhaften Spec-Dateien zum aktuellen Verhalten. Interessant, falls
  später mehrere Personen mitarbeiten.
- **BMAD**: simuliert ein ganzes Team aus Rollen. Für ein Ein-Personen-Projekt zu schwer.

Wer doch einmal lokal oder in einer Cloud-Sitzung arbeitet, kann die Prompts dort genauso nutzen:
„Lies `.github/claude/plan.md` und plane Issue #N.“

## 10. Arbeitsweise (unabhängig von Werkzeugen)

- **Ein Issue = eine Sitzung = ein PR.** Frischer Kontext je Aufgabe, keine Mammut-Sitzungen.
- **Kleine PRs.** Was ein Mensch nicht in 10 Minuten reviewen kann, ist zu groß. Dann `to-issues`.
- **Ohne Test nicht fertig.** „Fertig“ heißt: Test grün, Build grün, im Zweifel per Playwright angesehen.
- **CLAUDE.md kurz halten.** Befehle, Grenzen, Verweise. Begründungen gehören in ADRs und Docstrings.
- **Der Mensch reviewt.** Der Agent schreibt schnell, du prüfst bewusst. Die Freigabe des Plans ist das
  billigste Tor.

---

## Wie sich das in den geplanten Workflow einfügt

```
Issue (Formular)
  └─ Idee vage?  → @claude /grill (mehrere Runden) → Spec mit Akzeptanzkriterien
  └─ @claude /triage   → Labels, Risiko, Rückfragen
  └─ @claude /plan     → Plan: Akzeptanzkriterien → Tasks → Tests
                         └─ Goldfish-Check durch einen frischen Subagent
                         └─ groß? → to-issues → Teil-Issues
  └─ status:approved   → Umsetzung Test zuerst, Subagents je Task → PR
  └─ PR                → CI (ruff, pytest, tsc, Docker-Build)
                         + Claude-Review: Akzeptanzkriterien, Korrektheit, Sicherheit
  └─ Merge (du)        → release.yml
```

## Quellen

- grill-me: [Matt Pocock skills (skills.sh)](https://www.skills.sh/mattpocock/skills/write-a-prd), [Substack-Artikel](https://lertechnotes.substack.com/p/stop-letting-claude-code-guess-what), [Openskillindex](https://openskillindex.com/skills/mattpocock-skills-grill-me)
- to-issues / improve-codebase-architecture: [bestofjs](https://bestofjs.org/projects/mattpocock-skills), [aihero.dev](https://www.aihero.dev/skills-post), [skills.sh](https://www.skills.sh/mattpocock/skills/improve-codebase-architecture)
- Elephant/Goldfish: [Google Research](https://research.google/pubs/elephants-goldfish-and-the-new-golden-age-of-software-engineering/), [Google Open Source Blog](https://opensource.googleblog.com/2026/10/introducing-elephant-goldfish-model-plugin.html?m=0), [BetaNews](https://betanews.com/article/google-open-sources-its-elephant-goldfish-model-plugin-for-ai-coding/)
- Superpowers: [Marc Nuri](https://blog.marcnuri.com/superpowers-claude-code-skills-framework), [Quickstart](https://glukhov.org/ai-devtools/superpowers/), [Workflow-Doku](https://mintlify.com/obra/superpowers/concepts/workflow)
- Spec-Driven Development: [OpenSpec vs Spec Kit](https://ovidiueftimie.substack.com/p/openspec-vs-spec-kit), [Spec Kit vs BMAD vs OpenSpec](https://dev.to/willtorber/spec-kit-vs-bmad-vs-openspec-choosing-an-sdd-framework-in-2026-d3j), [Spec Kit vs Kiro vs Claude Code](https://glukhov.org/ai-devtools/ai-coding-assistants/spec-kit-vs-kiro-vs-claude-code/)
- ADRs für Agenten: [BrainGrid](https://www.braingrid.ai/blog/architecture-decision-records-for-ai-coding-agents), [Codeminer42: Stale docs](https://blog.codeminer42.com/stale-docs-are-prompt-injection-you-wrote-yourself/)
- Best Practices, Hooks, vertikale Slices: [OpenHands](https://www.openhands.dev/blog/claude-code-best-practices-agentic-coding), [tw93 Deep Dive](https://tw93.fun/en/2026-03-12/claude.html), [rfxn: Prompts to Pipelines](https://www.rfxn.com/talks/prompts-to-pipelines-v1-5/deck.html)
- Anthropic-Plugins (frontend-design u. a.): [claude.com/plugins](https://claude.com/plugins)
