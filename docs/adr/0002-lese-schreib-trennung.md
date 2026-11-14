# ADR-0002: Harte Trennung von lesenden und schreibenden Modulen

- **Status:** Akzeptiert (nachträglich dokumentiert)
- **Datum:** 2026-11-14

## Kontext
HomeAtlas meldet sich mit hinterlegten Zugangsdaten an Geräten an (SSH, HTTP, TR-064, Docker-API,
Proxmox). Dieselben Zugänge könnten Geräte auch verändern. Ein lesender Pfad, der über einen
Import oder einen zusätzlichen Parameter schreibend wird, wäre eine Fernsteuerung mit hübscher
Oberfläche – erreichbar auch für das LLM.

## Entscheidung
- Lesende und schreibende Module sind getrennte Dateien und importieren einander nicht:
  `docker_probe.py` ↔ `docker_admin.py`, `probe_auth.py` ↔ `remote_admin.py`,
  `proxmox_probe.py` ↔ `proxmox_admin.py`.
- Schreibende Module (`*_admin.py`, `remote_admin.py`) sind nur aus admin-geschützten Routen in
  `main.py` erreichbar – nie aus `tools.py`, `mcp_server.py`, `pipeline.py` oder einem Probe-Modul.
- Die SSH-Befehle der Probes stehen als Konstante in `probe_auth._SSH_COMMANDS`; keine Einstellung,
  kein API-Parameter und kein Tool kann sie erweitern. HTTP-Probes nutzen nur GET, TR-064 nur
  `Get*`-Aktionen.
- **Einzige dokumentierte Ausnahme:** `tools.py` importiert `switch_admin.py` für das Tool
  `set_switch` (Shelly-Relais bzw. Home-Assistant-`switch`/`light` an/aus). Bewusste
  Produktentscheidung, siehe Docstrings von `tools.py` und `switch_admin.py`. Jede Erweiterung
  dieser Ausnahme braucht ein neues ADR.

## Konsequenzen
- Ein neuer Import eines schreibenden Moduls in `tools.py`, `mcp_server.py`, `pipeline.py` oder
  ein Probe-Modul ist ein Fehler, kein Refactoring – Reviewer weisen ihn zurück.
- Gemeinsamer Code zwischen Lese- und Schreibseite wird eher dupliziert als geteilt.
