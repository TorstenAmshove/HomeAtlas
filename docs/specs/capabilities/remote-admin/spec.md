# Remote-Admin (schreibende Geräteverwaltung)

> Status: Ist-Verhalten, aus dem Code zurückgewonnen (Stand 0159807). Quellen als `datei:zeile`.

## Zweck

Der Administrator des Haushalts soll Geräte aus der Geräteansicht heraus bedienen können, ohne
zwischen Werkzeugen zu wechseln: lokale und entfernte Docker-Container starten/stoppen/neu starten,
Logs lesen, eine Konsole öffnen, Proxmox-Gäste steuern, ein Gerät neu starten und
Smart-Home-Schalter (Shelly, Home Assistant) ein- und ausschalten. Jede dieser Aktionen verändert
ein reales Gerät und ist deshalb strikt vom lesenden Teil der Anwendung getrennt, nur für ADMIN
erreichbar und protokolliert.

## Rollen und Rechte

| Aktion | ADMIN | MEMBER |
|---|---|---|
| Lokale Container steuern, Logs, Konsole | ja | nein (403 / WS 1008) |
| Entfernte Container/Proxmox-Gäste listen, steuern, Logs | ja | nein |
| SSH-Konsole, Remote-Docker-Konsole | ja | nein (WS 1008) |
| Gerät neu starten | ja | nein |
| Shelly/HA über REST schalten, HA-Entities listen | ja | nein |
| Shelly/HA über den Assistenten schalten (`set_switch`) | ja | **ja** (Ausnahme, siehe Req. „Lese/Schreib-Grenze“) |

Alle Routen verlangen zusätzlich eine abgeschlossene TOTP-Einrichtung
(siehe [auth-und-rollen](../auth-und-rollen/spec.md)).

## Anforderungen

### Requirement: Nur ADMIN mit zweitem Faktor
Das System MUSS jede Route dieser Fähigkeit (REST und WebSocket) nur für angemeldete ADMIN-Konten mit aktivem zweitem Faktor ausführen. **[Muss]**

#### Szenario: MEMBER ruft eine Schreibroute auf
- **WENN** ein MEMBER `POST /api/systems/{id}/reboot` aufruft
- **DANN** antwortet das System mit 403 „Dafür werden Administratorrechte benötigt.“ und führt nichts aus

#### Szenario: WebSocket ohne Admin-Sitzung
- **WENN** eine Konsole ohne gültige Sitzung, ohne TOTP oder mit Rolle MEMBER geöffnet wird
- **DANN** wird die Verbindung mit Close-Code 1008 abgewiesen, bevor eine Geräteverbindung entsteht

Quelle: `backend/app/main.py:102`, `backend/app/main.py:146`, `backend/app/main.py:805`

### Requirement: Origin-Prüfung für Konsolen
Das System MUSS einen WebSocket-Handshake ablehnen (1008), wenn ein `Origin`-Header vorhanden ist und dessen Hostname nicht dem Hostnamen aus `Host` entspricht; Ports werden dabei ignoriert. **[Muss]**

#### Szenario: Fremde Origin
- **WENN** ein Browser von `evil.example` eine Konsole auf `homeatlas.lan` öffnet
- **DANN** wird mit 1008 geschlossen, auch wenn das Sitzungs-Cookie mitgesendet wurde

#### Szenario: Proxy entfernt den Port
- **WENN** Origin `http://homeatlas.lan:8280` und Host `homeatlas.lan` lauten
- **DANN** gilt die Anfrage als gleiche Herkunft

Quelle: `backend/app/main.py:136`–`backend/app/main.py:144`

### Requirement: Lese/Schreib-Grenze
Das System MUSS schreibende Geräteaktionen ausschließlich aus admin-geschützten UI-Routen erreichbar machen, nie aus dem Assistenten/MCP, dem Scan oder lesenden Probes; einzige Ausnahme ist das Ein/Aus-Schalten von Shelly-Relais und Home-Assistant-`switch`/`light`-Entities (siehe [assistent-chat-und-mcp](../assistent-chat-und-mcp/spec.md), [llm-tools](../../contracts/llm-tools.md)). **[Muss]**

#### Szenario: Assistent soll Container neu starten
- **WENN** ein Nutzer den Assistenten bittet, einen Container oder ein Gerät neu zu starten
- **DANN** steht dafür kein Werkzeug zur Verfügung; nur `set_switch` verändert Geräte

Quelle: `backend/app/remote_admin.py:13`, `backend/app/docker_admin.py:10`, `backend/app/proxmox_admin.py:7`, `backend/app/switch_admin.py:9`, `backend/app/tools.py:28`, ADR `docs/adr/0011-lese-schreib-trennung-routen-module.md`

### Requirement: Feste Aktionslisten je Route
Das System MUSS je Route nur die folgenden Aktionen annehmen und jede andere mit 404 „Unbekannte Aktion.“ ablehnen: Container lokal/entfernt `start`, `stop`, `restart`; Shelly/HA `on`, `off`. Es DARF keine frei formulierten Befehle an Geräte senden; Container-IDs und VMIDs werden vor Verwendung in Shell-Befehlen gequotet. **[Muss]**

#### Szenario: Unbekannte Aktion
- **WENN** `POST /api/systems/{id}/container/kill` aufgerufen wird
- **DANN** 404, kein Docker-Aufruf

#### Szenario: Unbekannte Proxmox-Aktion im SSH-Fallback
- **WENN** die SSH-Proxmox-Steuerung mit Aktion `destroy` aufgerufen wird
- **DANN** Ergebnis „Unbekannte Aktion 'destroy'.“ ohne Verbindungsaufbau

Quelle: `backend/app/main.py:894`, `backend/app/main.py:1043`, `backend/app/main.py:1178`, `backend/app/main.py:1210`, `backend/app/remote_admin.py:38`, `backend/app/remote_admin.py:385`, Test: `backend/tests/test_remote_admin_proxmox.py::test_run_remote_proxmox_guest_command_rejects_unknown_action`

### Requirement: Lokale Container steuern
Das System MUSS für Inventar-Einträge der Art `container` mit hinterlegter Docker-Container-ID Start, Stopp und Neustart über die lokale Docker-Engine ausführen; „bereits im Zielzustand“ gilt als Erfolg. **[Muss]**

#### Szenario: Gerät ist kein Container
- **WENN** die Aktion für ein Gerät mit `kind != container` aufgerufen wird
- **DANN** 404 „Container nicht gefunden.“

#### Szenario: Container-ID fehlt
- **WENN** der Eintrag keine Container-ID hat
- **DANN** 400 „Keine Container-ID hinterlegt -- bitte erneut scannen.“

#### Szenario: Docker lehnt ab
- **WENN** die Engine mit einem Fehlerstatus antwortet
- **DANN** 400 mit der Fehlermeldung der Engine; Protokolleintrag mit `ok=false`

Quelle: `backend/app/main.py:901`–`backend/app/main.py:918`, `backend/app/docker_admin.py:47`

### Requirement: Lokale Container-Logs live
Das System MUSS die Logs eines lokalen Containers als fortlaufenden Text-Stream (stdout+stderr) liefern, beginnend mit den letzten `tail` Zeilen (Default 200), und folgt neuen Zeilen bis zum Abbruch durch den Client. **[Muss]**

#### Szenario: Logs öffnen
- **WENN** `GET /api/systems/{id}/container/logs` aufgerufen wird
- **DANN** `text/plain`-Stream der letzten 200 Zeilen, danach live; bei Docker-Fehler eine Zeile `[Log-Abruf fehlgeschlagen: HTTP n]`

Quelle: `backend/app/main.py:921`, `backend/app/docker_admin.py:98`–`backend/app/docker_admin.py:110`

### Requirement: Terminal-Protokoll der Konsolen
Das System MUSS für alle drei Konsolen dasselbe WebSocket-Protokoll sprechen: Binärframes tragen rohe Terminal-Bytes in beide Richtungen; Textframes sind JSON-Steuernachrichten. Client→Server: `{"type":"resize","cols":n,"rows":n}` (Defaults 80/24). Server→Client: `{"type":"error","message":"…"}` bei Fehlschlag des Sitzungsaufbaus, danach Close 1011. Validierungs-/Authentifizierungsfehler: Close 1008 ohne Nachricht. Endet eine Seite (Prozessende oder Browser trennt), wird die Sitzung vollständig geschlossen. **[Muss]**

#### Szenario: Verbindungsaufbau scheitert
- **WENN** die SSH-Anmeldung am Zielgerät fehlschlägt
- **DANN** sendet der Server `{"type":"error","message":<Fehlertext>}`, schließt mit 1011 und protokolliert `console.ssh.open` mit `ok=false`

#### Szenario: Fenstergröße ändert sich
- **WENN** der Client `{"type":"resize","cols":120,"rows":40}` sendet
- **DANN** wird das entfernte Terminal auf 120×40 gesetzt; andere Textframes und ungültiges JSON werden ignoriert

Quelle: `backend/app/main.py:842`–`backend/app/main.py:882`, `backend/app/main.py:825`, `frontend/src/components/Terminal.tsx`

### Requirement: SSH-Konsole
Das System MUSS eine interaktive SSH-Sitzung (PTY `xterm-256color`, Start 80×24) zum Gerät öffnen, wenn `accountId` einen Zugang bezeichnet, der direkt diesem Gerät zugeordnet und SSH-fähig ist (Kategorie `sshkey`, oder `login` mit Port 22 oder ohne Port) und das Gerät eine IP oder einen Hostnamen hat; sonst 1008. **[Muss]**

#### Szenario: Zugang gehört zu anderem Gerät
- **WENN** `accountId` einem anderen Gerät zugeordnet ist (auch über eine Zuordnungsregel statt direkt)
- **DANN** Close 1008

Quelle: `backend/app/main.py:791`–`backend/app/main.py:840`, `backend/app/remote_admin.py:88`–`backend/app/remote_admin.py:108`, `backend/app/remote_admin.py:156`

### Requirement: Lokale und entfernte Docker-Konsole
Das System MUSS eine interaktive Shell `/bin/sh` (TTY) in einem Container öffnen: lokal über die Docker-Engine für `container`-Einträge mit Container-ID; entfernt per SSH (`docker exec -it <id> /bin/sh`) mit `accountId` und `containerId` als Query-Parameter. Die entfernte Konsole wird für Proxmox-Hosts (Gerät mit Zugang der Kategorie `proxmox`) mit 1008 abgelehnt. **[Muss]**

#### Szenario: Proxmox-Host
- **WENN** die Remote-Docker-Konsole für einen Proxmox-Host geöffnet wird
- **DANN** Close 1008

Quelle: `backend/app/main.py:932`–`backend/app/main.py:964`, `backend/app/main.py:1226`–`backend/app/main.py:1266`, `backend/app/docker_admin.py:191`, `backend/app/remote_admin.py:408`

### Requirement: Entfernte Container und Proxmox-Gäste listen
Das System MUSS für ein Gerät die Container bzw. Gäste liefern: Ist dem Gerät ein `proxmox`-Zugang zugeordnet, über die Proxmox-API (VMs und LXC aller Nodes), bei deren Fehlschlag und gesetztem `accountId` über SSH (`pct list`, `qm list`) – nie über `docker`. Sonst über SSH `docker ps -a`. Jeder Eintrag hat `id`, `name`, `image`, `state` (`running`/`stopped` bzw. Docker-State), `status`; Proxmox-Einträge zusätzlich `ip`, `node`, `vmid`, `kind` (`vm`/`container`). Zusätzlich `proxmoxUrl` (sonst leer) für einen Link in die Proxmox-eigene Konsole. **[Muss]**

#### Szenario: Proxmox-Host ohne Docker
- **WENN** die REST-Abfrage scheitert und ein SSH-Zugang gewählt ist
- **DANN** werden `pct list` und `qm list` ausgeführt, nie `docker`

#### Szenario: Nur einer der Befehle funktioniert
- **WENN** `qm` fehlt, `pct list` aber Ergebnisse liefert
- **DANN** werden die LXC-Container geliefert, kein Fehler

Quelle: `backend/app/main.py:1015`–`backend/app/main.py:1037`, `backend/app/remote_admin.py:179`–`backend/app/remote_admin.py:309`, Tests: `backend/tests/test_remote_admin_proxmox.py::test_list_remote_proxmox_guests_never_runs_docker`, `::test_list_remote_proxmox_guests_survives_qm_missing_when_pct_works`, `::test_list_remote_proxmox_guests_reports_a_clear_error_when_both_commands_fail`, `::test_parse_pct_list_handles_a_locked_row_with_extra_column`, `backend/tests/test_main_proxmox_routing.py::test_proxmox_account_ignores_accounts_on_other_systems`

### Requirement: Entfernte Container und Proxmox-Gäste steuern
Das System MUSS `start`/`stop`/`restart` für entfernte Ziele ausführen. Proxmox: Container-ID im Format `{node}:{qemu|lxc}:{vmid}` oder `{qemu|lxc}:{vmid}` (sonst 400 „Ungültige Container-/VM-ID.“); `stop` ist ein geordnetes Herunterfahren (`shutdown`), `restart` ein `reboot`, nie ein harter Stopp. Mit bekanntem Node zuerst über die API, bei Fehlschlag oder unbekanntem Node mit `accountId` über SSH (`pct`/`qm`). Ohne API-Ergebnis und ohne `accountId`: 400. Docker-Hosts: `docker <aktion> <id>` per SSH. **[Muss]**

#### Szenario: Stopp einer VM
- **WENN** `stop` für `pve:qemu:101` aufgerufen wird
- **DANN** geht `POST /nodes/pve/qemu/101/status/shutdown` an die Proxmox-API

#### Szenario: SSH-Fallback für LXC
- **WENN** die ID `lxc:200` lautet (Node unbekannt) und ein SSH-Zugang gewählt ist
- **DANN** wird `pct shutdown 200` (bzw. `start`/`reboot`) ausgeführt

Quelle: `backend/app/main.py:993`–`backend/app/main.py:1083`, `backend/app/proxmox_admin.py:21`, Tests: `backend/tests/test_proxmox_admin.py::test_guest_action_posts_the_right_status_verb_for_each_action`, `::test_guest_action_uses_qemu_path_for_vms`, `::test_guest_action_requires_token`, `backend/tests/test_remote_admin_proxmox.py::test_run_remote_proxmox_guest_command_uses_qm_for_vms_and_maps_stop_to_shutdown`, `::test_run_remote_proxmox_guest_command_uses_pct_for_containers_and_never_docker`

### Requirement: Entfernte Logs (einmaliger Abruf)
Das System MUSS Logs entfernter Ziele als einmaligen Text liefern (`{"text": …}`): Docker-Host: die letzten 200 Zeilen (`docker logs --tail 200`, stdout+stderr). Proxmox-Gast mit `mode=journal`: `journalctl -n 200` im LXC-Container per SSH (nur `kind=container`, sonst 400; ohne `accountId` 400). Proxmox-Gast sonst: Proxmox-Aufgabenverlauf der letzten 20 Tasks, neueste zuerst, gekürzt auf die letzten 20 000 Zeichen; erfordert bekannten Node (sonst 400). **[Muss]**

#### Szenario: Journal für eine VM
- **WENN** `mode=journal` für eine VM angefordert wird
- **DANN** 400 „journalctl ist nur für LXC-Container verfügbar.“

#### Szenario: Docker-Host
- **WENN** das Gerät keinen Proxmox-Zugang hat
- **DANN** wird der Docker-Logpfad per SSH genutzt

Quelle: `backend/app/main.py:1086`–`backend/app/main.py:1129`, `backend/app/remote_admin.py:212`, `backend/app/remote_admin.py:347`, `backend/app/proxmox_probe.py:280`, Tests: `backend/tests/test_main_reboot_and_logs.py::test_logs_reads_proxmox_task_log_when_node_is_known`, `::test_logs_journal_mode_requires_lxc_kind`, `::test_logs_journal_mode_uses_ssh_journalctl`, `::test_logs_uses_remote_docker_path_for_a_non_proxmox_host`, `backend/tests/test_remote_admin_reboot_and_logs.py::test_remote_container_logs_returns_last_lines`

### Requirement: Gerät neu starten
Das System MUSS einen Geräte-Neustart über genau einen von zwei Wegen auslösen: Enthält Hersteller, Modell oder Name „fritz“ oder ist die Art `router`, per TR-064-Aktion `DeviceConfig:1#Reboot` (Port 49000, HTTP-Digest) mit einem Zugang der Kategorie `login`/`router` (sonst 400 mit Hinweis auf TR-064); sonst per SSH (`sudo -n reboot`, ersatzweise `reboot`) mit SSH-fähigem Zugang (sonst 400). Zugang muss direkt dem Gerät zugeordnet sein (sonst 404); Gerät ohne Adresse: 400. **[Muss]**

#### Szenario: Linux-Server
- **WENN** ein Server mit `sshkey`-Zugang neu gestartet wird
- **DANN** wird der SSH-Weg genutzt, nie TR-064

#### Szenario: Router mit SSH-Zugang
- **WENN** für einen Router ein `sshkey`-Zugang übergeben wird
- **DANN** 400, Meldung enthält „TR-064“

Quelle: `backend/app/main.py:1132`–`backend/app/main.py:1167`, `backend/app/remote_admin.py:419`–`backend/app/remote_admin.py:479`, Tests: `backend/tests/test_main_reboot_and_logs.py::test_reboot_uses_ssh_for_a_generic_host`, `::test_reboot_uses_tr064_for_a_router`, `::test_reboot_rejects_ssh_account_for_a_router`, `::test_reboot_rejects_non_ssh_account_for_a_generic_host`, `::test_reboot_404s_for_unknown_account`, `backend/tests/test_remote_admin_reboot_and_logs.py::test_reboot_fritzbox_posts_the_reboot_soap_action`, `backend/tests/test_remote_admin_proxmox.py::test_reboot_host_tries_passwordless_sudo_then_plain_reboot`

### Requirement: Shelly-Relais schalten
Das System MUSS ein Relais (`channel`, Default 0) eines Shelly-Geräts ein- oder ausschalten und dazu die Gerätegeneration bei jedem Aufruf frisch über `GET /shelly` ermitteln: Gen1 `GET /relay/{ch}?turn=on|off`, Gen2+ `GET /rpc/Switch.Set?id={ch}&on=true|false`. Antwortet das Ziel nicht wie ein Shelly oder mit HTTP ≥ 400: 400 mit Meldung. **[Muss]**

#### Szenario: Gen2-Gerät
- **WENN** `/shelly` `{"gen":2}` liefert und `on` angefordert wird
- **DANN** `GET /rpc/Switch.Set?id=0&on=true`

Quelle: `backend/app/main.py:1175`–`backend/app/main.py:1193`, `backend/app/switch_admin.py:27`–`backend/app/switch_admin.py:50`

### Requirement: Home-Assistant-Entities listen und schalten
Das System MUSS mit einem direkt dem Gerät zugeordneten Zugang der Kategorie `homeassistant` (sonst 404) die Entities der Domänen `switch` und `light` listen (`entityId`, `name`, `state`) und einzeln über `turn_on`/`turn_off` schalten. Entities anderer Domänen (z. B. `lock`, `cover`, `climate`, `alarm_control_panel`) DÜRFEN NICHT geschaltet werden. Adresse: URL des Zugangs, ersatzweise URL des Geräts. **[Muss]**

#### Szenario: Schloss
- **WENN** `entityId=lock.haustuer` geschaltet werden soll
- **DANN** 400, kein Aufruf an Home Assistant

#### Szenario: Token abgelehnt
- **WENN** Home Assistant mit 401/403 antwortet
- **DANN** 400 „Home Assistant hat das Zugriffstoken abgelehnt …“

Quelle: `backend/app/main.py:1196`–`backend/app/main.py:1223`, `backend/app/switch_admin.py:53`–`backend/app/switch_admin.py:80`, `backend/app/probe_auth.py:826`

### Requirement: Zugriffsprotokoll
Das System MUSS jede schreibende Aktion und jedes Öffnen/Schließen einer Konsole mit Benutzer, Client-IP (aus `X-Real-IP`), User-Agent, Erfolg und Kurzbeschreibung protokollieren; beim Schließen einer Konsole die Dauer in Sekunden. Aktionsnamen: `container.{start|stop|restart}`, `container.remote.{…}`, `container.proxmox.{…}`, `system.reboot`, `switch.shelly`, `switch.ha`, `switch.assistant`, `console.{ssh|docker|remote-docker}.{open|close}`. Reine Lesezugriffe (Logs, Listen) werden nicht protokolliert. **[Muss]**

#### Szenario: Konsole wird geschlossen
- **WENN** eine SSH-Sitzung nach 95 s endet
- **DANN** Eintrag `console.ssh.close` mit Detail `<Gerätename> (95s)`

Quelle: `backend/app/main.py:827`–`backend/app/main.py:839`, `backend/app/main.py:915`, `backend/app/main.py:1070`, `backend/app/main.py:1079`, `backend/app/main.py:1163`, `backend/app/main.py:1189`, `backend/app/main.py:1219`, `backend/app/db.py:1849`

### Requirement: Fehler als verständliche Rückmeldung
Das System MUSS fehlgeschlagene Geräteaktionen (Verbindung, Anmeldung, Befehl) als HTTP 400 mit deutschem, handlungsleitendem Text melden, nicht als Serverfehler; fehlt dem SSH-Benutzer der Zugriff auf den Docker-Socket, MUSS die Meldung den Befehl `sudo usermod -aG docker <user>` und den Hinweis auf Neuanmeldung enthalten. **[Muss]**

#### Szenario: Benutzer nicht in Gruppe docker
- **WENN** `docker logs` mit „permission denied … docker.sock“ scheitert
- **DANN** enthält die Fehlermeldung `usermod -aG docker`

Quelle: `backend/app/remote_admin.py:72`–`backend/app/remote_admin.py:85`, Test: `backend/tests/test_remote_admin_reboot_and_logs.py::test_remote_container_logs_reports_docker_group_permission_error`

### Requirement: Bestätigung in der Oberfläche
Die Oberfläche MUSS vor Stopp/Neustart eines Containers oder Gasts und vor einem Geräte-Neustart eine Bestätigung verlangen; Start und Ein/Aus-Schalten erfolgen in der klassischen Oberfläche ohne Rückfrage. In der neuen Oberfläche (Tab „Steuern“, nur ADMIN) verlangt zusätzlich jedes Ausschalten (Shelly, Home-Assistant-Entity) einen Prüfdialog, der in Klartext sagt, was passiert; Start und Einschalten bleiben ohne Rückfrage, und neben jeder Aktion steht der aktuelle Zustand (Gerät, Container, Entity; der Schaltzustand eines Shelly wird nicht abgefragt und das auch so gesagt). Admin-Bereiche werden nur ADMIN angezeigt. **[Muss]** (Rückfrage-Texte **[Impl]**)

#### Szenario: Neustart
- **WENN** der Admin „Gerät neu starten“ klickt
- **DANN** Rückfrage „„<Name>“ wirklich neu starten? Das Gerät ist währenddessen kurz nicht erreichbar.“

#### Szenario: Ausschalten in der neuen Oberfläche
- **WENN** der Admin im Tab „Steuern“ bei einer Home-Assistant-Entity „Aus …“ klickt
- **DANN** fragt ein Dialog „„<Name>“ ausschalten?“ und schaltet erst nach „Ausschalten“

Quelle: `frontend/src/pages/SystemDetailPage.tsx:175`, `frontend/src/pages/SystemDetailPage.tsx:224`, `frontend/src/pages/SystemDetailPage.tsx:1024`, `frontend/src/pages/SystemDetailPage.tsx:645`, `frontend/src/pages/device/SteuernTab.tsx`, `frontend/src/pages/device/RemoteHostSection.tsx`

## Daten

Aus [data-model](../../contracts/data-model.md):
- `systems` (lesend): `id`, `name`, `kind`, `ip`, `hostname`, `vendor`, `model`, `url`, `extra.docker.containerId`.
- `accounts` (lesend): `systemId` (muss exakt dem Gerät entsprechen), `category` (`sshkey`, `login`, `router`, `proxmox`, `homeassistant`), `username` (bei `proxmox`: Token-ID), `secretEnc`, `passphraseEnc`, `url`, `port`. Secrets werden serverseitig entschlüsselt und nie zurückgegeben.
- `accessLog` (schreibend): `action`, `userId`, `username`, `ip`, `userAgent`, `ok`, `detail` (max. 500 Zeichen); Bestand auf 5000 Einträge begrenzt (`backend/app/db.py:1846`).
- Keine Settings-Keys.

## Schnittstellen

| Methode | Pfad | Rolle | Zweck |
|---|---|---|---|
| GET | /api/systems/{system_id}/container/logs | ADMIN | Live-Log-Stream lokaler Container (`tail`, Default 200) |
| POST | /api/systems/{system_id}/container/{action} | ADMIN | Lokaler Container `start`/`stop`/`restart` |
| GET | /api/systems/{system_id}/remote-containers | ADMIN | Entfernte Container/Proxmox-Gäste listen (`accountId` optional) |
| GET | /api/systems/{system_id}/remote-containers/{container_id}/logs | ADMIN | Logs entfernt (`accountId`, `mode=journal` optional) |
| POST | /api/systems/{system_id}/remote-containers/{container_id}/{action} | ADMIN | Entfernt `start`/`stop`/`restart` (`accountId` Pflicht-Query, darf leer sein) |
| POST | /api/systems/{system_id}/reboot | ADMIN | Gerät neu starten (`accountId` Pflicht) |
| GET | /api/systems/{system_id}/ha-switchables | ADMIN | HA-`switch`/`light`-Entities (`accountId` Pflicht) |
| POST | /api/systems/{system_id}/ha-switch/{action} | ADMIN | HA-Entity `on`/`off` (`accountId`, `entityId` Pflicht) |
| POST | /api/systems/{system_id}/shelly-switch/{action} | ADMIN | Shelly-Relais `on`/`off` (`channel`, Default 0) |
| WS | /api/ws/systems/{system_id}/ssh-console | ADMIN | Interaktive SSH-Konsole (`accountId`) |
| WS | /api/ws/systems/{system_id}/docker-console | ADMIN | Shell im lokalen Container |
| WS | /api/ws/systems/{system_id}/remote-docker-console | ADMIN | Shell in entferntem Container (`accountId`, `containerId`) |

Erfolgsantworten der Aktionen: `{"ok": true}`; Listen: `{"containers": [...], "proxmoxUrl": "…"}` bzw. `{"entities": [...]}`; Logs entfernt: `{"text": "…"}`.
Berührt: SSH-Schlüssel erzeugen/verteilen (`POST /api/systems/{id}/ssh-keys`, `POST /api/accounts/{id}/deploy`) gehören zu [zugangsdaten](../zugangsdaten/spec.md); `set_switch`/`list_switches` zu [assistent-chat-und-mcp](../assistent-chat-und-mcp/spec.md).

UI-Seite(n): `frontend/src/pages/SystemDetailPage.tsx` (Route `/geraete/:id`), neue Oberfläche `frontend/src/pages/device/SteuernTab.tsx`, Terminal-Komponente `frontend/src/components/Terminal.tsx`.

## Nicht-Ziele und Grenzen

- Kein harter Stopp (Power-Cut) von Proxmox-Gästen; keine Proxmox-Konsole in HomeAtlas (nur Link auf die Proxmox-noVNC-Konsole).
- Keine Prüfung von SSH-Hostschlüsseln (bewusst, kein Vertrauensspeicher); TLS-Zertifikate bei Proxmox/Home Assistant werden nicht geprüft.
- Entfernte Logs sind kein Live-Tail; Proxmox-Aufgabenverlauf zeigt keine Anwendungs-/Systemausgabe.
- Zugänge, die nur über Zuordnungsregeln (nicht direkt per `systemId`) an einem Gerät hängen, können keine Konsole/Steuerung auslösen.
- Shelly-Geräte mit aktivierter Authentifizierung werden nicht unterstützt (keine Zugangsdaten im Aufruf).
- Keine Idle-Zeitbegrenzung und keine Begrenzung gleichzeitiger Konsolen.

## Ist-Implementierung (nur Referenz, [Impl])

- Schreibmodule duplizieren Verbindungs-Setup bewusst statt lesende Module zu importieren (`remote_admin.py` ↔ `probe_auth.py`, `docker_admin.py` ↔ `docker_probe.py`, `proxmox_admin.py` ↔ `proxmox_probe.py`). Einzige Ausnahme: `ha-switchables` nutzt die lesende Funktion `probe_auth.list_ha_switchables`.
- Lokale Docker-Konsole: Exec-Erzeugung + „Hijack“ des Unix-Sockets (`Upgrade: tcp`), Resize per separatem `POST /exec/{id}/resize`. Docker-Socket ist `:ro` gemountet, was Schreibaufrufe über den Socket nicht verhindert.
- Timeouts: Docker-API 15 s (Connect 5 s), Log-Stream ohne Timeout; SSH-Connect 10 s, Befehle ohne Gesamt-Timeout; TR-064 15 s; Proxmox 15 s (Connect 5 s); Shelly/HA-Schalten 8 s (Connect 3 s); HA-Liste 15 s (Connect 5 s) mit Vorab-Prüfung `GET /api/`.
- Relay liest in 4096-Byte-Blöcken; SSH-PTY mit `encoding=None` (Bytes), damit UTF-8-Zeichen nicht zerbrechen.
- Close 1008 wird vor `accept()` gesendet und erscheint beim Browser als abgelehnter Handshake (Starlette: HTTP 403), nicht als regulärer Close-Code.
- UI hält Live-Logs auf die letzten 20 000 Zeichen begrenzt.
- SSH-Proxmox-Einträge haben leeren `node`; deshalb kein Task-Log und kein noVNC-Link für sie.

## OFFEN

- > OFFEN: Prompt-Injection-Risiko: Inhalte aus Inventar/Doku könnten das Modell zu `set_switch` ohne Rückfrage verleiten.
- > OFFEN: Assistent schaltet bei Shelly immer Kanal 0; REST-Route akzeptiert beliebige `channel`-Ganzzahl ohne Bereichsprüfung.
- > OFFEN: Proxmox-Steuerung fällt bei *jedem* API-Fehler auf SSH zurück – auch bei fachlichen Fehlern der API (z. B. Gast bereits gestoppt); mögliche Doppelausführung/irreführende Meldung. (`backend/app/main.py:1061`)
- > OFFEN: Reboot meldet evtl. Fehler, obwohl der Neustart ausgelöst wurde (SSH-Verbindung bricht beim Reboot ab, bevor ein Exit-Status kommt). Nicht durch Tests abgedeckt.
- > OFFEN: Kategorie `router` wird im Reboot-Pfad akzeptiert, existiert aber in der UI-Kategorieliste nicht (`frontend/src/pages/AccountsPage.tsx:5`) – toter Zweig oder Altbestand?
- > OFFEN: SSH-Befehle (`connection.run`) haben kein Gesamt-Timeout; ein hängender Befehl blockiert die Anfrage unbegrenzt.
- > OFFEN: Nicht-numerische `cols`/`rows` in einer Resize-Nachricht lösen eine Ausnahme aus und beenden die Sitzung statt ignoriert zu werden. (`backend/app/main.py:864`)
- > OFFEN: `Terminal.tsx` erwartet laut Kommentar eine Server-Nachricht `{"type":"exit"}`, die das Backend nie sendet.
- > OFFEN: Frontend kodiert `containerId` in der URL der Remote-Docker-Konsole nicht (`frontend/src/lib/api.ts:528`), anders als bei Aktion/Logs.
- > OFFEN: Keine Tests für die drei WebSocket-Konsolen, lokale Container-Aktionen, Shelly/HA-Schalten und die Origin-Prüfung.
