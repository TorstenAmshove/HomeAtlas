# ADR-0022: Live-Status lokaler Docker-Container für den Assistenten, ohne Inspect

- **Status:** Ersetzt durch ADR-0023 (ersetzte ADR-0021)
- **Datum:** 2026-11-23

## Kontext
Für Docker-Container kennt der Assistent nur den Stand des letzten Scans (`list_containers`). Auf „Warum geht
Jellyfin nicht?“ kann er weder Exit-Code noch Neustart-Schleife oder Health nennen und dem Member nicht sagen, was
der Admin wissen muss (Issue #218). Das neue Werkzeug erweitert die Fähigkeitsgrenze in `tools.py` und braucht
deshalb dieses ADR.

## Entscheidung
Alles aus ADR-0021 gilt unverändert weiter (und damit ADR-0019 bis ADR-0013). Geändert:
- Neues Lese-Werkzeug `get_container_status`, nur in `tools.py`. Quelle ist die neue Funktion
  `docker_probe.live_containers()` mit genau einer Anfrage: `GET /containers/json?all=1`.
- **Kein Inspect** (`GET /containers/{id}/json`). Inspect liefert `Config.Env` im Klartext (mögliche Geheimnisse),
  und ein Socket-Proxy kann Env nicht herausfiltern. Ohne Inspect erreicht Env HomeAtlas auf diesem Pfad nie, und
  ein Proxy (#101) kann `/containers/{id}/json` komplett sperren. `RestartCount` und `OOMKilled` entfallen
  bewusst; Exit-Code 137 deutet auf ein OOM hin, „Restarting“ steht im Status.
- Feld-Positivliste: Name, Image (ohne `user:pass@`), State, Status-Text, daraus Exit-Code mit Einordnung, Health,
  „seit“ und Compose-Projekt. Command, Env, Mounts, Ports und alle anderen Labels werden nie kopiert.
- Nur der **lokale** Docker-Host. Entfernte Hosts bleiben beim Stand des Scans. Keine Logs, keine Steuerung.
- Der Filterwert wird nur gegen die Live-Liste verglichen, nie in einen API-Pfad eingesetzt. Höchstens 50 Container
  pro Antwort, Kürzung wird angezeigt.
- Das Werkzeug steht allen Rollen und MCP-Clients offen (wie `get_proxmox_*`). Das Opt-in je Zugang (L3) greift
  nicht, weil es kein Konto gibt; der Socket-Mount ist die Entscheidung des Betreibers.
- `docker_probe.py` ist neben `unifi_live` und `proxmox_live` die dritte lesende Quelle, die `tools.py` importieren
  darf. `docker_admin.py` bleibt unerreichbar (ADR-0002, ADR-0011). Die bestehende `probe()` (DynDNS liest Env per
  Inspect) bleibt unberührt und ist nicht aus `tools.py` erreichbar.
- Die Prompt-Regel in `prompts.py` verlangt, bei nicht selbst behebbaren Fällen die Ursache zu erklären, zu sagen,
  dass der Admin handeln muss, und eine Nachricht an ihn zu formulieren; nie wird etwas als ausgeführt behauptet.

## Konsequenzen
- Der Assistent erklärt Container-Ausfälle live, ohne schreibenden Zugriff und ohne Env-Werte zu sehen.
- Reviewer erkennen Verstöße an einem zweiten Pfad in `live_containers`, einer anderen Methode als GET oder einem
  zusätzlichen Feld in `_live_row`/`_CONTAINER_FIELDS`; Tests in `test_docker_probe.py` sichern das ab.
- Ein Socket-Proxy (#101) braucht für den Assistenten nur `GET /containers/json`.
- ADR-0021 hat den Status „Ersetzt durch ADR-0022“.
