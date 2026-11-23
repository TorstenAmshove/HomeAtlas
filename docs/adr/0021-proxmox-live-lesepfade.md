# ADR-0021: Lesender Live-Zugriff auf die Proxmox-API für den Assistenten

- **Status:** Akzeptiert, ersetzt ADR-0019
- **Datum:** 2026-11-23

## Kontext
Der Assistent kennt Proxmox-Gäste nur aus dem letzten Scan (`proxmox_probe.py`). Fragen wie „Warum ist die VM
langsam?“ oder „Lief das Backup?“ brauchen den aktuellen Zustand. Das Aufgabenprotokoll eines Gasts gibt es nur
für Admins in `routes/remote.py`. Der Zugriff erweitert die Fähigkeitsgrenze in `tools.py` und braucht deshalb
dieses ADR (Folge von #104, Issue #108).

## Entscheidung
Alles aus ADR-0019 gilt unverändert weiter (und damit ADR-0018 bis ADR-0013). Geändert:
- Neues Modul `proxmox_live.py` nach dem Muster von `unifi_live.py`: ein einziger Netzwerkzugriff `_request`,
  nur GET, feste Pfad-Allowlist: `nodes`, `nodes/{node}/status`, `…/rrddata`, `…/tasks`, die Gästelisten
  `nodes/{node}/qemu` und `…/lxc` (nur zum Auflösen von Name → VMID/Node) sowie `…/{qemu|lxc}/{vmid}/status/current`
  und `…/{qemu|lxc}/{vmid}/rrddata`. Frei wählbar sind nur validierte Pfadteile (Node, Typ, VMID, `hour|day`).
- Zugang: derselbe API-Token wie beim Scan (Konto der Kategorie `proxmox`), zusätzlich muss `allowProbe` gesetzt
  sein. Kein neuer Schalter, kein neuer Konto-Typ. Die README empfiehlt einen eigenen Token mit der Rolle
  PVEAuditor; HomeAtlas kann die Rechte nicht prüfen, die Allowlist im Code ist die eigentliche Sperre.
- Werkzeuge `get_proxmox_guest` und `get_proxmox_node`, nur in `tools.py`. Antworten laufen durch eine
  Feld-Positivliste. Freitext des Gasts (Notizen, Tags, Konfiguration), Aufgaben-Log-Zeilen und UPIDs werden nie
  gelesen oder zurückgegeben. Nichts wird gespeichert.
- `proxmox_live.py` importiert weder ein `*_admin`- noch ein Scan-Modul (auch nicht `proxmox_probe.py`); nur
  `tools.py` importiert es. Der wenige HTTP-Code wird dupliziert statt geteilt, damit Scan und Live-Abfrage
  unabhängig änderbar bleiben und niemand die eine Seite über die andere erweitert.
- `proxmox_admin.py` und `proxmox_probe.py` bleiben unverändert.

## Konsequenzen
- Der Assistent beantwortet Gast- und Host-Fragen live, ohne schreibenden Zugriff auf Proxmox.
- Ein Token mit mehr Rechten als PVEAuditor ist nicht ausgenutzt: Der Code sendet nur GET auf die Allowlist.
- Reviewer erkennen Verstöße an einem neuen Pfad in `_ALLOWED`, einem Import in `proxmox_live.py` oder einem
  zusätzlichen Feld in den Positivlisten.
- `allowProbe` wird wie bei Home Assistant und UniFi-Live in der gemeinsamen Zugangsauswahl
  `tools._pick_account` bei jedem Aufruf geprüft.
- ADR-0019 hat den Status „Ersetzt durch ADR-0021“.
