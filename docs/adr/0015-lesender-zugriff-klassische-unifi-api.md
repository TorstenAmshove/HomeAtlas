# ADR-0015: Lesender Live-Zugriff auf die klassische UniFi-API

- **Status:** Ersetzt durch ADR-0016; ersetzte ADR-0014
- **Datum:** 2026-11-22

## Kontext
Der Assistent soll für die Fehleranalyse (#104, „Warum hat Client xy Verbindungsprobleme?“) live
UniFi-Daten lesen. Die Integration API (`unifi_probe.py`) liefert weder Signal, Retries noch
Roaming noch Events. ADR-0014 verlangt für die klassische API einen Login-POST und verbietet, dass
Quellmodule von `tools.py` importiert werden.

Spike gegen UniFi Network 11.0.103 (Header `X-API-Key`, Basis `/proxy/network`):

| Endpunkt | Methode | Status | Nutzen |
|---|---|---|---|
| `api/s/<site>/stat/sta` | GET | 200 | Clients inkl. Funkwerte (`signal`, `rssi`, `noise`, `tx_retries`, `wifi_tx_retries_percentage`, `tx_retry_burst_count`, `roam_count`, `ap_mac`, `essid`, `channel`) |
| `api/s/<site>/stat/device` | GET | 200 | Geräte (enthält Geheimnisse wie `x_authkey`, `x_aes_gcm`, `guest_token`) |
| `api/s/<site>/stat/health` | GET | 200 | WAN/LAN/WLAN/VPN |
| `v2/api/site/<site>/firewall-policies`, `…/firewall/zone` | GET | 200 | Firewall (`rest/firewallrule` ist leer) |
| `v2/api/site/<site>/system-log/all` | POST | 200 | Events, Body `{timestampFrom,timestampTo,pageNumber,pageSize}`, neueste zuerst |
| `stat/event`, `v2/…/alarms` | GET | 404 | nicht verfügbar |
| `rest/alarm`, `stat/user` | GET | 400 | nicht verwendet |
| `system-log/device-alert` | POST | 200 | Geräte-Alarme; **bewusst nicht** übernommen (Owner: „Alarme: gar nicht“) |

## Entscheidung
Alles aus ADR-0014 gilt unverändert weiter (Forced-Command-Dateilesen je Quelltyp mit fester
Befehlskonstante, Parser mit Allowlist-Feldern, Außenkontakte nur lesend und opt-in, jeder weitere
SSH-Befehl, jedes weitere Außenziel oder jeder weitere nicht-GET-Aufruf braucht ein neues ADR; ebenso
ADR-0013: `tools.py` als vollständige Fähigkeitsgrenze, `set_switch`-Ausnahme, WebSocket nur
`trace/list`/`trace/get`, Secrets erreichen kein Modell; `list_exposure` liest nur aus der Datenbank).
Aufgelöst bzw. neu:
- **Keine Login-POST-Ausnahme für den Live-Zugriff:** `X-API-Key` reicht für die klassische API. Kein
  Login, kein Cookie, kein View-only-Konto. (Die Ausnahme in ADR-0014 gilt nur noch für
  `unifi_classic_probe.py`, den Scan.)
- **Neues Modul `unifi_live.py`** (nur lesend, kein Import eines `*_admin`-Moduls, wird nicht von
  `unifi_probe.py`, `unifi_classic_probe.py` oder `pipeline.py` importiert). Es ist das einzige
  Quellmodul, das `tools.py` importieren darf; der ADR-0014-Satz „Quellmodule werden nicht von
  `tools.py` importiert“ gilt dafür nicht.
- **Feste Allowlist:** `_request` ist der einzige Netzzugang. Erlaubt sind nur die GET-Pfade der Tabelle
  und **genau ein** POST (`system-log/all`, Events, nur Lesen; Body nur aus intern berechneten
  Ganzzahlen). Aus Nutzereingabe stammt nur `site` (Muster `^[A-Za-z0-9_-]{1,64}$`). Keine Redirects,
  kein Retry.
- **Feld-Positivliste je Objektart**, alles Unbekannte wird verworfen; Redaktion von Schlüsseln wie
  `*key*`, `*token*`, `*secret*`, `*password*`, `*psk*`, `x_*` und des Klartext-Keys ist nur zweite
  Schicht. Antworten werden nie gespeichert, geloggt oder mit Rohtext in Fehlermeldungen gezeigt.
- **Limits:** Zeitfenster (Events) höchstens 168 h, höchstens 50 Einträge, 16 000 Zeichen je Abfrage.
- **TLS:** `verify=False` wie in `unifi_probe.py` (selbstsigniertes Zertifikat, Ziel im LAN; der Key
  geht im Header an den Controller im LAN).
- **Bewertung weiterer Integrationen (AK9):** Docker und Home Assistant haben bereits Live-Zugriff.
  Folge-Issues: Omada (#107), Proxmox (#108), AdGuard (#109).
- Umsetzung in Stufen: zuerst `get_unifi_client`; `get_unifi_device`, `get_unifi_network` und
  `get_unifi_events` (der POST) folgen und sind hier bereits als zulässig festgelegt.

## Konsequenzen
- Der Assistent beantwortet Verbindungsfragen mit Live-Werten; ohne `unifi`-Konto bleibt es beim
  Inventar des letzten Scans (klare Meldung).
- Ein Reviewer erkennt Verstöße an einem Pfad außerhalb der Allowlist, einem zweiten POST, einem
  durchgereichten Feld ohne Positivliste oder einem Import aus `unifi_live` in Scan-Modulen.
- Geltung nur für UniFi Network 11.0.103; andere Versionen können Pfade ändern (404/405 werden als
  „Endpunkt nicht verfügbar“ gemeldet).
- ADR-0014 hat den Status „Ersetzt durch ADR-0015; ersetzte ADR-0013“.
