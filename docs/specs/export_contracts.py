"""Erzeugt die maschinell gewonnenen Verträge unter docs/specs/contracts/ direkt aus dem Code.

Braucht die Backend-Abhängigkeiten (backend/requirements.txt). Aufruf aus dem Repo-Wurzelverzeichnis:

    python docs/specs/export_contracts.py

Schreibt:
- contracts/openapi.json   REST-API aus FastAPI
- contracts/llm-tools.json KI-Werkzeuge exakt so, wie das Modell sie sieht (Name, Beschreibung, Schema)
- contracts/catalogs.json  feste Kataloge, die eine Alternative übernehmen kann: Port-Katalog,
                           Port-Hinweise, kuratierte Hersteller-Doku-Links, OUI-Fallback,
                           verbotene Passwörter, Wortliste für Erstpasswörter

Die Datenbank- und Schlüsselpfade zeigen auf ein Temp-Verzeichnis, damit nichts Echtes angefasst wird.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "specs" / "contracts"


def _dump(name: str, data: object) -> None:
    (OUT / name).write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(f"geschrieben: contracts/{name}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="homeatlas-specs-"))
    os.environ.setdefault("HOMEATLAS_DB_PATH", str(tmp / "specs.db"))
    os.environ.setdefault("HOMEATLAS_KEY_PATH", str(tmp / "specs.key"))
    sys.path.insert(0, str(ROOT / "backend"))

    from app import auth, oui, ports, security, tools, vendor_docs  # noqa: E402
    from app.main import app  # noqa: E402

    _dump("openapi.json", app.openapi())
    _dump("llm-tools.json", tools.TOOL_DEFINITIONS)
    _dump("catalogs.json", {
        "ports.services": {str(port): {"name": name, "description": desc}
                           for port, (name, desc) in sorted(ports.SERVICES.items())},
        "ports.deviceHints": {str(port): list(hint) for port, hint in sorted(ports.DEVICE_HINTS.items())},
        "vendorDocs.curated": [{"match": list(keys), "title": title, "url": url}
                               for keys, title, url in vendor_docs.CURATED],
        "oui.fallback": dict(sorted(oui._FALLBACK.items())),
        "passwordPolicy.forbidden": sorted(security._OBVIOUS),
        "passwordPolicy.passphraseLength": security.PASSPHRASE_LENGTH,
        "initialPassword.words": list(auth._WORDS),
    })
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
