# ADR-0014: Lesender Live-Zugriff auf die klassische UniFi-API

- **Status:** Vorgeschlagen (wird „Akzeptiert“, sobald der Spike unten ausgefüllt und die Auth-Frage entschieden ist)
- **Datum:** 2026-11-22

## Kontext
Der Assistent soll Fehleranalyse mit Live-Daten machen („warum hat Client xy ständig
Verbindungsprobleme?“, #104). `unifi_probe.py` nutzt die Integration API
(`/proxy/network/integration/v1`, `X-API-Key`) und liefert pro Client nur IP, MAC und
Verbindungstyp, kein Signal, keine Retries, kein Roaming, keine Events. Diese Daten liefert nur die
klassische Controller-API (`/proxy/network/api/s/<site>/…`). Ob der vorhandene API-Key dort
akzeptiert wird, hängt von der UniFi-Version ab und lässt sich nur gegen den echten Controller prüfen.
Nur APIs, kein MCP-Server (Owner-Entscheidung).

## Entscheidung (Vorschlag)
Alles aus ADR-0013 gilt unverändert weiter. Neu:
- Neues Modul `backend/app/unifi_live.py`, nur lesend, nur von `tools.py` genutzt. Es importiert kein
  `*_admin.py`/`remote_admin.py`/`routes/` und wird von `unifi_probe.py` und `pipeline.py` nicht
  importiert. `unifi_probe.py` bleibt unverändert.
- Genau eine Netzfunktion `_get` (nur GET), Pfade aus fester Tabelle `_ALLOWED_ENDPOINTS`, einzige
  Variable ist die validierte Site (`^[A-Za-z0-9_-]{1,64}$`). Alles andere wirft `ValueError`.
- Zeitfenster höchstens 7 Tage (168 h, Default 24 h), höchstens 50 Einträge und 16 000 Zeichen je
  Abfrage; Kürzung wird im Ergebnis genannt. Antworten werden geschwärzt (`x_passphrase`,
  `x_iapp_key`, `*password*`, `*secret*`, `*token*`, `*psk*`, Cookies) und nie gespeichert.
- TLS-Prüfung aus, Timeout 15 s / connect 5 s, wie `unifi_probe.py`.
- Konto der Kategorie `unifi`; fehlt es oder ist der Controller nicht erreichbar, kommt eine
  verständliche Meldung.
- **Auth, abhängig vom Spike:** (a) akzeptiert die klassische API `X-API-Key`, wird nur dieser Header
  genutzt, kein neuer Credential-Pfad. (b) Sonst optionales lokales Konto mit Rolle „nur Ansicht“ in
  `accounts.secretEnc` (ADR-0007). Das braucht Cookie-Login per POST auf den festen Login-Pfad, CSRF
  und Relogin, also eine ausdrückliche, eng gefasste Ausnahme von „nur GET“. Diese Ausnahme gilt erst
  nach Entscheidung des Owners; der Plan wird dann vor Teil B überarbeitet.

## Spike-Ergebnis (vom Owner auszufüllen, Anleitung: `docs/adr/spikes/0014-unifi-api-key.md`)
| Endpunkt | `X-API-Key` akzeptiert? | Relevante Felder |
|---|---|---|
| `GET /proxy/network/api/s/default/stat/sta` | offen | offen (erwartet u. a. `signal`, `rssi`, `tx_retries`, `uptime`, `ap_mac`, `sw_port`) |
| `GET …/stat/device` | offen | offen (`uplink`, `sys_stats`, `port_table`) |
| `GET …/stat/event` | offen | offen |
| `GET …/stat/alarm` | offen | offen |
| `GET …/stat/health` | offen | offen |
| `GET …/rest/firewallrule` | offen | offen (nur falls nötig, enthält potenziell sensible Daten) |

UniFi-Version: offen.

## Bewertung weiterer Integrationen (je ein Folge-Issue)
- **Omada** (`omada_probe.py`, OpenAPI mit Client-ID/-Secret): gleiche Art Controller wie UniFi, Live-Client-
  und Geräte-Status (Signal, Uplink) lohnt sich. Folge-Issue.
- **Proxmox** (`proxmox_probe.py`): Live-Last, Gast-Status und Aufgabenprotokoll helfen bei „warum ist VM
  x langsam/aus“. Lesend per GET machbar, `proxmox_admin.py` bleibt getrennt. Folge-Issue.
- **AdGuard** (`adguard_probe.py`): Live-Abfrageprotokoll und Statistik je Client („wird Domain x
  blockiert?“). Lohnt sich, Protokolle enthalten aber Surfverhalten, daher Datenschutz und Kürzung
  klären. Folge-Issue.
- **Docker**: hat bereits Live-Zugriff (`docker_probe.py`, GET-only, Tools für Status/Logs). Kein
  Folge-Issue.
- **Home Assistant**: hat bereits Live-Tools (ADR-0012/0013).

## Konsequenzen
- Weitere Endpunkte, Methoden oder ein Schreibzugriff auf UniFi brauchen ein neues ADR.
- Ein Import von `unifi_live` in `unifi_probe.py`/`pipeline.py`, ein Pfad-Parameter oder eine zweite
  Netzfunktion ist ein Fehler, kein Refactoring.
- Bei Annahme: Constitution-Regeln L2, K1, K2 auf dieses ADR verlinken bzw. ergänzen (im selben PR).
