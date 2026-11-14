# Methoden und Skills für die KI-gestützte Entwicklung von HomeAtlas

Stand: November 2026. Grundlage ist eine Web-Recherche (Quellen am Ende) und der Ist-Zustand des
Repos. HomeAtlas nutzt bereits **Superpowers**, zu erkennen an `docs/superpowers/specs` und
`docs/superpowers/plans`. Die Empfehlungen bauen darauf auf, statt ein zweites Framework daneben
zu stellen.

**Umgesetzt im Repo:** Goldfish-Prüfung im `/plan` (3), ADRs (4), ruff + Hooks (5), Security-Review
im PR (6). Der Ablauf ist in [README.md](README.md) beschrieben. grill-me (2) installierst du lokal.

## Kurzfassung: Was ich empfehle

| # | Baustein | Wofür | Aufwand | Empfehlung |
|---|---|---|---|---|
| 1 | **Superpowers** (obra) | Brainstorming → Spec → Plan → Umsetzung mit Subagents, TDD, Debugging | schon im Einsatz | **behalten, als Rückgrat** |
| 2 | **grill-me** (Matt Pocock) | vage Ideen vor dem Plan hart hinterfragen | 1 Befehl | **ja**, für Ideen-Issues |
| 3 | **Elephant/Goldfish** (Google) | Plan von einer frischen Sitzung ohne Vorwissen prüfen lassen | gering | **ja, als Prinzip** im Workflow |
| 4 | **ADRs** (`docs/adr/`) | Architekturentscheidungen dauerhaft festhalten | einmalig ca. 1 h | **ja** |
| 5 | **Linter + Hooks** (ruff, tsc) | deterministische Prüfungen statt Bitten in CLAUDE.md | gering | **ja** |
| 6 | **Eingebaute Skills** `/code-review`, `/security-review`, `/simplify` | Review vor dem Merge | keiner | **ja**, im PR-Review |
| 7 | **to-issues** (Matt Pocock) | große Features in vertikale Slices als Issues zerlegen | 1 Befehl | optional, bei großen Features |
| 8 | **frontend-design** (Anthropic) | bessere UI-Entwürfe für React-Seiten | 1 Befehl | optional |
| 9 | Spec Kit / OpenSpec / BMAD | eigenes Spec-Driven-Framework | hoch | **nein**, überschneidet sich mit Superpowers |

Wichtigste Regel: **wenige Skills, die sich nicht überschneiden.** Skills mit ähnlicher Beschreibung
konkurrieren um denselben Auslöser. Dann ist schwer vorherzusagen, welcher läuft.

---

## 1. Superpowers: das Rückgrat

Superpowers ist ein Satz zusammenspielender Skills für den ganzen Entwicklungszyklus:

- `brainstorming`: stellt Rückfragen und schreibt eine Design-Spec nach `docs/superpowers/specs/`.
- `writing-plans`: macht daraus einen Plan mit abhakbaren Tasks (`docs/superpowers/plans/`).
- `subagent-driven-development`: startet je Task einen frischen Subagent. Dann folgt ein Review in zwei
  Stufen: erst „passt es zur Spec?“, dann „ist der Code gut?“.
- `test-driven-development`: Red → Green → Refactor.
- `systematic-debugging`, `verification-before-completion`: gegen „sollte jetzt gehen“.

**Einordnung in den Issue-Workflow:**
`@claude /plan` erzeugt Spec und Plan nach dem Superpowers-Schema. Nach `status:approved` setzt Claude den
Plan mit `subagent-driven-development` um. Spec und Plan liegen im PR mit im Repo und sind damit
gleichzeitig die Dokumentation der Änderung.

Das **ist** bereits Spec-Driven Development. Deshalb rate ich von Spec Kit, OpenSpec oder BMAD ab
(Abschnitt 9).

## 2. grill-me: Ideen hart hinterfragen

Der Skill lässt Claude **eine Frage nach der anderen** stellen, jeweils mit einer empfohlenen Antwort.
Das geht so lange, bis ihr euch verstanden habt. Fakten, die im Code stehen, schlägt Claude selbst nach.
Dich fragt es nur nach echten Entscheidungen.

- Sinnvoll bei `type:idea`-Issues, die nur aus einem Satz bestehen („Fritzbox-Integration wäre cool“).
- Überschneidung: Superpowers-`brainstorming` stellt auch Rückfragen, aber milder. grill-me ist für
  die Fälle, in denen du selbst noch nicht weißt, was du willst.
- Einsatz: lokal oder in einer Cloud-Session, nicht in der GitHub Action, denn es braucht einen Dialog.
  Das Ergebnis kommt als Kommentar ins Issue. Danach folgt `/plan`.
- Installation: `npx skills add https://github.com/mattpocock/skills --skill grill-me`

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

Heute gibt es weder Tests noch Linter. Was nicht maschinell geprüft wird, ist für einen Agenten nur ein
Vorschlag.

- **Backend:** `ruff` (Lint + Format) und `pytest`. Optional `mypy` oder `pyright`, schrittweise.
- **Frontend:** `npm run build` (tsc) gibt es schon. ESLint ist optional.
- **Claude-Code-Hooks** in `.claude/settings.json`:
  - `PostToolUse` nach Edit/Write auf `*.py` → `ruff format` + `ruff check --fix` für die Datei.
  - `PreToolUse`-Schutz: Änderungen an `deploy.sh` und die Ausführung von `deploy.sh` blockieren.
  - Faustregel: Was **immer** gelten muss, gehört in einen Hook oder in die CI. CLAUDE.md beschreibt
    Kontext und Gründe.

## 6. Eingebaute Skills für das Review

Gibt es in Claude Code bereits, ohne Installation:

- `/code-review`: sucht Fehler in der Logik. Läuft im Review-Job jedes Agenten-PRs.
- `/security-review`: **wichtig für HomeAtlas**. Das Projekt verwaltet Zugangsdaten, SSH-Zugänge und den
  Docker-Socket. Pflicht bei Issues mit `risk:high`, sinnvoll bei allen PRs.
- `/simplify`: räumt auf (Wiederverwendung, Vereinfachung). Gelegentlich nutzen, nicht automatisch.

## 7. to-issues / to-prd (Matt Pocock), optional

- `to-issues` zerlegt einen großen Plan in **vertikale Slices**: kleine Issues, die jeweils für sich
  lauffähig sind, quer durch Backend und Frontend statt erst nur Backend. Das passt gut zum Issue-Workflow
  und hält PRs klein.
- `improve-codebase-architecture`: hin und wieder ein Architektur-Check, der Refactoring-Vorschläge als
  Issues anlegt. Er liest ADRs, wenn welche da sind.
- Ohne Bedarf weglassen. `writing-plans` aus Superpowers deckt Features mittlerer Größe ab.

## 8. Sprach- und Stack-spezifische Skills

Nach meiner Recherche bringen sprachspezifische Skills hier wenig. Die Modelle kennen FastAPI und React
gut. Der Hebel liegt bei **Werkzeugen** (ruff, pytest, tsc) und **projekteigenen Regeln** (CLAUDE.md,
ADRs). Lohnend sind höchstens:

- **frontend-design** (Anthropic-Plugin): für neue Seiten und Redesigns, damit die UI nicht generisch
  aussieht.
- **Playwright** (vorinstalliert in Cloud-Sessions) bzw. der `/run`-Skill: Claude startet die App und
  sieht sich die Änderung im Browser an, statt nur den Build zu prüfen.
- Nicht empfohlen: Sammlungen wie „50 Python-Skills“. Sie überschneiden sich und konkurrieren um
  dieselben Auslöser.

## 9. Bewusst nicht empfohlen

- **GitHub Spec Kit**: mächtig, aber viele Dateien und Zeremonie (constitution → specify → plan →
  tasks → implement). Doppelt sich mit Superpowers.
- **OpenSpec**: schlanker als Spec Kit, doppelt sich aber ebenfalls mit Superpowers. Erst interessant,
  wenn du Superpowers aufgibst.
- **BMAD**: simuliert ein ganzes Team aus Rollen (PM, Architekt, Scrum Master). Für ein
  Ein-Personen-Projekt zu schwer.

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
  └─ Idee vage?  → grill-me (lokal/Cloud-Session) → Ergebnis als Kommentar
  └─ @claude /triage   → Labels, Risiko, Rückfragen
  └─ @claude /plan     → Superpowers: Spec + Plan
                         └─ Goldfish-Check durch einen frischen Subagent
                         └─ groß? → to-issues → Teil-Issues
  └─ status:approved   → Superpowers: subagent-driven-development + TDD → PR
  └─ PR                → CI (ruff, pytest, tsc, Docker-Build)
                         + /code-review (+ /security-review bei risk:high)
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
