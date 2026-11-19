# ADR-0011: Lese-/Schreib-Trennung mit Routen-Modulen

- **Status:** Akzeptiert, ersetzt ADR-0002
- **Datum:** 2026-11-19

## Kontext
ADR-0002 legt die harte Trennung von lesenden und schreibenden Modulen fest und nennt als einzigen
Einstieg in die schreibenden Module „admin-geschützte Routen in `main.py`“. Seit #55 stehen die
Routen in `backend/app/routes/` (ein Modul je Fähigkeitsgruppe), `main.py` setzt die App nur noch
zusammen. Seit #56 prüft `set_switch` außerdem, dass ein Shelly-Ziel wirklich ein Shelly ist, und
protokolliert den Auslöser. Ein Agent, der ADR-0002 wörtlich nimmt, sucht die Schreibpfade an der
falschen Stelle und kennt die engere Ausnahme nicht.

## Entscheidung
Übernommen aus ADR-0002, inhaltlich unverändert:
- Lesende und schreibende Module sind getrennte Dateien und importieren einander nicht:
  `docker_probe.py` ↔ `docker_admin.py`, `probe_auth.py` ↔ `remote_admin.py`,
  `proxmox_probe.py` ↔ `proxmox_admin.py`.
- Die SSH-Befehle der Probes stehen als Konstante in `probe_auth._SSH_COMMANDS`; keine Einstellung,
  kein API-Parameter und kein Tool kann sie erweitern. HTTP-Probes nutzen nur GET, TR-064 nur
  `Get*`-Aktionen.

Neu bzw. präzisiert:
- Schreibende Module (`*_admin.py`, `remote_admin.py`) sind nur aus admin-geschützten Routen in
  `backend/app/routes/` erreichbar (heute ausschließlich `routes/remote.py`, jede Route mit
  `require_admin` bzw. Admin-Prüfung der WebSocket-Verbindung) – nie aus `tools.py`,
  `mcp_server.py`, `pipeline.py` oder einem Probe-Modul.
- **Einzige dokumentierte Ausnahme:** `tools.py` importiert `switch_admin.py` für das Tool
  `set_switch` (Shelly-Relais bzw. Home-Assistant-`switch`/`light` an/aus). Das Ziel wird immer
  gegen die Datenbank aufgelöst, nie als freie Adresse vom Modell übernommen: ein Shelly-Befehl nur
  an ein Inventar-Gerät, das `switch_admin.is_shelly` besteht, ein HA-Befehl nur über einen
  hinterlegten Home-Assistant-Zugang. Jeder Vorgang wird mit Auslöser (Benutzer bzw. MCP-Token)
  protokolliert. Jede Erweiterung dieser Ausnahme braucht ein neues ADR.

## Konsequenzen
- Ein neuer Import eines schreibenden Moduls in `tools.py`, `mcp_server.py`, `pipeline.py`, ein
  Probe-Modul oder ein anderes Routen-Modul als `routes/remote.py` ist ein Fehler, kein
  Refactoring – Reviewer weisen ihn zurück. Ein neues Routen-Modul für schreibende Funktionen ist
  erlaubt, wenn jede seiner Routen admin-geschützt ist.
- Gemeinsamer Code zwischen Lese- und Schreibseite wird eher dupliziert als geteilt.
- ADR-0002 hat den Status „Ersetzt durch ADR-0011“.
