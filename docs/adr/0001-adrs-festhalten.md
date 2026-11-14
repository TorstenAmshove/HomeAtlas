# ADR-0001: Architekturentscheidungen als ADRs festhalten

- **Status:** Akzeptiert
- **Datum:** 2026-11-14

## Kontext
HomeAtlas wird zunehmend von KI-Agenten weiterentwickelt (siehe `docs/ai-workflow/`). Bewusste
Entscheidungen standen bisher verstreut in `CLAUDE.md`, der README und Modul-Docstrings. Ein Agent
ohne Gedächtnis sieht eine ungewöhnliche Lösung und „verbessert“ sie – oder schlägt eine längst
verworfene Alternative erneut vor.

## Entscheidung
Architekturentscheidungen werden als nummerierte ADRs in `docs/adr/` festgehalten. Bestehende
Entscheidungen werden nachträglich dokumentiert (ADR-0002 bis -0008). ADRs werden nie still
geändert, sondern durch neue ersetzt. `CLAUDE.md` verweist auf diesen Ordner; die Agent-Prompts
in `.github/claude/` verlangen, die relevanten ADRs vor Plan und Review zu lesen.

## Konsequenzen
- Modul-Docstrings bleiben die Detailquelle („warum ist *dieser Code* so“), ADRs sind die
  Querschnittsübersicht („welche Regeln gelten modulübergreifend“).
- Neue modulübergreifende Regeln gehören in ein ADR, nicht nur in `CLAUDE.md`.
