# Monitoring (Dauerüberwachung wichtiger Geräte)

> Status: Ist-Verhalten, aus dem Code zurückgewonnen (Stand 0159807). Quellen als `datei:zeile`.

## Zweck

Der Haushalt will wissen, ob die wirklich wichtigen Geräte (Router, NAS, Heizungssteuerung …)
*jetzt* funktionieren, nicht nur beim letzten Scan. Ein Hintergrundprozess prüft überwachte Geräte
alle paar Sekunden über ihren Dienst-Port oder per Ping, hält deren Status aktuell und merkt sich
nur echte Ausfälle und Wiederkehr – ohne Fehlalarm bei einzelnen verlorenen WLAN-Paketen.

## Rollen und Rechte

| Aktion | ADMIN | MEMBER |
|---|---|---|
| Überwachungsstatus und Ereignisverlauf ansehen | ja | ja |
| Prüfrunde sofort auslösen | ja | nein (403) |
| Gerät überwachen / Ports festlegen (über Inventar) | ja | nein |
| Intervall/Timeout/An-Aus (über Einstellungen) | ja | nein |

## Anforderungen

### Requirement: Menge der überwachten Geräte
Das System MUSS genau die Geräte überwachen, die als „überwacht“ markiert sind und eine IP-Adresse oder einen Hostnamen haben. Geräte mit Bedeutung „kritisch“ und Adresse MÜSSEN automatisch als überwacht markiert werden – beim Start, vor jeder Prüfrunde, beim Anlegen/Ändern/Zusammenführen eines Geräts und nach jedem Scan. Reihenfolge: kritisch, normal, sonstige; dann Name. **[Muss]**

#### Szenario: Gerät wird als kritisch markiert
- **WENN** ein Admin ein Gerät mit IP auf „kritisch“ setzt
- **DANN** wird es spätestens in der nächsten Runde geprüft, ohne Scan abzuwarten

#### Szenario: Gerät ohne Adresse
- **WENN** ein überwachtes Gerät weder IP noch Hostname hat
- **DANN** taucht es in der Überwachung nicht auf

Quelle: `backend/app/db.py:1890`–`backend/app/db.py:1910`, `backend/app/monitor.py:144`, `backend/app/main.py:56`, `backend/app/main.py:563`, `backend/app/main.py:574`, `backend/app/main.py:598`, `backend/app/pipeline.py:512`

### Requirement: Prüfintervall und Abschalten
Das System MUSS im Hintergrund alle `monitorIntervalSeconds` Sekunden (Default 10, wirksam begrenzt auf 5–600) eine Prüfrunde über alle überwachten Geräte ausführen, sofern `monitorEnabled` (Default an) gesetzt ist. Ist es aus, finden keine automatischen Runden statt; Einstellungsänderungen wirken ab der nächsten Runde ohne Neustart. **[Muss]** (Grenzen 5/600 **[Impl]**)

#### Szenario: Intervall zu klein
- **WENN** `monitorIntervalSeconds` auf 1 gesetzt ist
- **DANN** wird alle 5 Sekunden geprüft

#### Szenario: Überwachung abgeschaltet
- **WENN** `monitorEnabled = false`
- **DANN** keine automatischen Prüfungen; der Status bleibt auf dem letzten Wert

Quelle: `backend/app/monitor.py:123`–`backend/app/monitor.py:137`, `backend/app/db.py:443`–`backend/app/db.py:445`

### Requirement: Auswahl der Prüf-Ports
Das System MUSS je Gerät höchstens 3 Ports wählen, in dieser Rangfolge: (1) von Hand festgelegte Monitor-Ports („explizit“); (2) offene Ports aus dem letzten Scan, die für die Geräteart typisch sind; (3) beliebige offene Ports aus dem Scan; (4) die für die Art typischen Ports, auch ungescannt. Typische Ports je Art: router 80, 443; nas 445, 5001, 5000; server 22, 80, 443; printer 9100, 631; smarthome 8123, 1883; camera 554, 80; network 80, 443; container keine; andere Arten keine. **[Muss]** (Port-Tabelle **[Impl]**)

#### Szenario: NAS ohne Handeinstellung
- **WENN** ein NAS im Scan Ports 22, 445, 5000 offen hatte
- **DANN** werden 445 und 5000 geprüft (nicht explizit)

#### Szenario: Mehr als drei Ports von Hand
- **WENN** 5 Monitor-Ports eingetragen sind
- **DANN** werden nur die ersten 3 geprüft

Quelle: `backend/app/monitor.py:28`–`backend/app/monitor.py:58`

### Requirement: Bewertung einer Prüfung
Das System MUSS je Gerät einen Status `online`, `offline` oder `unknown` plus verständlichen Detailtext ermitteln. Alle gewählten Ports werden parallel per TCP-Verbindungsaufbau mit Timeout `monitorTimeoutMs` (Default 1500 ms, mindestens 200 ms) geprüft. Antwortet einer: `online`. Explizite Ports, keiner offen: `offline` ohne Ping. Sonst (geratene oder keine Ports): ein einzelner Ping entscheidet – Antwort ⇒ `online` (Detail nennt ggf., dass der Port nicht antwortete), keine ⇒ `offline`. Ohne Adresse oder wenn der Ping-Aufruf selbst eine Ausnahme wirft (z. B. ungültige Adresse): `unknown` „Prüfung fehlgeschlagen“. Eine scheiternde Portprüfung zählt als „Port nicht offen“. Wirft die Prüfung eines Geräts an anderer Stelle, wird es in dieser Runde übersprungen – kein Status-, kein Ereignis-, kein Fehlerzählerwechsel. **[Muss]**

#### Szenario: Explizit konfigurierter Dienst tot
- **WENN** Port 445 explizit gesetzt ist, nicht antwortet, das Gerät aber auf Ping reagiert
- **DANN** `offline`, Detail „Kein Dienst erreichbar (geprüft: Port 445 (…))“

#### Szenario: Geratener Port zu, Ping ok
- **WENN** kein Port explizit ist, die geratenen Ports zu sind, Ping antwortet
- **DANN** `online`, Detail „Antwortet auf Ping, aber Port … nahm keine Verbindung an“

#### Szenario: Ausnahme bei einem Gerät
- **WENN** die Prüfung eines Geräts außerhalb des Ping-Aufrufs eine Ausnahme wirft
- **DANN** behält es seinen bisherigen Status und Fehlerzähler; die übrigen Geräte werden normal bewertet

Quelle: `backend/app/monitor.py:65`–`backend/app/monitor.py:102`, `backend/app/monitor.py:141`, `backend/app/monitor.py:150`–`backend/app/monitor.py:156`

### Requirement: Ausfall erst nach Bestätigung
Das System MUSS einen Ausfall erst nach 2 aufeinanderfolgenden `offline`-Ergebnissen übernehmen; bis dahin bleibt der bisherige Status unverändert. Jedes nicht-`offline`-Ergebnis setzt den Fehlerzähler sofort zurück und wird sofort übernommen. **[Muss]** (Schwelle 2 **[Impl]**)

#### Szenario: Ein verlorenes Paket
- **WENN** ein Gerät in einer Runde `offline`, in der nächsten `online` ist
- **DANN** bleibt der Status durchgehend `online`, kein Ereignis

#### Szenario: Bestätigter Ausfall
- **WENN** ein Gerät zwei Runden hintereinander `offline` ist
- **DANN** wechselt der Status nach der zweiten Runde auf `offline`

Quelle: `backend/app/monitor.py:26`, `backend/app/monitor.py:158`–`backend/app/monitor.py:164`, Test: `backend/tests/test_monitor_error_events.py::test_confirmed_down_transition_logs_a_device_error_event`

### Requirement: Nur Statusübergänge als Ereignis
Das System MUSS bei jeder übernommenen Prüfung den aktuellen Gerätestatus speichern (bei `online` auch „zuletzt gesehen“ = jetzt), aber ein Überwachungsereignis (Gerät, Zeitpunkt, neuer Status, Detail max. 300 Zeichen) nur bei einer Statusänderung anlegen. **[Muss]**

#### Szenario: Gerät bleibt online
- **WENN** ein Gerät 100 Runden lang `online` ist
- **DANN** existiert dafür höchstens ein Ereignis (der Wechsel auf `online`)

#### Szenario: Unbekannt → online
- **WENN** ein Gerät mit Status `unknown` erstmals `online` geprüft wird
- **DANN** Status `online`, kein Fehlerereignis

Quelle: `backend/app/db.py:1913`–`backend/app/db.py:1927`, Test: `backend/tests/test_monitor_error_events.py::test_flapping_back_online_does_not_log_an_error_event`

### Requirement: Fehlerereignis am Gerät bei bestätigtem Ausfall
Das System MUSS beim bestätigten Übergang auf `offline` zusätzlich ein Fehlerereignis am Gerät (Stufe `warning`, Text „Nicht mehr erreichbar: <Detail>“) anlegen, sichtbar im Fehlerprotokoll des Geräts; je Gerät werden die neuesten 100 Fehlerereignisse behalten. Ein unbestätigter Fehlschlag erzeugt kein Fehlerereignis. **[Muss]** (Limit 100 **[Impl]**)

#### Szenario: Erster Fehlschlag
- **WENN** nach der ersten `offline`-Runde die Fehlerereignisse abgefragt werden
- **DANN** ist die Liste leer; nach der zweiten Runde enthält sie genau einen `warning`-Eintrag

Quelle: `backend/app/monitor.py:168`–`backend/app/monitor.py:172`, `backend/app/db.py:1741`–`backend/app/db.py:1763`, Test: `backend/tests/test_monitor_error_events.py::test_confirmed_down_transition_logs_a_device_error_event`

### Requirement: Überwachungsstatus abfragen
Das System MUSS jedem angemeldeten Benutzer liefern: `enabled`, `intervalSeconds` (Rohwert der Einstellung), Laufzustand des Monitors (`running`, `lastRun` als Unix-Zeit, `lastError`, `pendingFailures` = Geräte-ID → Anzahl unbestätigter Fehlschläge), alle überwachten Geräte (`id`, `name`, `ip`, `kind`, `status`, `importance`, `lastSeen`, `ports` = gewählte Prüfports, `portsExplicit`) und die letzten 50 Ereignisse (neueste zuerst, mit Gerätename). **[Muss]**

#### Szenario: MEMBER öffnet den Übersichtsplan
- **WENN** ein MEMBER `GET /api/monitor` aufruft
- **DANN** erhält er Status, Geräte und Verlauf (keine Secrets enthalten)

Quelle: `backend/app/main.py:1557`–`backend/app/main.py:1573`, `backend/app/monitor.py:176`, `backend/app/db.py:1930`

### Requirement: Prüfrunde manuell auslösen
Das System MUSS einem ADMIN erlauben, sofort eine Prüfrunde auszuführen, und die in dieser Runde übernommenen Statuswechsel zurückgeben (`changes`: `systemId`, `name`, `status`, `detail`). Die manuelle Runde gilt unabhängig von `monitorEnabled` und zählt für die Ausfallbestätigung wie eine automatische. **[Muss]**

#### Szenario: Admin klickt „Jetzt prüfen“
- **WENN** `POST /api/monitor/run` aufgerufen wird
- **DANN** antwortet das System nach Abschluss der Runde mit `{"changes": [...]}`; MEMBER erhält 403

Quelle: `backend/app/main.py:1576`–`backend/app/main.py:1580`, `frontend/src/pages/geraete/PlanCalm.tsx`

### Requirement: Robuster Dauerbetrieb
Das System MUSS die Überwachung beim Start der Anwendung starten und beim Herunterfahren beenden; ein Fehler in einer Runde oder bei einem einzelnen Gerät DARF die Überwachung nicht beenden (Fehlertext in `lastError`, nächste Runde läuft normal). Geräte einer Runde werden parallel geprüft. **[Muss]**

#### Szenario: Datenbankfehler in einer Runde
- **WENN** eine Runde mit einer Ausnahme abbricht
- **DANN** steht der Text in `lastError`; nach dem Intervall folgt die nächste Runde, die `lastError` bei Erfolg leert

Quelle: `backend/app/monitor.py:130`–`backend/app/monitor.py:137`, `backend/app/monitor.py:150`, `backend/app/main.py:57`

## Daten

Aus [data-model](../../contracts/data-model.md):
- `systems` lesend: `id`, `name`, `kind`, `ip`, `hostname`, `importance`, `openPorts`, `monitorPorts`, `monitored`; schreibend: `status`, `lastSeen`, `monitored` (Auto-Aufnahme kritischer Geräte).
- `monitorEvents` schreibend/lesend: `id`, `systemId`, `at`, `status`, `detail` (max. 300 Zeichen). Keine Aufbewahrungsgrenze.
- `deviceErrorEvents` schreibend: `systemId`, `level=warning`, `message`, `createdAt`; max. 100 je Gerät.
- Settings (nur lesend; geschrieben über [einstellungen-und-llm-provider](../einstellungen-und-llm-provider/spec.md)): `monitorEnabled` (Default `true`), `monitorIntervalSeconds` (Default 10), `monitorTimeoutMs` (Default 1500).

## Schnittstellen

| Methode | Pfad | Rolle | Zweck |
|---|---|---|---|
| GET | /api/monitor | MEMBER | Status, überwachte Geräte, letzte 50 Ereignisse |
| POST | /api/monitor/run | ADMIN | Prüfrunde sofort ausführen, Änderungen zurückgeben |

Berührt: Markieren als überwacht / Monitor-Ports über `PATCH /api/systems/{id}` ([inventar](../inventar/spec.md)); Fehlerereignisse eines Geräts über `GET /api/systems/{id}/errors` ([inventar](../inventar/spec.md)); kritische Geräte auf dem [dashboard](../dashboard/spec.md); Einstellungen über `PATCH /api/settings`.

UI-Seite(n): `frontend/src/pages/geraete/PlanCalm.tsx` (Route `/plan`, Überwachungsbereich, Button „Jetzt prüfen“ nur ADMIN); `frontend/src/pages/device/DeviceCalm.tsx` (Route `/geraete/:id`, Badge „überwacht · Port …/Ping“, Checkbox + Ports im Bearbeiten-Modus); `frontend/src/pages/SettingsPage.tsx` (Route `/einstellungen`, An/Aus, Intervall 5–600 s, Timeout 200–10000 ms).

## Nicht-Ziele und Grenzen

- Keine Benachrichtigungen (Push, E-Mail …); Ausfälle sind nur in der UI und im Verlauf sichtbar.
- Keine Verfügbarkeitsstatistik/Uptime-Berechnung, keine Latenzhistorie.
- Keine Prüfung auf Anwendungsebene (HTTP-Status, Inhalte) – nur TCP-Connect und ICMP.
- Der Ping-Fallback nutzt das Diagnose-Ping (1 Paket, 2 s Wartezeit), nicht `monitorTimeoutMs`.
- Netzwerk-Scans setzen den Status ebenfalls (z. B. nicht mehr gefundene Geräte auf `offline`); Monitor und Scan schreiben dasselbe Feld.

## Ist-Implementierung (nur Referenz, [Impl])

- Ein einzelner asyncio-Task im Backend-Prozess; Fehlerzähler liegen nur im Speicher und gehen bei Neustart verloren.
- Port- und Ping-Prüfung nutzen dieselben Funktionen wie die [diagnose](../diagnose/spec.md) (`diagnostics.check_port`, `diagnostics.ping` mit `count=1`).
- `ensure_monitoring_for_critical` ist ein billiges UPDATE vor jeder Runde.
- Detailtexte enthalten Port-Bezeichnungen aus dem Port-Katalog (`ports.label_for`).

## OFFEN

- > OFFEN: Kritische Geräte werden vor jeder Runde zwangsweise wieder auf „überwacht“ gesetzt – ein Admin kann die Überwachung eines kritischen Geräts nicht abschalten; das Abwählen wird stillschweigend rückgängig gemacht. Absicht? (`backend/app/db.py:1890`)
- > OFFEN: `unknown` (z. B. Ping-Aufruf wirft) setzt den Fehlerzähler zurück und wird sofort übernommen; ein Gerät kann so `offline → unknown → offline` flattern und jeweils Ereignisse erzeugen.
- > OFFEN: Manuelle Runde und Hintergrundschleife teilen sich den Fehlerzähler und können parallel laufen; ein Klick auf „Jetzt prüfen“ kann einen Ausfall daher schneller „bestätigen“ als zwei Intervalle.
- > OFFEN: `monitorEvents` hat keine Aufbewahrungsgrenze (im Gegensatz zu `deviceErrorEvents`/`accessLog`); wächst bei flatternden Geräten unbegrenzt.
- > OFFEN: Rückkehr auf `online` nach Ausfall erzeugt kein Fehler-/Info-Ereignis am Gerät, nur ein `monitorEvents`-Eintrag – gewollt?
- > OFFEN: `intervalSeconds` in `GET /api/monitor` ist der ungeklemmte Einstellungswert, nicht das tatsächlich verwendete Intervall; `monitorTimeoutMs` hat serverseitig keine Obergrenze.
- > OFFEN: Für Docker-Container (Art `container`, teilen die Host-IP) gibt es keine typischen Ports; ohne offene Ports prüft der Monitor per Ping effektiv nur den Host.
