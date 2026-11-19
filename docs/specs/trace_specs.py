"""Erzeugt docs/specs/traceability.md (welche Route, Tabelle, KI-Werkzeug und Seite in welcher Spec
steht, welches ADR welche Constitution-Regel trägt) und den generierten Teil von
docs/specs/offene-punkte.md (alle OFFEN-Punkte der Specs).

Aufruf aus dem Repo-Wurzelverzeichnis:

    python docs/specs/trace_specs.py            # traceability.md neu schreiben
    python docs/specs/trace_specs.py --check    # nur prüfen, Exit-Code 1 bei Lücken oder veralteten Dateien

Quellen sind der Code selbst, nicht die Specs: REST-Routen aus contracts/openapi.json (zuvor neu
erzeugen, siehe README.md), WebSocket-Routen und Mounts aus backend/app/main.py und routes/, Tabellen aus
backend/app/db.py, Werkzeuge aus backend/app/tools.py, Seiten aus frontend/src/pages/, ADRs und ihr
Status aus docs/adr/. Eine Lücke ist auch: eine Constitution-Regel verweist auf ein ersetztes oder
fehlendes ADR, oder ein akzeptiertes ADR wird von keiner Regel verwiesen.
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
OPEN = SPECS / "offene-punkte.md"
OPEN_MARKER = "<!-- Ab hier erzeugt von trace_specs.py -->"
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
    db = (ROOT / "backend" / "app" / "db.py").read_text(encoding="utf-8")
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


def open_points(texts: dict[str, str]) -> list[tuple[str, list[str]]]:
    """Die `> OFFEN:`-Punkte aus dem Abschnitt `## OFFEN` jeder Spec, mehrzeilige Punkte zusammengefügt."""
    result = []
    for name, text in texts.items():
        section = re.split(r"^## OFFEN[^\n]*\n", text, maxsplit=1, flags=re.M)
        if len(section) < 2:
            continue
        body = re.split(r"^## ", section[1], maxsplit=1, flags=re.M)[0]
        items: list[str] = []
        for line in body.splitlines():
            if re.match(r"^\s*-\s", line):
                items.append(re.sub(r"^\s*-\s*(>\s*)?(OFFEN:\s*)?", "", line).strip())
            elif line.strip() and items:
                items[-1] += " " + re.sub(r"^\s*>?\s*", "", line).strip()
        result.append((name, [i for i in items if i]))
    return result


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

    points = open_points(texts)
    generated = [OPEN_MARKER, "", f"## Alle Punkte je Fähigkeit ({sum(len(i) for _, i in points)})", ""]
    for name, items in points:
        generated += [f"### [{name}](capabilities/{name}/spec.md) ({len(items)})", ""]
        generated += [f"{n}. {item}" for n, item in enumerate(items, 1)] + [""]
    head = OPEN.read_text(encoding="utf-8").split(OPEN_MARKER, 1)[0] if OPEN.exists() else ""
    open_content = head + "\n".join(generated)
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        current_open = OPEN.read_text(encoding="utf-8") if OPEN.exists() else ""
        if current != content or current_open != open_content:
            print("traceability.md/offene-punkte.md veraltet: python docs/specs/trace_specs.py", file=sys.stderr)
            return 1
    else:
        OUT.write_text(content, encoding="utf-8")
        OPEN.write_text(open_content, encoding="utf-8")
    for sec, item in gaps:
        print(f"FEHLT ({sec}): {item}", file=sys.stderr)
    return 1 if gaps else 0


if __name__ == "__main__":
    sys.exit(main())
