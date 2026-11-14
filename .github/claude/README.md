# Agent-Prompts

Versionierte Anweisungen für `anthropics/claude-code-action` (siehe `.github/workflows/claude*.yml`).
Die Workflows übergeben nur „lies Datei X und bearbeite Issue/PR #N“. Der eigentliche Prompt liegt hier,
damit Änderungen am Verhalten des Agenten als normale Diffs reviewbar sind.

| Datei | Auslöser | Darf |
|---|---|---|
| `help.md` | Kommentar `@claude /help` | wird ohne Modellaufruf als Kommentar gepostet (Befehlsübersicht) |
| `common.md` | wird von allen anderen eingebunden | — |
| `grill.md` | Kommentar `@claude /grill` (nur Repo-Owner), beliebig oft | Rückfragen stellen, am Ende Spec posten, Labels setzen |
| `triage.md` | Kommentar `@claude /triage` (nur Repo-Owner) | Issue lesen, kommentieren, Labels setzen |
| `plan.md` | Kommentar `@claude /plan` (nur Repo-Owner) | Code lesen, Plan als Kommentar posten, Labels setzen |
| `implement.md` | Label `status:approved` (nur Repo-Owner, nicht bei `needs-human`) | Branch, Code, Tests, PR |
| `review.md` | PR von einem `agent/*`-Branch oder Kommentar `@claude /review` | PR lesen und kommentieren |

Ablauf und Hintergrund: `docs/ai-workflow/README.md`.
