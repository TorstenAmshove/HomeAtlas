# ADR-0012: Lesender WebSocket für Home-Assistant-Traces

- **Status:** Ersetzt durch ADR-0013 (ersetzte ADR-0011)
- **Datum:** 2026-11-22

## Kontext
Für „warum ist das Garagentor zugegangen, was hat die Automation ausgelöst?“ reichen Zustand,
Verlauf und Logbuch nicht: den genauen Trigger und den Ablauf einer Automation liefert Home
Assistant nur über seine WebSocket-API (`trace/list`, `trace/get`), nicht über REST (#99).
ADR-0011 schreibt für Probes „HTTP nur GET“ vor; ein WebSocket passt formal nicht hinein, obwohl
diese beiden Befehle rein lesend sind.

## Entscheidung
Alles aus ADR-0011 gilt unverändert weiter (Lese-/Schreib-Trennung, feste SSH-Befehlsliste, nur
admin-geschützte Routen erreichen schreibende Module, einzige Ausnahme `switch_admin` für
`set_switch`). Neu:
- `probe_auth.py` darf zusätzlich **eine** WebSocket-Verbindung zu Home Assistant öffnen, aber nur
  für die Befehle `trace/list` und `trace/get`. `_ha_ws_call` vergleicht den Typ exakt gegen diese
  Allowlist und wirft sonst `ValueError`; keine Einstellung, kein Parameter und kein Tool kann sie
  erweitern.
- Die TLS-Prüfung ist aus, wie bei allen REST-Clients (selbstsignierte Zertifikate im Heimnetz).
- Traces werden wie Fehlerlog und Logbuch vor dem Kürzen geschwärzt, auf höchstens 10 Läufe bzw.
  16 000 Zeichen begrenzt und nie gespeichert.
- Jede Erweiterung der Allowlist (oder ein schreibender WebSocket-Befehl) braucht ein neues ADR.

## Konsequenzen
- Der Assistent kann Auslöser und Ablauf von Automationen erklären; die Fähigkeitsgrenze bleibt
  lesend. `websockets` ist eine explizite Abhängigkeit (kam bisher nur über `uvicorn[standard]`).
- Ein weiterer Befehlstyp in `_HA_WS_ALLOWED_TYPES` oder ein WebSocket-Aufruf außerhalb von
  `_ha_ws_call` ist ein Fehler, kein Refactoring.
- ADR-0011 hat den Status „Ersetzt durch ADR-0012“.
