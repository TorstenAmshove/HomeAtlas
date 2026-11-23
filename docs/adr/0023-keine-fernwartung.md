# ADR-0023: Keine Fernwartung, einzige Steuerung ist Home-Assistant-Schalten

- **Status:** Akzeptiert, ersetzt ADR-0022
- **Datum:** 2026-11-23

## Kontext
HomeAtlas enthielt eine vollständige Fernwartung: SSH-Schlüssel erzeugen und verteilen, Web-Terminals, Container-
und Proxmox-Steuerung, Geräte-Neustart, dazu Schaltknöpfe für Shelly und Home Assistant. Der Admin nutzt dafür
Portainer, Ansible und die Proxmox-Oberfläche. Jede dieser Funktionen vergrößerte die Angriffsfläche: Zugänge mit
Schreibrechten, Web-Terminal, voller Docker-Socket. HomeAtlas soll ein Werkzeug zum Erkennen und Erklären bleiben
(Issue #217).

## Entscheidung
Alles aus ADR-0022 gilt unverändert weiter (und damit ADR-0021 bis ADR-0013), soweit es lesende Pfade betrifft.
Geändert:
- **HomeAtlas hat keine Fernwartung.** `remote_admin.py`, `docker_admin.py`, `proxmox_admin.py` und
  `routes/remote.py` entfallen ersatzlos, mit ihnen SSH-Schlüssel erzeugen/verteilen, alle Konsolen
  (WebSockets), Container-/Proxmox-Steuerung und -Logs, Geräte-Neustart und die Shelly-/HA-Schaltknöpfe der
  Oberfläche. Verwaltung erfolgt über externe Werkzeuge (Portainer, Ansible, Proxmox), die Oberfläche verlinkt
  sie (Absprung-Links, #216).
- **Die einzige Schreibfähigkeit ist das Schalten über Home Assistant** in `switch_admin.py`: `switch`/`light`
  ein/aus und Rollos der `cover`-Allowlist (open/close/stop), nur über `set_switch` in `tools.py`, für alle Rollen
  und MCP, ohne Rückfrage, mit Zugriffsprotokoll und mit Opt-in „Zum Auslesen verwenden“ am HA-Zugang. Das
  Verhalten ist unverändert (ADR-0013). **Shelly wird nicht mehr direkt geschaltet**; Shelly-Geräte werden weiter
  erkannt und dokumentiert (rein lesend).
- **Erweiterungspunkt:** Weitere Member-Aktionen kommen nativ in HomeAtlas, ausschließlich in `switch_admin.py`,
  sind nur über `tools.py` erreichbar und brauchen je Aktion ein eigenes ADR mit fester Allowlist.
- Bestehende `sshkey`-Zugänge werden für das lesende Probing (`probe_auth.py`, feste Befehlsliste) unverändert
  verwendet. Neue Schlüssel legt der Admin außerhalb an (z. B. per Ansible) und trägt sie als Zugang ein.
- Offen: Docker-Socket nur lesend über einen Socket-Proxy, siehe #101.

## Konsequenzen
- Es gibt keinen Weg mehr, über HomeAtlas einen Befehl auf einem Gerät auszuführen, ein Gerät oder einen
  Container zu steuern oder eine Shell zu öffnen. Der Docker-Socket wird nur noch gelesen (GET).
- Reviewer erkennen Verstöße an einem neuen `*_admin`-Modul, einem Import von `switch_admin` außerhalb von
  `tools.py` oder einer weiteren Aktion in `switch_admin.py` ohne eigenes ADR. `test_removed_routes.py` sichert ab,
  dass die entfallenen Routen und Module nicht zurückkehren.
- Breaking Change (Major-Release): Zugänge, die nur für die Fernwartung angelegt wurden (z. B. SSH-Zugänge mit
  Schreibrechten), kann der Admin löschen.
- ADR-0022 hat den Status „Ersetzt durch ADR-0023“.
