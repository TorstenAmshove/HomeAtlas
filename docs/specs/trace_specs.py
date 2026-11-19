"""Erzeugt docs/specs/traceability.md (welche Route, Tabelle, KI-Werkzeug und Seite in welcher Spec
steht) und den generierten Teil von docs/specs/offene-punkte.md (alle OFFEN-Punkte der Specs).

Aufruf aus dem Repo-Wurzelverzeichnis:

    python docs/specs/trace_specs.py            # traceability.md neu schreiben
    python docs/specs/trace_specs.py --check    # nur prüfen, Exit-Code 1 bei Lücken oder veralteten Dateien

Quellen sind der Code selbst, nicht die Specs: REST-Routen aus contracts/openapi.json (zuvor neu
erzeugen, siehe README.md), WebSocket-Routen und Mounts aus backend/app/main.py, Tabellen aus
backend/app/db.py, Werkzeuge aus backend/app/tools.py, Seiten aus frontend/src/pages/.
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

_PATH_TAIL = r"(?![A-Za-z0-9_/{}.-])"


def routes() -> list[tuple[str, str]]:
    spec = json.loads((SPECS / "contracts" / "openapi.json").read_text(encoding="utf-8"))
    items = [(m.upper(), p) for p, ops in spec["paths"].items() for m in ops]
    main = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    items += [("WS", p) for p in re.findall(r'@app\.websocket\("([^"]+)"\)', main)]
    items += [("MOUNT", p) for p in re.findall(r'app\.mount\("([^"]+)"', main)]
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
