"""Erzeugt docs/specs/traceability.md (welche Route, Tabelle, KI-Werkzeug und Seite in welcher Spec
steht, welches ADR welche Constitution-Regel trägt) und prüft, dass jeder `> OFFEN:`-Hinweis unter
docs/specs/ ein Issue verlinkt (`→ #N`). Offene Punkte stehen nur noch als Issues (#253).

Aufruf aus dem Repo-Wurzelverzeichnis:

    python docs/specs/trace_specs.py            # traceability.md neu schreiben
    python docs/specs/trace_specs.py --check    # nur prüfen, Exit-Code 1 bei Lücken oder veralteten Dateien

Quellen sind der Code selbst, nicht die Specs: REST-Routen aus contracts/openapi.json (zuvor neu
erzeugen, siehe README.md), WebSocket-Routen und Mounts aus backend/app/main.py und routes/, Tabellen aus
backend/app/db/*.py, Werkzeuge aus backend/app/tools.py, Seiten aus frontend/src/pages/, ADRs und ihr
Status aus docs/adr/. Eine Lücke ist auch: eine Constitution-Regel verweist auf ein ersetztes oder
fehlendes ADR, oder ein akzeptiertes ADR wird von keiner Regel verwiesen, oder ein `> OFFEN:`-Hinweis
trägt keinen Issue-Verweis.
Nur Standardbibliothek, damit es ohne Backend-Abhängigkeiten läuft.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPECS = ROOT / "docs" / "specs"
CAPS = SPECS / "capabilities"
OUT = SPECS / "traceability.md"
OPEN_NOTE = re.compile(r"(?<!`)>\s*OFFEN:")  # nicht in Inline-Code (`> OFFEN:` in Prosa)
ISSUE_LINK = re.compile(r"→\s*#\d+")
ADRS = ROOT / "docs" / "adr"
CONSTITUTION = SPECS / "constitution.md"
# ADRs ohne eigene Regel in der Constitution: 0001 betrifft nur den Dokumentationsprozess.
ADR_WITHOUT_RULE = {"0001"}

_PATH_TAIL = r"(?![A-Za-z0-9_/{}.-])"


def routes() -> list[tuple[str, str]]:
    spec = json.loads((SPECS / "contracts" / "openapi.json").read_text(encoding="utf-8"))
    items = [(m.upper(), p) for p, ops in spec["paths"].items() for m in ops]
    app_dir = ROOT / "backend" / "app"
    sources = [app_dir / "main.py", *sorted((app_dir / "routes").glob("*.py"))]
    code = "\n".join(p.read_text(encoding="utf-8") for p in sources if p.exists())
    items += [("WS", p) for p in re.findall(r'@(?:app|router)\.websocket\("([^"]+)"\)', code)]
    items += [("MOUNT", p) for p in re.findall(r'app\.mount\("([^"]+)"', code)]
    return sorted(items, key=lambda x: (x[1], x[0]))


def tables() -> list[str]:
    db = "\n".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "backend" / "app" / "db").glob("*.py")))
    return sorted(set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", db)))


def tools() -> list[str]:
    src = (ROOT / "backend" / "app" / "tools.py").read_text(encoding="utf-8")
    block = src.split("TOOL_DEFINITIONS", 1)[1]
    return re.findall(r'^        "name": "(\w+)"', block, flags=re.M)


def pages() -> list[str]:
    return sorted(p.stem for p in (ROOT / "frontend" / "src" / "pages").glob("*.tsx"))


def adrs() -> dict[str, tuple[str, str]]:
    """ADR-Nummer -> (Dateiname, Status-Zeile)."""
    result = {}
    for path in sorted(ADRS.glob("[0-9][0-9][0-9][0-9]-*.md")):
        status = re.search(r"^- \*\*Status:\*\*\s*(.+)$", path.read_text(encoding="utf-8"), flags=re.M)
        result[path.name[:4]] = (path.name, status.group(1).strip() if status else "")
    return result


def constitution_adr_refs() -> dict[str, list[str]]:
    """ADR-Nummer -> Regeln der Constitution (P1, L2, ...), die per Link darauf verweisen."""
    text = CONSTITUTION.read_text(encoding="utf-8")
    refs: dict[str, list[str]] = {}
    for block in re.split(r"(?=^- \*\*\w+ \[)", text, flags=re.M)[1:]:
        rule = re.match(r"- \*\*(\w+) \[", block).group(1)
        block = re.split(r"^## ", block, maxsplit=1, flags=re.M)[0]
        for num in re.findall(r"\]\(\.\./adr/(\d{4})-[^)]*\.md\)", block):
            refs.setdefault(num, [])
            if rule not in refs[num]:
                refs[num].append(rule)
    return refs


def specs() -> dict[str, str]:
    return {p.parent.name: p.read_text(encoding="utf-8") for p in sorted(CAPS.glob("*/spec.md"))}


def unlinked_open_notes(specs_dir: Path = SPECS) -> list[str]:
    """`Datei:Zeile` jedes `> OFFEN:`-Hinweises ohne Issue-Verweis `→ #N`.

    Gesucht wird in allen *.md unter `specs_dir` außer `_template.md`, auch mitten in einer Zeile. Ein
    Hinweis reicht bis zur nächsten Leerzeile oder Überschrift; der Verweis darf in jeder seiner Zeilen
    stehen. Überschriften (`## OFFEN`), Prosa wie „**OFFEN**:“ und Inline-Code sind keine Hinweise."""
    missing = []
    for path in sorted(specs_dir.rglob("*.md")):
        if path.name == "_template.md":
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            match = OPEN_NOTE.search(line)
            if not match:
                continue
            note = [line[match.start():]]
            for nxt in lines[i + 1:]:
                if not nxt.strip() or nxt.lstrip().startswith("#") or OPEN_NOTE.search(nxt):
                    break
                note.append(nxt)
            if not ISSUE_LINK.search(" ".join(note)):
                missing.append(f"{path.relative_to(specs_dir).as_posix()}:{i + 1}")
    return missing


def find(texts: dict[str, str], pattern: re.Pattern[str]) -> list[str]:
    return [name for name, text in texts.items() if pattern.search(text)]


def main() -> int:
    texts = specs()
    sections: list[tuple[str, list[tuple[str, list[str]]]]] = []

    rows = []
    for method, path in routes():
        if method in ("WS", "MOUNT"):
            pat = re.compile(re.escape(path) + _PATH_TAIL)
        else:
            pat = re.compile(rf"\b{method}\b[^\n]*?{re.escape(path)}{_PATH_TAIL}")
        rows.append((f"`{method} {path}`", find(texts, pat)))
    sections.append(("Routen", rows))
    sections.append(("Tabellen", [(f"`{t}`", find(texts, re.compile(rf"\b{t}\b"))) for t in tables()]))
    sections.append(("KI-Werkzeuge", [(f"`{t}`", find(texts, re.compile(rf"\b{t}\b"))) for t in tools()]))
    sections.append(("Seiten", [(f"`{p}`", find(texts, re.compile(rf"\b{p}\b"))) for p in pages()]))

    gaps = [(sec, item) for sec, rows in sections for item, where in rows if not where]
    gaps += [("OFFEN ohne Issue", where) for where in unlinked_open_notes()]

    adr_index = adrs()
    adr_refs = constitution_adr_refs()
    adr_rows = []
    for num in sorted(set(adr_index) | set(adr_refs)):
        name, status = adr_index.get(num, ("", ""))
        rules = adr_refs.get(num, [])
        superseded = status.startswith("Ersetzt")
        if not name:
            problem = "ADR fehlt"
        elif superseded and rules:
            problem = "ersetzt, Regel auf Nachfolger umstellen"
        elif not superseded and not rules and num not in ADR_WITHOUT_RULE:
            problem = "keine Regel verweist darauf"
        else:
            problem = ""
        if problem:
            gaps.append(("ADRs", f"ADR-{num}: {problem}"))
        title = f"[ADR-{num}](../adr/{name})" if name else f"ADR-{num}"
        adr_rows.append((title, status or "–", ", ".join(rules) or "–", f"**{problem}**" if problem else ""))
    lines = [
        "# Abdeckungsmatrix",
        "",
        "> Erzeugt von `python docs/specs/trace_specs.py`, nicht von Hand bearbeiten.",
        "> Quelle der linken Spalte ist der Code; rechts die Capability-Specs, die den Eintrag nennen.",
        "",
        f"Lücken: **{len(gaps)}**",
        "",
    ]
    for sec, rows in sections:
        lines += [f"## {sec} ({len(rows)})", "", "| Eintrag | Spec |", "|---|---|"]
        for item, where in rows:
            links = ", ".join(f"[{w}](capabilities/{w}/spec.md)" for w in where) or "**FEHLT**"
            lines.append(f"| {item} | {links} |")
        lines.append("")
    lines += [
        f"## ADRs in der Constitution ({len(adr_rows)})",
        "",
        "Quelle links sind die Dateien in `docs/adr/`, rechts die Regeln in [constitution.md](constitution.md),",
        "die auf das ADR verlinken.",
        "",
        "| ADR | Status | Regeln | Problem |",
        "|---|---|---|---|",
    ]
    lines += [f"| {t} | {st} | {r} | {pr} |" for t, st, r, pr in adr_rows]
    lines.append("")

    content = "\n".join(lines)

    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != content:
            print("traceability.md veraltet: python docs/specs/trace_specs.py", file=sys.stderr)
            return 1
    else:
        OUT.write_text(content, encoding="utf-8")
    for sec, item in gaps:
        print(f"FEHLT ({sec}): {item}", file=sys.stderr)
    return 1 if gaps else 0


if __name__ == "__main__":
    sys.exit(main())
