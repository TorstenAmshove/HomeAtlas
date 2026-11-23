# Credentialed Probing (authentifiziertes Auslesen)

> Status: Ist-Verhalten, aus dem Code zurückgewonnen (Stand 0159807). Quellen als `datei:zeile`.

## Zweck

Hat ein Admin für ein Gerät Zugangsdaten hinterlegt und ausdrücklich zum Auslesen freigegeben,
meldet sich HomeAtlas dort an und liest Eckdaten, die ein reiner Netzwerkscan nicht sieht:
Betriebssystem, Hardware, VLANs, Nachbarn, ARP-Tabellen, Gerätekonfiguration, Automationen,
Tonerstand, verwaltete Geräte eines Controllers, VMs eines Hypervisors. Das Auslesen ist
beweisbar lesend: nichts wird am Gerät geändert. Läuft automatisch im Vollscan und auf Knopfdruck
je Gerät.

## Rollen und Rechte

| Aktion | ADMIN | MEMBER |
|---|---|---|
| Gerät manuell auslesen (`POST /api/systems/{id}/probe`) | ja | nein |
| Ausgelesene Fakten am Gerät / in der Doku sehen (fremde Routen) | ja | ja |
| Freigabe `allowProbe` setzen (siehe [zugangsdaten](../zugangsdaten/spec.md)) | ja | nein |
| Probe-Schalter in den Einstellungen ändern | ja | nein |

## Anforderungen

### Requirement: Opt-in pro Zugang
Das System DARF einen gespeicherten Zugang nur dann zum Anmelden an einem Gerät verwenden, wenn
ein Admin für genau diesen Zugang die Freigabe „Zum Auslesen verwenden“ (`allowProbe`) gesetzt hat;
Default ist aus. **[Muss]**

#### Szenario: Nicht freigegebener Zugang wird ignoriert
- **WENN** ein Zugang mit `allowProbe = 0` per Gruppe auf alle Router zugewiesen ist
- **DANN** taucht er in der Liste der Probe-Zugänge des Routers nicht auf; ein direkt angehängter
  und zusätzlich per Gruppe zugewiesener Zugang erscheint genau einmal

Quelle: `backend/app/db.py:1433`, Test: `backend/tests/test_db_account_assignments.py::test_list_probe_accounts_deduplicates_direct_and_assigned_and_ignores_allowprobe_off`

### Requirement: Probe-Zugänge je Gerät auflösen
Das System MUSS als Probe-Zugänge eines Geräts alle freigegebenen Zugänge nehmen, die direkt am
Gerät hängen oder per Zuordnung (Gerät, Gerätetyp `kind`, Subnetz, in dem die Geräte-IP liegt) auf
es zeigen, ohne Duplikate, sortiert nach (Kategorie, Bezeichnung case-insensitiv). **[Muss]**

#### Szenario: Subnetz-Zuordnung
- **WENN** ein freigegebener Zugang dem Subnetz `192.168.2.0/24` zugeordnet ist und das Gerät
  die IP `192.168.2.10` hat
- **DANN** gehört der Zugang zu den Probe-Zugängen des Geräts

Quelle: `backend/app/db.py:1408`, Test: `backend/tests/test_db_account_assignments.py::test_list_probe_accounts_includes_subnet_assigned_credential`, `backend/tests/test_db_account_assignments.py::test_list_probe_accounts_includes_kind_assigned_credential`

### Requirement: Feste, nicht erweiterbare SSH-Befehlsliste
Das System MUSS per SSH ausschließlich Befehle aus fest eingebauten, lesenden Listen ausführen;
keine Einstellung, kein API-Parameter und kein LLM-Werkzeug darf die Listen erweitern oder
Befehle frei zusammensetzen. Verboten sind Paketmanager, Dienststeuerung, Umleitungen, `sudo`,
Konfigurationsmodus-Befehle (Ausnahmen siehe unten) und `/export show-sensitive`. **[Muss]**

Vollständige Listen (Schlüssel → Befehl), Quelle `backend/app/probe_auth.py:64`–`223`:

- **Linux (Default)**: `hostname` → `hostname`; `os` → `grep -E '^(PRETTY_NAME|NAME|VERSION)=' /etc/os-release 2>/dev/null | head -3 || uname -sr`;
  `kernel` → `uname -sr`; `model` → `cat /sys/firmware/devicetree/base/model 2>/dev/null || cat /sys/devices/virtual/dmi/id/product_name 2>/dev/null`;
  `virt` → `systemd-detect-virt 2>/dev/null`; `uptime` → `uptime -p 2>/dev/null || uptime`; `cpu` → `nproc 2>/dev/null`;
  `memory` → `free -h 2>/dev/null | awk 'NR==2{print $2" gesamt, "$3" belegt"}'`;
  `disks` → `df -h -x tmpfs -x devtmpfs -x overlay --output=target,size,used,pcent 2>/dev/null | head -8`;
  `ip` → `ip -4 -o addr show scope global 2>/dev/null | awk '{print $2" "$4}' | head -6`;
  `arp_table` → `ip neigh show 2>/dev/null | grep lladdr | head -200 || arp -an 2>/dev/null | head -200`;
  `docker` → `docker ps --format '{{.Names}} ({{.Image}}) {{.Status}}' 2>/dev/null | head -25`;
  `services` → `systemctl list-units --type=service --state=running --no-pager --no-legend 2>/dev/null | awk '{print $1}' | head -20`;
  `omada_backup` → `ls -1t /opt/tplink/EAPController/data/backup/*.cfg 2>/dev/null | head -1 | xargs -r base64 -w0 2>/dev/null`
- **MikroTik**: `/system identity print`, `/system resource print`, `/system routerboard print`,
  `/interface vlan print detail without-paging`, `/interface bridge port print detail without-paging`,
  `/ip neighbor print detail without-paging`, `/interface print detail without-paging`,
  `/ip address print without-paging`, `/ip arp print detail without-paging`, `/export compact` (`config_export`)
- **ArubaOS-Switch (klassisch)**: `show system-information`, `show vlan`, `show vlan ports all detail`,
  `show lldp info remote-device`, `show interfaces brief`, `show ip`, `show arp`, `show running-config`
  (`config_export`); Sitzungsvorlauf: Newline, ggf. `enable`, `no page`
- **ArubaOS-CX**: je mit vorangestelltem `no paging`: `show system`, `show vlan`, `show lldp neighbor-info`,
  `show interface brief`, `show interface vlan`, `show arp`, `show running-config`
- **Cisco IOS**: je mit `| no-more`: `show version`, `show vlan brief`, `show cdp neighbors detail`,
  `show interfaces status`, `show ip interface brief`, `show ip arp`, `show running-config`
- **TP-Link JetStream**: je mit vorangestelltem `configure` / `no clipaging` / `exit`: `show system-info`,
  `show vlan`, `show lldp neighbor-information`, `show interface status`, `show arp`, `show running-config`

#### Szenario: Klassisches Aruba sendet reine show-Befehle
- **WENN** die Aruba-Befehlsliste geprüft wird
- **DANN** enthält jeder Eintrag genau einen `show …`-Befehl ohne eingefalteten Pager-Befehl

Quelle: `backend/app/probe_auth.py:64`, Test: `backend/tests/test_probe_auth_aruba.py::test_aruba_commands_are_bare_show_commands_run_one_at_a_time`, `backend/tests/test_probe_auth_switch_paging.py::test_every_tplink_command_disables_paging_first`

### Requirement: Plattform-Erkennung
Das System MUSS die Befehlsliste anhand der Geräteangaben (Hersteller, Modell, Name, OS,
case-insensitiv) wählen, in dieser Reihenfolge: `mikrotik`/`routeros` → MikroTik; `aruba`/
`procurve`/`hewlett`/Wort `hp` → Aruba, darin `arubaos-cx`/`aos-cx`/Wort `cx` → ArubaOS-CX;
`cisco` → Cisco; `tp-link`/`tplink`/`jetstream` → TP-Link; sonst Linux. Die Kategorie eines
Zugangs bestimmt nie die Plattform. **[Muss]**

#### Szenario: HP ProCurve
- **WENN** ein Gerät als „HP ProCurve 2530“ beschrieben ist
- **DANN** wird die klassische Aruba-Liste verwendet, nicht ArubaOS-CX; „hp“ als Teilwort
  (z. B. Hersteller „Shpock GmbH“) löst keinen Treffer aus

Quelle: `backend/app/probe_auth.py:271`, Test: `backend/tests/test_probe_auth_platform.py::test_detect_platform_hp_procurve_maps_to_aruba`, `backend/tests/test_probe_auth_platform.py::test_detect_platform_hp_word_boundary_does_not_match_substring`, `backend/tests/test_probe_auth_aruba.py::test_detect_platform_arubaos_cx_by_explicit_string`

### Requirement: Welche Probes je Zugangskategorie laufen
Das System MUSS je Probe-Zugang folgende Leseverfahren starten (Host = IP, sonst Hostname; ohne
Adresse läuft nichts, Grund „Keine Adresse hinterlegt.“): **[Muss]**
- `sshkey`: immer SSH.
- `login` mit Port 0 oder 22: SSH nur (ein anderer Port gehört meist zur Weboberfläche; SSH dorthin
  wäre ein Fehlversuch mit Zugangsdaten für einen anderen Dienst – bewusst so, `sshkey` ist
  eindeutig SSH und darf jeden Port haben; `routes/remote.py::_ssh_eligible` trägt dieselbe Regel), wenn eine Netzwerk-Plattform erkannt ist oder `kind` ∈
  {server, nas, vm, pc, container}.
- `snmp`: SNMP. `homeassistant`: Home-Assistant-API (URL des Zugangs, sonst des Geräts).
- `login`/`apikey` mit URL (Zugang, sonst Gerät): HTTP-GET-Anmeldung.
- Gerät mit „fritz“ in Hersteller/Modell/Name oder `kind = router`: TR-064. Der erste Zugang der
  Kategorie `login` wird nur bei „fritz“ in Hersteller/Modell/Name mitgegeben (auch ohne Zugang,
  dann nur unauthentifizierter Teil); ein Nicht-FRITZ-Router bekommt nie Zugangsdaten an Port 49000.
  Die Kategorie `router` gibt es nicht mehr (Migration beim Start: `login`; die API lehnt Kategorien
  außerhalb der UI-Liste mit 422 ab).

#### Szenario: Nicht-FRITZ-Router bekommt keine TR-064-Anmeldung
- **WENN** ein Gerät `kind = router` ohne „fritz“ einen `login`-Zugang hat
- **DANN** läuft TR-064 ohne Zugang (nur unauthentifizierter Teil); das Passwort wird nicht gesendet
- `unifi`/`omada`/`proxmox`/`adguard`: eigene Controller-Probes (siehe unten).

#### Szenario: Login-Zugang auf Drucker ohne Plattform
- **WENN** ein `login`-Zugang (Port 0) an einem Gerät `kind = printer` ohne erkannte Plattform hängt
- **DANN** wird keine SSH-Verbindung aufgebaut, nur ggf. HTTP gegen die hinterlegte URL

Quelle: `backend/app/probe_auth.py:1367`

### Requirement: Ergebnisse je Art
Das System MUSS jedes Probe-Ergebnis unter `<art>:<label>` (`ssh`, `snmp`, `ha`, `http`) bzw.
`tr064` speichern, auch Fehlschläge (inkl. HTTP-Anmeldung abgelehnt/nicht erreichbar), damit die
Pipeline je Fehlschlag ein Fehlerereignis schreibt. Ein Fehlschlag, neben dem ein Zugang
derselben Art Erfolg hatte, MUSS mit `superseded = true` markiert werden (die Technik-Seite zeigt
„nachrangig“); er wird nicht verworfen. TR-064-Fehlschläge MÜSSEN nur bei Geräten mit „fritz“ in
Hersteller/Modell/Name gespeichert werden (sonst Fehlerereignis je Scan für jeden Nicht-AVM-Router).
Ebenso MÜSSEN HTTP-Fehlschläge nur für Zugänge gespeichert werden, die erkennbar für die Weboberfläche
gedacht sind (`apikey`, eigene URL am Zugang oder `login` mit Port ≠ 22/leer); ein SSH-Login an einem
Gerät mit Geräte-URL wird per HTTP nur nebenbei versucht, sein Fehlschlag wird verworfen.
Fehlertexte aller Arten DÜRFEN keine Zugangsdaten aus einer URL (`user:pass@`, auch mit `@` im
Passwort) enthalten. **[Muss]**

#### Szenario: Abgelaufener zweiter Zugang
- **WENN** zwei HA-Zugänge existieren, einer funktioniert, einer hat ein abgelaufenes Token
- **DANN** stehen beide in `results`, der fehlerhafte mit `superseded = true`, und er erzeugt ein Fehlerereignis

#### Szenario: Nur Fehlschläge
- **WENN** alle Zugänge einer Art fehlschlagen
- **DANN** wird keiner als `superseded` markiert

#### Szenario: Abgelehnter Web-Login
- **WENN** ein `login`-Zugang mit Web-Port (z. B. 8443) oder eigener URL von der Weboberfläche abgelehnt wird
- **DANN** steht `http:<label>` mit `ok = false` und Fehlertext im Ergebnis

#### Szenario: SSH-Login an Gerät mit Web-Oberfläche
- **WENN** ein `login`-Zugang mit Port 22 (oder leer) an einem Gerät mit URL beim HTTP-Versuch abgelehnt wird
- **DANN** fehlt `http:<label>` im Ergebnis, und es entsteht kein Fehlerereignis

### Requirement: SSH-Verbindungsparameter
Das System MUSS SSH mit Benutzer (Default `root`), Port (Default 22), Verbindungs-Timeout 10 s
und 15 s Timeout je Befehl aufbauen; Schlüssel-Login, wenn Kategorie `sshkey` oder das Secret
„PRIVATE KEY“ enthält (Passphrase aus dem Zugang), sonst Passwort-Login. Bei Schlüssel-Login DARF
das System nicht auf eigene Schlüssel des Containers ausweichen. Hostschlüssel werden nicht
geprüft. **[Muss]** (Hostschlüssel-Verzicht: bewusste Abwägung, README „Sicherheit“)

#### Szenario: Unlesbarer Schlüssel
- **WENN** der hinterlegte Schlüssel nicht importiert werden kann
- **DANN** ist das Ergebnis `ok: false` mit „Der hinterlegte SSH-Schlüssel ließ sich nicht lesen: …“

Quelle: `backend/app/probe_auth.py:433`

### Requirement: Fehlertoleranz je SSH-Befehl
Das System MUSS einzelne fehlschlagende Befehle überspringen, ohne die Probe abzubrechen; ein
Befehl über 15 s erzeugt eine Warnung („„<Label>“ hat innerhalb von 15 Sekunden nicht geantwortet …“).
Liefert kein Befehl Ausgabe, ist das Ergebnis `ok: false` mit „Verbindung stand, aber kein Befehl
lieferte eine Ausgabe.“ plus Warnungen. Ein fehlgeschlagener Befehl führt nie zu einem
aggressiveren Zweitversuch. **[Muss]**

#### Szenario: Zeitüberschreitung eines Befehls
- **WENN** ein Befehl nicht innerhalb von 15 s antwortet
- **DANN** enthält `warnings` einen Hinweis mit dem Befehlslabel, übrige Fakten bleiben erhalten

Quelle: `backend/app/probe_auth.py:493`, Test: `backend/tests/test_probe_auth_aruba.py::test_probe_ssh_logs_a_clear_warning_when_a_command_times_out`

### Requirement: Klassisches ArubaOS-Switch ohne Fremd-Credentials
Das System MUSS bei klassischem Aruba eine einzige interaktive Sitzung (Terminal vt100) nutzen:
Banner per Newline bestätigen; nur am Operator-Prompt (`>`) einmal `enable` senden, aber NIE eine
Benutzer-/Passwortabfrage beantworten – erscheint eine, bricht die Probe mit Warnung ab; danach
`no page` und die Befehle. Gesamtbudget 45 s, ein Befehl gilt nach 0,6 s Ruhe als fertig;
Echo-Zeile und abschließender Prompt werden entfernt. **[Muss]** (Nie-antworten), Zeiten **[Impl]**

#### Szenario: enable verlangt Manager-Passwort
- **WENN** der Switch nach `enable` mit „Password:“ antwortet
- **DANN** wird nichts eingegeben, keine Fakten gesammelt und die Warnung „„enable“ verlangt
  eigene Manager-Zugangsdaten …“ zurückgegeben

Quelle: `backend/app/probe_auth.py:371`, Test: `backend/tests/test_probe_auth_aruba.py::test_probe_ssh_aruba_gives_up_without_answering_a_manager_credential_prompt`, `backend/tests/test_probe_auth_aruba.py::test_probe_ssh_aruba_skips_enable_when_session_already_at_manager_prompt`

### Requirement: Pager-Unterdrückung und Terminal
Das System MUSS Pager so unterdrücken, dass lange Ausgaben vollständig ankommen: Cisco über
`| no-more`, ArubaOS-CX und TP-Link durch Einfalten des Pager-Befehls in dieselbe Befehlszeichenkette;
für ArubaOS-CX, Cisco und TP-Link mit Pseudo-Terminal (vt100), für Linux und MikroTik ohne. **[Impl]**

#### Szenario: Linux ohne PTY
- **WENN** ein Linux-Host per SSH ausgelesen wird
- **DANN** wird kein Pseudo-Terminal angefordert

Quelle: `backend/app/probe_auth.py:236`, Test: `backend/tests/test_probe_auth_aruba.py::test_probe_ssh_does_not_request_a_pty_for_plain_linux_hosts`, `backend/tests/test_probe_auth_switch_paging.py::test_cisco_running_config_already_suppresses_paging_with_no_more`

### Requirement: Größenbegrenzung gespeicherter Fakten
Das System MUSS die Ausgabe je Fakt begrenzen: allgemein 1.200 Zeichen, Konfigurationsexport
(`config_export`) 60.000 Zeichen; binäre Sicherung (`omada_backup`, Base64) wird ab 4.000.000
Zeichen komplett verworfen statt gekürzt. Leere Ausgabe ergibt keinen Fakt. **[Muss]** (Verwerfen
statt Kürzen bei Binärdaten), Zahlen **[Impl]**

#### Szenario: Zu große Binärsicherung
- **WENN** die Base64-Sicherung ≥ 4.000.000 Zeichen lang ist
- **DANN** wird kein `omada_backup`-Fakt gespeichert

Quelle: `backend/app/probe_auth.py:253`, Test: `backend/tests/test_probe_auth_aruba.py::test_bounded_fact_drops_an_oversized_binary_backup_entirely`, `backend/tests/test_probe_auth_aruba.py::test_bounded_fact_gives_config_export_the_wide_limit`

### Requirement: HTTP-Anmeldung nur per GET
Das System MUSS die Web-URL nur per GET abrufen, zuerst mit Basic-, dann mit Digest-Auth
(Timeout 10 s, Connect 5 s, Redirects folgen, TLS-Zertifikat ungeprüft) und Fakten Seitentitel
(≤150 Zeichen), `Server`-Header (≤120), erkannte Version und Anmeldeart liefern. Es MUSS
„nicht erreichbar“ von „Zugangsdaten abgelehnt“ (401/403 bei beiden Verfahren) unterscheiden.
URL ohne `http(s)://` oder Zugang ohne Benutzer und Passwort → Fehler ohne Verbindungsversuch. **[Muss]**

#### Szenario: Host nicht erreichbar
- **WENN** beide Versuche mit Transportfehler scheitern
- **DANN** lautet der Fehler „<url> war nicht erreichbar (…)“, nicht „abgelehnt“

Quelle: `backend/app/probe_auth.py:529`

### Requirement: Home Assistant lesen
Das System MUSS mit Long-Lived-Token (Bearer) zuerst `GET <basis>/api/` prüfen (Antwort
`{"message": "API running."}`), 401/403 als „Token abgelehnt“ und eine fremde Antwort als „Adresse
prüfen“ melden; dann `GET /api/states` lesen und liefern: bis zu 60 Automationen inkl.
deaktivierter („ein“/„aus“), Beschreibung aus der Automationskonfiguration oder ersatzweise
Kurzfassung „Auslöser: …; Aktion: …“, „zuletzt ausgelöst“ als `TT.MM.JJJJ HH:MM` (unparsbar →
Rohwert); KNX-Anbindung aus `knx_interface`-Sensoren; Drucker-Verbrauchsmaterial aus
`sensor.*`-Entitäten mit toner/ink/cartridge/drum. Timeout 15 s/Connect 5 s; nur GET. **[Muss]**

#### Szenario: Falsche Adresse
- **WENN** unter `/api/` ein anderer Webserver ohne die erwartete Meldung antwortet
- **DANN** ist der Fehler „… hat nicht wie die Home-Assistant-API geantwortet -- Adresse prüfen …“,
  nicht „Token abgelehnt“

Quelle: `backend/app/probe_auth.py:675`, `backend/app/probe_auth.py:704`, Test: `backend/tests/test_probe_auth_homeassistant.py::test_self_check_reports_wrong_endpoint_distinctly_from_auth_failure`, `backend/tests/test_probe_auth_printer_supplies.py::test_probe_homeassistant_includes_disabled_automations_with_explicit_status`, `backend/tests/test_probe_auth_homeassistant.py::test_automation_line_includes_last_triggered_when_present`

### Requirement: SNMP nur lesend
Das System MUSS SNMP v2c mit der Community aus dem Zugang (Port aus Zugang, Default 161) nur per
`snmpget`/`snmpwalk` mit fester Argumentliste (kein Shell-String) abfragen, je Aufruf `-t 3 -r 1`
und harte Obergrenze 10 s; feste OIDs: sysName, sysDescr, ifDescr (Walk), LLDP-Remote-Tabelle,
Q-BRIDGE-VLANs, ipNetToMediaPhysAddress. Ausgaben mit „Timeout“/„No Such“ werden verworfen, sonst
≤20.000 Zeichen. Ohne Antwort: „Keine SNMP-Antwort von <host:port>. Community-Zeichenkette prüfen …“. **[Muss]**

#### Szenario: Kein Druckerteil bei Nicht-Druckern
- **WENN** der Zugang an einem Gerät mit `kind ≠ printer` hängt
- **DANN** werden keine Toner-OIDs abgefragt

Quelle: `backend/app/probe_auth.py:905`, Test: `backend/tests/test_probe_auth_printer_snmp.py::test_probe_snmp_skips_printer_supplies_for_non_printer_kind`

### Requirement: Druckerverbrauchsmaterial per SNMP
Das System MUSS bei `kind = printer` Tonerstände je Farbe (Schwarz, Magenta, Cyan, Gelb) aus den
Brother-OIDs lesen und bei fehlendem oder exakt 0 % Wert auf die Printer-MIB-Zeile der Farbe
(englischer Farbname in der Beschreibung) zurückfallen; ohne verlässlichen Wert entfällt die Farbe.
Negative Level (RFC-3805-Statuscodes) und Kapazität ≤ 0 sind nie Prozentwerte. Nicht-Toner-Teile
(Trommel, Band …) erscheinen separat als Wartungsteile. Jeder Fallback wird mit Rohwerten geloggt. **[Muss]**

#### Szenario: Falsche 0 % bei Magenta
- **WENN** die Brother-OID für Magenta 0 liefert, die Printer-MIB-Zeile „Magenta Toner“ aber 40/100
- **DANN** wird Magenta mit 40 % gespeichert, die anderen Farben bleiben unberührt

Quelle: `backend/app/probe_auth.py:1115`, Test: `backend/tests/test_probe_auth_printer_snmp.py::test_merge_brother_toner_levels_falls_back_when_direct_oid_is_zero`, `backend/tests/test_probe_auth_printer_snmp.py::test_percent_from_level_capacity_rejects_negative_level_and_nonpositive_capacity`, `backend/tests/test_probe_auth_printer_snmp.py::test_probe_snmp_reports_drum_and_belt_under_consumables_maintenance`

### Requirement: FRITZ!Box TR-064
Das System MUSS auf Port 49000 `tr64desc.xml` ohne Anmeldung lesen (Gerätename, Modell,
Modellnummer, Hersteller) und mit Digest-Auth nur `DeviceInfo:GetInfo` (Firmware, Seriennummer,
Modell, Beschreibung, Laufzeit) und `Hosts:X_AVM-DE_GetHostListPath` + Abruf der Hostliste
(„IP MAC Name (aktiv|inaktiv)“, ≤20.000 Zeichen) ausführen; nie eine `Set*`-Aktion. Ohne jede
Antwort: Hinweis auf „Zugriff für Anwendungen zulassen“. **[Muss]**

#### Szenario: Ohne Zugangsdaten
- **WENN** kein `login`-Zugang vorhanden ist
- **DANN** werden nur die unauthentifizierten Beschreibungsdaten gelesen

Quelle: `backend/app/probe_auth.py:1200`

### Requirement: Standard-Zugang als Fallback
Das System MUSS einen global konfigurierten Standard-SSH-Zugang nur im Vollscan und nur dann
verwenden, wenn (a) aktiviert, (b) Secret gesetzt, (c) das Gerät keinen eigenen Probe-Zugang hat,
(d) `kind` ∈ {server, nas, vm, pc, container} und (e) der Port (Default 22) im letzten Scan offen
war. Nie gegen Router oder unidentifizierte Geräte. **[Muss]**

#### Szenario: Port nicht offen
- **WENN** Port 22 beim Server nicht in `openPorts` steht
- **DANN** wird der Standard-Zugang dort nicht versucht (kein Credential-Spraying)

Quelle: `backend/app/probe_auth.py:1328`, `backend/app/pipeline.py:83`

### Requirement: Ergebnisse am Gerät speichern
Das System MUSS die Ergebnisse je Quelle (Schlüssel `<art>:<Zugangsbezeichnung>`, z. B.
`ssh:Root`, `snmp:…`, `ha:…`, `http:…`, `tr064`, `unifi:…`) mit `ok`, `error`, `facts`
(`{label, value}`) und ggf. `warnings` am Gerät ablegen und dabei das vorige Probe-Ergebnis
vollständig ersetzen. Leere Felder `purpose` (aus Rollenhinweisen: Docker → Server mit Containern,
Virtualisierung → VM/Container), im Vollscan zusätzlich `os` (erste Zeile, ≤120) und `model`
(≤100), werden nur gefüllt, wenn sie leer sind – nie Überschreiben menschlicher Eingaben. **[Muss]**

#### Szenario: Manuell gepflegtes Modell bleibt
- **WENN** das Gerät bereits ein Modell hat und SSH ein anderes meldet
- **DANN** bleibt das gespeicherte Modell unverändert

Quelle: `backend/app/pipeline.py:115`, `backend/app/probe_auth.py:1315`

### Requirement: Konfigurationsversionen sichern
Das System MUSS Fakten `config_export` und `omada_backup` erfolgreicher Ergebnisse als
Konfigurationsversion des Geräts (Label „<Gerätename> – <Faktlabel>“, Quelle = Ergebnisschlüssel)
verschlüsselt speichern, aber nur, wenn sich der Inhalt gegenüber der neuesten Version gleichen
Labels geändert hat (Vergleich ohne Zeilen, die mit `#` beginnen). Je Gerät und Label bleiben die
neuesten `configVersionKeep` Versionen (Default 50, begrenzt auf 1–1000). Es gibt keinen Weg,
eine Version zurück aufs Gerät zu schreiben. Diese Fakten DÜRFEN nicht in `systems.extra.probe`
gespeichert werden (dort lesen MEMBER, Doku und LLM); dort landet nur das Ergebnis ohne sie
(`probe_auth.without_config_backups`). Beim Start entfernt das System Klartext-Kopien, die ältere
Versionen gespeichert haben, auch aus Doku-Ständen und gespeicherten Werkzeugergebnissen des
Assistenten. **[Muss]** Test: `backend/tests/test_secrets_at_rest.py`

#### Szenario: Nur Zeitstempel geändert
- **WENN** ein MikroTik-Export sich nur in der Kommentarzeile mit Zeitstempel unterscheidet
- **DANN** wird keine neue Version angelegt

Quelle: `backend/app/probe_auth.py:1529`, `backend/app/db.py:1694`

### Requirement: Geräte aus Router-ARP-Tabellen lernen
Das System MUSS im Vollscan aus ARP-/Hostlisten-Fakten (`arp_table`, `arpTable`, `hostList`)
erfolgreicher Probes von Geräten mit `kind = router` IP→MAC-Paare lesen (Formate: Linux, RouterOS,
Cisco-Punktnotation, Aruba `aabbcc-ddeeff`, SNMP-Oktette; 0.0.0.0/255.255.255.255 ignoriert) und
für Paare, deren MAC und IP noch unbekannt sind, Geräte anlegen: `kind = other`, Name aus
Reverse-DNS, sonst „<Herstellerwort> (<letztes Oktett>)“, sonst IP; Quelle `gateway-arp`. **[Muss]**

#### Szenario: SNMP-Walk-Zeile
- **WENN** eine Zeile `IP-MIB::ipNetToMediaPhysAddress.6.192.168.1.40 = STRING: aa bb cc dd ee ff` lautet
- **DANN** ergibt sich `192.168.1.40 → aa:bb:cc:dd:ee:ff` (Schnittstellenindex 6 nicht als Oktett)

Quelle: `backend/app/probe_auth.py:1465`, `backend/app/pipeline.py:142`, Test: `backend/tests/test_probe_auth_arp.py::test_parse_arp_pairs_snmp_walk_space_separated_octets`, `backend/tests/test_probe_auth_arp.py::test_extract_arp_entries_merges_across_facts_and_skips_failed_results`

### Requirement: Druckerstände dem richtigen Drucker zuordnen
Das System MUSS im Vollscan Prozentzeilen („- Name: Wert%“) aus `printerSupplies`-Fakten an
Drucker im Inventar (`extra.printerSupplies`) hängen: bei genau einem Drucker alles an diesen,
sonst je Wert an den Drucker mit größter Wortüberlappung (Wörter ≥3 Zeichen aus Name/Hersteller/
Modell); ohne Überlappung verworfen. Nicht-Prozentwerte werden nicht übernommen. **[Muss]**

#### Szenario: Rohcode statt Prozent
- **WENN** ein Sensor einen HP-Versorgungscode statt eines Prozentwerts liefert
- **DANN** wird er nicht als Füllstand übernommen

Quelle: `backend/app/probe_auth.py:1494`, `backend/app/pipeline.py:196`, Test: `backend/tests/test_probe_auth_printer_supplies.py::test_extract_printer_supplies_ignores_non_percentage_and_failed_results`

### Requirement: Fehler und Warnungen je Gerät protokollieren
Das System MUSS im Vollscan jedes fehlgeschlagene Ergebnis als Fehlerereignis und jede Warnung
als Warnungsereignis am Gerät speichern und zusätzlich in die Scan-Warnungen schreiben – auch
wenn ein anderer Zugang am selben Gerät erfolgreich war. Eine Ausnahme bei einem Gerät beendet
den Scan nicht. Fehlermeldungen enthalten nie ein Secret. **[Muss]**

#### Szenario: SSH ok, HA-Token abgelaufen
- **WENN** SSH erfolgreich ist und Home Assistant 401 liefert
- **DANN** gilt das Gerät als ausgelesen, und es entsteht genau ein Fehlerereignis „…Zugriffstoken abgelehnt…“

Quelle: `backend/app/pipeline.py:102`, Test: `backend/tests/test_pipeline_probe_warnings.py::test_probe_with_credentials_logs_failure_even_when_another_credential_on_same_system_succeeds`

### Requirement: UniFi Network lesen
Das System MUSS mit API-Key (Header `X-API-Key`) nur feste GET-Endpunkte unter
`<url>/proxy/network/integration/v1` aufrufen: `/info`, `/sites`, je Site `/devices` (+ Detail je
Gerät, max. 8 parallel), `/clients` (nur WIRED/WIRELESS), `/networks` (+ Detail), `/wifi/broadcasts`,
`/wans`; Seitengröße 200 über `offset`/`limit` bis `totalCount`. Geräte → `kind` router (Feature
`gateway`) sonst network, Hersteller Ubiquiti; Netze/WLANs/WANs → Netzwerkressourcen. Fehler eines
Teilbereichs einer Site → Warnung, Bereich gilt als nicht vollständig. 401/403 → „Der UniFi
API-Key wurde abgelehnt.“ ohne den Key zu nennen. Timeout 15 s/Connect 5 s, TLS ungeprüft.
Clients MÜSSEN nur übernommen werden, wenn ihre IPv4-Adresse in einem der Scan-Netze
(`discovery.effective_subnets`, als `client_subnets` übergeben) liegt; Clients ohne IP werden dabei
übersprungen, Geräte nie gefiltert, bestehende Einträge nie angefasst. Leere bzw. nur ungültige
Netzliste = kein Filter. **[Muss]**

#### Szenario: Key abgelehnt
- **WENN** der Controller 401 liefert
- **DANN** ist `ok: false`, die Meldung enthält „API-Key“, aber nicht den Key selbst

#### Szenario: Gäste-Client außerhalb der Scan-Netze
- **WENN** `client_subnets=["192.168.1.0/24"]` gilt und Clients mit IP in 192.168.1.x, 192.168.50.x und ohne IP existieren
- **DANN** werden nur die Clients aus 192.168.1.x und alle Geräte übernommen, `skippedClients` zählt die übrigen

Quelle: `backend/app/unifi_probe.py:169`, Test: `backend/tests/test_unifi_probe.py::test_probe_filters_clients_by_subnets`, `backend/tests/test_unifi_probe.py::test_probe_without_client_subnets_keeps_all_clients`, `backend/tests/test_unifi_probe.py::test_probe_ignores_invalid_subnet_entries`, `backend/tests/test_main_unifi_probe.py::test_manual_probe_passes_scan_subnets`, `backend/tests/test_main_unifi_probe.py::test_manual_probe_falls_back_to_host_subnets`, `backend/tests/test_main_unifi_probe.py::test_filtered_client_does_not_delete_existing_system`; `backend/tests/test_unifi_probe.py::test_probe_reports_authentication_failure_without_echoing_api_key`, `backend/tests/test_unifi_probe.py::test_probe_normalizes_all_unifi_sites_without_persisting_api_key`

### Requirement: Omada Controller lesen
Das System MUSS `GET /api/info` (→ `omadacId`), den Client-Credentials-Token-Tausch
`POST /openapi/authorize/token` (einzige Nicht-GET-Anfrage) und danach nur GETs mit Header
`Authorization: AccessToken=<token>` ausführen: Sites (100/Seite), Geräte je Site (100/Seite),
Clients je Site (500/Seite), jeweils nur Seite 1. Gerätetypen ap/switch → network, gateway →
router; Status 1 = online; Uplink-MAC aus mehreren möglichen Feldern; Clients ohne `kind`. **[Muss]**

#### Szenario: Uplink fehlt
- **WENN** ein Gerät kein bekanntes Uplink-Feld trägt
- **DANN** ist `uplinkMac` leer und der Scan läuft weiter

Quelle: `backend/app/omada_probe.py:63`, Test: `backend/tests/test_omada_probe.py::test_extract_uplink_missing_returns_empty`, `backend/tests/test_omada_probe.py::test_extract_uplink_prefers_nested_over_flat`

### Requirement: Proxmox VE lesen
Das System MUSS mit API-Token (`Authorization: PVEAPIToken=<id>=<secret>`) nur GETs ausführen:
`/api2/json/nodes`, je Node `qemu` und `lxc`, je Gast `/config`. MAC/IP aus `net0`; Notizen: erste
`Doc:`/`URL:`-Zeile → `docLink`, erste übrige Textzeile → `purpose` (≤200), Gesamttext →
`descriptionMd` (≤800); Tag `critical` (`;`/`,`-getrennt) → `importance = critical` (nur
hochstufen). Gäste mit `template: 1` (qemu und lxc) werden nicht übernommen und es erfolgt
kein `/config`-Abruf für sie. Scheitern alle Gästelisten und wurde nichts gefunden → Fehler mit Hinweis auf
Token-Berechtigung (PVEAuditor). **[Muss]**

#### Szenario: Kritischer Gast
- **WENN** ein Gast die Tags `web;critical` trägt
- **DANN** erhält der Fund `importance = critical`

#### Szenario: Template
- **WENN** ein Gast `template: 1` hat
- **DANN** erscheint er nicht in den Funden

Quelle: `backend/app/proxmox_probe.py:115`, Test: `backend/tests/test_proxmox_probe.py::test_probe_sets_critical_importance_docs_and_purpose_from_notes`, `backend/tests/test_proxmox_probe.py::test_probe_skips_templates`, `backend/tests/test_db_systems_templates.py::test_missing_discovered_proxmox_row_is_kept_and_set_offline`, `backend/tests/test_proxmox_probe.py::test_parse_notes_does_not_match_url_mentioned_mid_sentence`

### Requirement: AdGuard Home lesen
Das System MUSS per Basic Auth nur GETs ausführen: `/control/dns_info` (Pflicht; 401/403 →
„Zugangsdaten abgelehnt“), `/control/stats`, `/control/dhcp/status`, `/control/clients` (optional,
Fehler ignoriert). Statistik (Schutz an/aus, Anzahl Upstreams, Anfragen, blockiert, Blockquote
auf 0,1 %) wird am Gerät des Zugangs (`extra.adguard`) gespeichert; DHCP-Leases und Clients mit
Hostname und MAC werden als Funde geliefert, je MAC nur einmal (Lease vor Client). Timeout 10 s/5 s. **[Muss]**

#### Szenario: Lease ohne Hostname
- **WENN** eine DHCP-Lease keinen Hostnamen hat
- **DANN** entsteht kein Fund

Quelle: `backend/app/adguard_probe.py:100`, `backend/app/pipeline.py:458`, Test: `backend/tests/test_adguard_probe.py::test_probe_skips_dhcp_leases_without_a_hostname`, `backend/tests/test_adguard_probe.py::test_probe_survives_missing_stats_endpoint`, `backend/tests/test_adguard_probe.py::test_probe_deduplicates_a_mac_seen_in_both_dhcp_and_clients`

### Requirement: Docker-Host lesen
Das System MUSS den lokalen Docker-Socket (`DOCKER_SOCKET`, Default `/var/run/docker.sock`) nur
per GET (`/version`, `/info`, `/containers/json?all=1`, `/networks`, `/volumes`; Timeout 15 s/5 s)
lesen. Container-Name „<service> · <projekt>“ bei Compose, sonst Containername; stabiler Schlüssel
`docker:<projekt>:<service>` bzw. `docker:<name>`, Alt-Schlüssel `docker:<id12>` zur Migration;
nur veröffentlichte Ports; Standort = Docker-Hostname. Fehlender Socket ist kein Scan-Fehler. **[Muss]**

#### Szenario: Gleichnamige Dienste in zwei Projekten
- **WENN** `immich` und `paperless` je einen Dienst `postgres` haben
- **DANN** heißen sie „postgres · immich“ und „postgres · paperless“

Quelle: `backend/app/docker_probe.py:54`, Test: `backend/tests/test_docker_probe.py::test_container_names`

### Requirement: Controller-Probes im Vollscan
Das System MUSS im Vollscan alle Zugänge der Kategorien `unifi`, `omada`, `proxmox`, `adguard` mit
Freigabe abfragen – unabhängig von Gerätezuordnung – und ihre Funde ins Inventar übernehmen;
Proxmox-Gäste unter den Host des Zugangs hängen; Fehler als Scan-Warnung und Fehlerereignis am
Gerät des Zugangs. Jede Quelle ist nur per eigener Einstellung abschaltbar (`scanEnableUnifi`/
`Omada`/`Proxmox`/`Adguard`/`Docker`, Default an); `scanUseCredentials` (Default an) schaltet
ausschließlich das Auslesen je Gerät (`_probe_with_credentials`, inkl. ARP-Lernen und
Druckerfüllstände) ab, nicht die Controller-Probes. **[Muss]**

#### Szenario: Auslesen abgeschaltet
- **WENN** `scanUseCredentials = false` und ein freigegebener `unifi`-Zugang existiert
- **DANN** protokolliert der Scan „Auslesen per Zugangsdaten ist in den Einstellungen abgeschaltet“
  und liest kein Gerät einzeln aus (SSH/HTTP/SNMP/TR-064/HA), meldet sich aber weiterhin mit dem Zugang am
  UniFi-Controller an (ebenso Omada, Proxmox, AdGuard, sofern deren `scanEnable*` an ist)

Quelle: `backend/app/pipeline.py:376`, `backend/app/pipeline.py:387`–`:455`, `backend/app/pipeline.py:521`

### Requirement: Gerät manuell auslesen
Das System MUSS Admins erlauben, ein Gerät sofort auszulesen: unbekanntes Gerät → 404; ohne
freigegebenen Zugang → 400 „Für dieses Gerät ist kein Zugang freigegeben …“; sonst alle Probes
des Geräts plus vollständige UniFi-Synchronisierung für `unifi`-Zugänge (Funde, Netzwerkressourcen,
Topologie-Verknüpfung). Antwort `{outcome: {ran, results, purpose, reason}, system}`; scheitern
nur UniFi-Zugänge, ist `ran = false` und `reason` = Fehlermeldungen, „ · “-getrennt. **[Muss]**

#### Szenario: UniFi-Sync auf Knopfdruck
- **WENN** ein Admin am Controller „Gerät auslesen“ auslöst
- **DANN** ist `outcome.ran = true`, der neue Switch hängt unter dem Controller und das VLAN ist aktiv

Quelle: `backend/app/main.py:1344`, Test: `backend/tests/test_main_unifi_probe.py::test_manual_unifi_probe_syncs_devices_topology_and_network_resources`, `backend/tests/test_main_unifi_probe.py::test_manual_unifi_probe_returns_the_controller_error`

### Requirement: Lese-/Schreibtrennung
Das System MUSS die lesenden Probe-Module strikt von schreibenden Modulen (Remote-Admin,
Container-/Gast-Steuerung) trennen: kein Probe-Modul nutzt Schreibfunktionen, und das LLM erreicht
keine Schreibfunktion über die Probes (ADR 0012). **[Muss]** Einzige Nicht-GET-Verbindung zu Home Assistant ist ein WebSocket, der nur
`trace/list` und `trace/get` sendet (exakter Vergleich gegen eine feste Liste, sonst `ValueError`).

#### Szenario: Kein Schreibpfad
- **WENN** ein LLM-Werkzeug oder der Scan eine Probe auslöst
- **DANN** kann dabei kein Befehl außerhalb der festen Leselisten an ein Gerät gehen

Quelle: `backend/app/probe_auth.py:1`, `docs/adr/0012-lesender-websocket-fuer-ha-traces.md`, Test: `backend/tests/test_probe_auth_ha_ws.py::test_disallowed_type_rejected`

## Daten

Siehe [data-model](../../contracts/data-model.md).
- Liest `accounts` (alle Felder, `secretEnc`/`passphraseEnc` entschlüsselt nur im Speicher),
  `accountAssignments`, `systems` (ip, hostname, kind, vendor, model, name, os, openPorts, url, purpose).
- Schreibt `systems.extra.probe` (Ergebnisse), `systems.purpose/os/model` (nur leer),
  `systems.extra.printerSupplies`, `systems.extra.adguard`, neue/aktualisierte `systems` aus
  Controller-/Docker-/ARP-Funden, `networkResources` (UniFi), `deviceConfigVersions`
  (`content` verschlüsselt), `deviceErrorEvents` (Level `error`/`warning`).
- Settings: `scanUseCredentials`, `scanEnableDocker`, `scanEnableUnifi`, `scanEnableOmada`,
  `scanEnableProxmox`, `scanEnableAdguard`, `scanEnableTraefik`, `scanEnableUnifiClassic`, `scanEnableExposureFiles`, `configVersionKeep`, `defaultCredentialEnabled`,
  `defaultCredentialUsername`, `defaultCredentialIsKey`, `defaultCredentialSecretEnc`,
  `defaultCredentialPassphraseEnc`, `defaultCredentialPort` (alle nur gelesen).

## Schnittstellen

| Methode | Pfad | Rolle | Zweck |
|---|---|---|---|
| POST | /api/systems/{system_id}/probe | ADMIN | Gerät sofort mit allen freigegebenen Zugängen auslesen (inkl. UniFi-Sync) |

Berührte fremde Routen: Konfigurationsversionen `GET /api/systems/{id}/config-versions[/{vid}]` und
Fehlerereignisse `GET /api/systems/{id}/errors` ([inventar](../inventar/spec.md)); Vollscan
([discovery-und-scan](../discovery-und-scan/spec.md)); Freigabe/Zuordnung
([zugangsdaten](../zugangsdaten/spec.md)); Standard-Zugang ([einstellungen-und-llm-provider](../einstellungen-und-llm-provider/spec.md)).

UI-Seite(n): `frontend/src/pages/device/DevicePage.tsx` (Route `/geraete/:id`, Knopf „Gerät
auslesen“, nur Admin und nur wenn ein Zugang `allowProbe` hat).

## Nicht-Ziele und Grenzen

- Keine Konfigurationsänderung, kein Neustart, kein Zurückspielen von Sicherungen (siehe
  [remote-admin](../remote-admin/spec.md) für Schreibaktionen).
- Keine Hostschlüssel-/Zertifikatsprüfung (SSH, HTTPS, Controller-APIs).
- SNMP nur v2c; keine strukturierte Auswertung von VLAN-/LLDP-Walks (Rohtext).
- Klassisches Aruba (das Zugangsformular der Kategorie `login` weist am Benutzernamen darauf hin): kein Beantworten einer `enable`-Passwortabfrage – nur Konten mit
  Manager-Rechten liefern `show running-config`.
- Omada: nur erste Seite (100 Geräte, 500 Clients je Site).

## Ist-Implementierung (nur Referenz, [Impl])

- Python/asyncssh, httpx, net-snmp-CLI (`snmpget`/`snmpwalk`) per `create_subprocess_exec`.
- Pro SSH-Befehl ein eigener Exec-Kanal (außer klassisches Aruba: eine interaktive Sitzung).
- `persist_config_backups` ist der einzige Speicherzugriff in `probe_auth.py`.
- Ergebnis-Dict je Probe: `{ok, error, facts, warnings?}`; Faktwerte sind Text, mehrzeilig möglich.
- Fortschritt im Scan: Docker 86 %, UniFi/Omada 87 %, Proxmox/AdGuard 88 %, Zugänge 93 %.

## OFFEN

- > OFFEN: TP-Link-Pager-Abschaltung nutzt `configure` / `no clipaging` – ein
  Konfigurationsmodus-Befehl, entgegen „kein Config-Mode“. Ob die Einstellung persistent in der
  Running-Config landet, ist ungeprüft.
- > OFFEN: Manuelles Auslesen behandelt `omada`/`proxmox`/`adguard`-Zugänge nicht (sie gehen an
  `probe_auth.probe_system`, das sie ignoriert) → bei solchen Geräten `ran = false` ohne Grund.
  Ebenso ignoriert es `scanUseCredentials`/`scanEnable*`, den Standard-Zugang, ARP-Lernen,
  Druckerzuordnung, `os`/`model`-Füllung und Fehlerereignisse. → #135
- > OFFEN: Im Vollscan nutzen Controller-Probes alle freigegebenen Zugänge der Kategorie,
  beim manuellen Auslesen nur die dem Gerät (direkt/per Zuordnung) zugeordneten – uneinheitlich. → #135
- > OFFEN: `omada_backup` läuft auf jedem Linux-Host und wird Base64-kodiert als Fakt gespeichert;
  ein Restore ist bewusst nicht vorgesehen, Nutzen der Speicherung ist unklar.
- > OFFEN: Omada liest nur Seite 1 (Geräte 100, Clients 500); größere Sites werden still abgeschnitten.
  Ein `errorCode` bei Geräten überspringt auch die Clients der Site.
