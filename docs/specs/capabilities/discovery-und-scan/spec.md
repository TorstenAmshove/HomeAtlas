# Discovery und Scan

> Status: Ist-Verhalten, aus dem Code zurückgewonnen (Stand 0159807). Quellen als `datei:zeile`.

## Zweck

Ein Admin will wissen, was in seinem Heimnetz hängt, ohne jedes Gerät von Hand einzutragen. Ein
Netzwerk-Scan sucht alle Geräte in den gewählten Netzen, sammelt aus mehreren unabhängigen Quellen
Belege (Erreichbarkeit, offene Dienste, Namen, Hersteller, Selbstauskunft), führt sie ins Inventar
zusammen und stößt danach Einordnung, Zugangs-Abfragen und die Neuerzeugung der Dokumentation an.
Optional läuft der Scan automatisch in einem festen Mindestabstand.

## Rollen und Rechte

| Aktion | ADMIN | MEMBER |
|---|---|---|
| Scan manuell starten | ja | nein (403) |
| Scan-Liste und laufenden Scan lesen | ja | ja (nur API; UI-Seite ist admin-only) |
| Einzelnen Scan inkl. Protokoll lesen | ja | ja (nur API) |
| Herstellerdatenbank (OUI) aktualisieren | ja | nein |
| Scan-Einstellungen ändern | ja, siehe [einstellungen-und-llm-provider](../einstellungen-und-llm-provider/spec.md) | nein |

## Anforderungen

### Requirement: Scan als Hintergrundauftrag mit Fortschritt
Das System MUSS einen Scan asynchron ausführen, sofort eine Scan-ID zurückgeben und Phase,
Fortschritt (0–100 %) und ein zeitgestempeltes Protokoll am Scan-Datensatz fortschreiben. **[Muss]**

#### Szenario: Start liefert ID, Fortschritt ist abfragbar
- **WENN** ein Admin `POST /api/scans` aufruft und kein Scan läuft
- **DANN** antwortet das System mit `{"scanId": …}`, legt einen Scan mit Status `running` an und
  schreibt einen Zugriffsprotokoll-Eintrag `scan.start`
- **UND** `GET /api/scans/{id}` liefert `phase`, `progress`, `log` bis Status `completed` oder `failed`

Quelle: `backend/app/main.py:1431`, `backend/app/pipeline.py:347`, `backend/app/db.py:1794`

### Requirement: Höchstens ein Scan gleichzeitig
Das System MUSS einen zweiten Scan ablehnen, solange einer läuft (manuell: HTTP 409 „Es läuft
bereits ein Scan."; Zeitplan: still überspringen). **[Muss]**

#### Szenario: Doppelstart
- **WENN** ein Scan `running` ist und erneut `POST /api/scans` kommt
- **DANN** HTTP 409, kein neuer Scan

Quelle: `backend/app/main.py:1433`, `backend/app/pipeline.py:602`

### Requirement: Abgebrochene Scans nach Neustart bereinigen
Das System MUSS beim Start alle noch `running` markierten Scans auf `failed` mit Phase
„abgebrochen (Neustart)“ setzen, damit kein verwaister Scan neue Scans blockiert. **[Muss]**

#### Szenario: Container-Neustart mitten im Scan
- **WENN** das Backend neu startet, während ein Scan-Datensatz `running` ist
- **DANN** ist er danach `failed` mit `finishedAt` gesetzt

Quelle: `backend/app/db.py:1832`, `backend/app/main.py:46`

### Requirement: Scan-Historie
Das System MUSS die letzten 20 Scans (neueste zuerst) mit `id, startedAt, finishedAt, status,
subnets, summary` sowie den gerade laufenden Scan vollständig liefern. **[Muss]** Die Liste enthält
weder `log` noch `phase`/`progress`. **[Impl]**

#### Szenario: Liste
- **WENN** `GET /api/scans`
- **DANN** `{"scans": [≤20 Einträge], "running": <voller Datensatz oder null>}`

Quelle: `backend/app/db.py:1822`, `backend/app/main.py:1446`

### Requirement: Scan-Bereiche ermitteln
Das System MUSS die zu scannenden IPv4-Netze so bestimmen: zuerst angehakte, aktive und
aktivierte Controller-Netze (`scanControllerNetworkIds`, Quelle „controller“, mit Name/VLAN), dann
Freitext-Einträge (`scanSubnets`, Quelle „freitext“). Einträge werden normalisiert
(`10.0.0.5/24` → `10.0.0.0/24`) und dedupliziert (Controller-Eintrag gewinnt). Ist nichts
gewählt, MUSS das System die direkt angeschlossenen Netze des Hosts nehmen, ersatzweise das /24 der
primären Host-IP. **[Muss]** Ungültiger Freitext wird unverändert durchgereicht, damit der Scan
warnen kann. **[Impl]**

#### Szenario: Controller + Freitext ohne Duplikate
- **WENN** Controller-Netze a=`192.168.20.0/24`, b=`10.0.0.0/24` angehakt und Freitext
  `10.0.0.5/24`, `192.168.99.0/24`
- **DANN** Bereiche `192.168.20.0/24`, `10.0.0.0/24`, `192.168.99.0/24`

#### Szenario: Veraltete/inaktive Auswahl
- **WENN** nur inaktive, deaktivierte, CIDR-lose, IPv6- oder unbekannte IDs angehakt sind
- **DANN** Rückfall auf die Host-Netze

Quelle: `backend/app/discovery.py:154`, `backend/app/discovery.py:190`, `backend/app/discovery.py:93`,
Tests: `backend/tests/test_discovery_subnets.py::test_merges_checked_controller_networks_and_free_text_without_duplicates`,
`::test_ignores_selected_networks_that_are_inactive_disabled_or_without_cidr`,
`::test_falls_back_to_local_subnets_when_nothing_selected`, `::test_selected_subnets_duplicate_keeps_controller_position`,
`::test_selected_subnets_reports_source_name_and_vlan`

### Requirement: Host-Netze ohne virtuelle Interfaces
Bei der automatischen Ermittlung MUSS das System Loopback, Link-Local sowie Interfaces nach dem
Muster `lo, docker*, br-<hex≥8>, veth*, virbr*, tailscale*, wg*, zt*` ignorieren. **[Muss]**

#### Szenario: Docker-Bridges
- **WENN** der Host `docker0` und `br-0123abcd…` hat
- **DANN** erscheinen deren Netze nicht als Scan-Bereich

Quelle: `backend/app/discovery.py:40`, Test: `backend/tests/test_discovery_mdns.py::test_local_subnets_still_filters`

### Requirement: Kein Bereich ermittelbar
Das System MUSS einen Scan mit der Meldung „Es konnte kein Netzwerk-Bereich ermittelt werden …“
fehlschlagen lassen, wenn keinerlei Bereich bestimmbar ist. **[Muss]**

#### Szenario: Keine Interfaces, keine Einstellung
- **WENN** weder Auswahl noch Host-Netz existieren
- **DANN** Scan-Status `failed`, `summary.error` enthält die Meldung

Quelle: `backend/app/discovery.py:746`, `backend/app/pipeline.py:554`

### Requirement: Adressraum begrenzen und Ausnahmen
Das System MUSS pro Netz höchstens die ersten 1024 Host-Adressen prüfen (Warnung bei Kürzung),
ungültige Bereiche mit Warnung überspringen und Adressen aus `scanExcludeIps` nie prüfen. **[Muss]**

#### Szenario: /16 konfiguriert
- **WENN** `10.0.0.0/16` gescannt wird
- **DANN** Warnung „… umfasst 65534 Adressen -- es wurden nur die ersten 1024 geprüft.“

Quelle: `backend/app/discovery.py:44`, `backend/app/discovery.py:757`, `backend/app/discovery.py:766`

### Requirement: Einzelziele außerhalb der Bereiche
Das System MUSS zusätzlich `scanExtraTargets` (IP oder Hostname) sowie IPs aller Inventar-Geräte,
die in keinem Scan-Bereich liegen, vollständig prüfen (Ping, Ports, DNS, Banner). Hostnamen werden
aufgelöst; nicht auflösbare erzeugen eine Warnung. Ausgeschlossene IPs und Duplikate entfallen. **[Muss]**

#### Szenario: Router in anderem Segment
- **WENN** Inventar ein Gerät `10.1.1.1` enthält und nur `192.168.1.0/24` gescannt wird
- **DANN** wird `10.1.1.1` mitgeprüft und in `summary.routedTargets` sowie `extra.routedTarget=true` geführt

Quelle: `backend/app/pipeline.py:25`, `backend/app/discovery.py:771`

### Requirement: Lebend-Erkennung
Das System MUSS jede Adresse zuerst auf Lebenszeichen prüfen: TCP-Connect auf
`80, 443, 22, 445, 53, 8080, 139, 3389, 631, 9100, 8123, 5000` (in dieser Reihenfolge, Abbruch beim
ersten offenen Port, Timeout je Port min(`scanTimeoutMs`, 400 ms)); nur ohne TCP-Antwort ein
einzelner ICMP-Ping (Wartezeit max(1, ganzzahlige Sekunden des Timeouts)). Danach MUSS jede Adresse
mit gültiger MAC in der ARP-/Neighbour-Tabelle (ohne FAILED/INCOMPLETE) als lebend gelten, sofern
sie im geprüften Adressraum liegt und nicht ausgeschlossen ist. **[Muss]**

#### Szenario: ARP-Treffer zählt als Antwort
- **WENN** keine Adresse auf Ping/TCP antwortet, die ARP-Tabelle aber `10.3.0.4` mit MAC enthält
- **DANN** wird `10.3.0.4` gefunden und es gibt keine „keine Adresse hat geantwortet“-Warnung

Quelle: `backend/app/discovery.py:287`, `backend/app/discovery.py:304`, `backend/app/discovery.py:223`,
`backend/app/discovery.py:800`, Test: `backend/tests/test_discovery_subnets.py::test_arp_hit_counts_as_responding`

### Requirement: Nebenläufigkeit und Timeout
Das System MUSS die parallelen Prüfungen auf `scanConcurrency` (Default 128, geklemmt 8–512)
begrenzen und `scanTimeoutMs` (Default 700, mindestens 100 ms) als Timeout für Portscan und Ping
verwenden. **[Muss]**

#### Szenario: Ausreißer
- **WENN** `scanConcurrency=5000`
- **DANN** werden höchstens 512 Verbindungen gleichzeitig geöffnet

Quelle: `backend/app/discovery.py:738`

### Requirement: Warnungen für geroutete und stumme Netze
Das System MUSS je Scan-Netz, das mit keinem direkt angeschlossenen Host-Netz überlappt, genau eine
Warnung „<cidr> ist nur geroutet erreichbar: keine MAC/Hersteller, kein mDNS/SSDP. … Siehe
docs/multi-vlan.md“ ausgeben (Zusatz „Keine Adresse hat geantwortet.“ falls stumm). Für nicht
geroutete Netze ohne jede Antwort MUSS die Warnung „<cidr>: keine Adresse hat geantwortet …“ kommen.
Ist die Host-Interface-Ermittlung leer, entfällt die Routing-Warnung. **[Muss]**

#### Szenario: Zwei geroutete Netze
- **WENN** lokal `192.168.1.0/24`, gescannt `192.168.1.0/30`, `10.99.0.0/29`, `10.98.0.0/29`
- **DANN** genau zwei „nur geroutet“-Warnungen, `10.98.0.0/29` genau einmal erwähnt, keine Warnung zu `192.168.1.0/30`

Quelle: `backend/app/discovery.py:115`, `backend/app/discovery.py:806`,
Tests: `backend/tests/test_discovery_subnets.py::test_discover_warns_once_per_routed_subnet`,
`::test_routed_subnet_warnings_one_per_routed_subnet`, `::test_routed_subnet_warnings_local_none_duplicates_once_and_unknown_local_none`,
`::test_warns_for_subnet_without_any_responding_host`

### Requirement: Dienste-Portscan
Das System MUSS bei jedem lebenden Gerät alle Ports des Port-Katalogs (55 TCP-Ports, siehe
`ports.SERVICES`) per TCP-Connect prüfen und jeden offenen Port mit Kurzname und laienverständlicher
Erklärung speichern (`services: [{port, service, explanation}]`, nach Port sortiert). Unbekannte
Ports heißen „Port N / Unbekannter Dienst“. **[Muss]** Die genaue Portliste ist **[Impl]**, sollte
aber übernommen werden.

#### Szenario: Drucker
- **WENN** 9100 offen ist
- **DANN** enthält `services` `{"port": 9100, "service": "JetDirect", "explanation": "Direktdruck -- fast immer ein Netzwerkdrucker"}`

Quelle: `backend/app/ports.py:12`, `backend/app/ports.py:75`, `backend/app/ports.py:103`, `backend/app/discovery.py:830`

### Requirement: Reverse-DNS
Das System MUSS für jedes lebende Gerät den PTR-Namen abfragen (Timeout 3 s, Fehler = leer). **[Muss]**

#### Szenario: DHCP-Name
- **WENN** der Router `nas.fritz.box` für die IP meldet
- **DANN** `hostname = "nas.fritz.box"`, Namensbeitrag `nas`

Quelle: `backend/app/discovery.py:331`

### Requirement: HTTP-Banner
Wenn `scanEnableHttpBanner` (Default an) gesetzt ist, MUSS das System die erste antwortende
Weboberfläche lesen, Ports in der Reihenfolge `443, 8443, 5001, 8006, 80, 8080, 8123, 5000, 3000,
9000, 8096, 81, 8081, 10000` (nur offene), HTTPS für 443/8443/5001/8006, Zertifikate ungeprüft,
Redirects folgen, Timeout 6 s (Connect 3 s). Gespeichert werden `url`, `<title>` (aus den ersten
20 000 Zeichen, Leerraum zusammengefasst, max. 120 Zeichen), `Server`-Header (max. 120) und Status;
erster Port mit Titel oder Server-Header gewinnt. **[Muss]**

#### Szenario: Abgeschaltet
- **WENN** `scanEnableHttpBanner=false`
- **DANN** wird keine HTTP-Anfrage gestellt, `httpBanner = {}`

Quelle: `backend/app/discovery.py:341`, `backend/app/discovery.py:344`, `backend/app/discovery.py:835`

### Requirement: mDNS
Wenn `scanEnableMdns` (Default an) gesetzt ist, MUSS das System parallel zur Lebend-Erkennung
mDNS-Dienstarten 5 s lang suchen, sie 5 s browsen und je Dienst Name, Typ, Server, Port und
TXT-Properties pro IP sammeln (Auflösung je Dienst max. 1,5 s). Multicast-Mitgliedschaft MUSS auf
die lokalen IPs in den Scan-Bereichen beschränkt werden; passt keine, alle Interfaces plus Warnung.
Jeder Netzwerkfehler MUSS zu einer Warnung statt zum Scanabbruch führen; bei ENOBUFS mit Diagnose
(Anzahl Host-Interfaces, `net.ipv4.igmp_max_memberships`, Abhilfe). **[Muss]**

#### Szenario: ENOBUFS
- **WENN** der mDNS-Start mit `OSError(ENOBUFS)` scheitert
- **DANN** leeres Ergebnis und Warnung mit Interface-Anzahl und IGMP-Limit; Scan läuft weiter

#### Szenario: Interfaces begrenzt
- **WENN** der Host eine IP in einem Scan-Bereich hat
- **DANN** wird mDNS nur auf dieser IP gestartet

Quelle: `backend/app/discovery.py:450`, `backend/app/discovery.py:435`, `backend/app/discovery.py:793`,
Tests: `backend/tests/test_discovery_mdns.py::test_mdns_oserror_on_create_returns_empty_with_warning`,
`::test_mdns_warning_contains_diagnosis`, `::test_mdns_warning_tolerates_missing_or_garbled_igmp_limit`,
`::test_mdns_warning_other_errno_is_not_called_enobufs`, `::test_mdns_limits_interfaces_to_scanned_subnets`,
`::test_mdns_falls_back_to_default_with_warning_when_no_interface_matches`

### Requirement: SSDP/UPnP
Wenn `scanEnableSsdp` (Default an) gesetzt ist, MUSS das System parallel zur Lebend-Erkennung drei
`M-SEARCH`-Anfragen (`ST: ssdp:all`, `MX: 3`, TTL 2, 200 ms Abstand) an `239.255.255.250:1900`
senden, 5 s Antworten sammeln (dedupliziert je IP nach LOCATION+ST) und jede eindeutige
Beschreibungs-XML einmal laden (Timeout 6 s/3 s), daraus `friendlyName, manufacturer, modelName,
modelNumber, modelDescription, serialNumber` (je max. 200 Zeichen). **[Muss]**

#### Szenario: Fehler in einer Quelle
- **WENN** SSDP mit `OSError` scheitert, mDNS aber funktioniert
- **DANN** Warnung „UPnP/SSDP-Erkennung übersprungen …“, Funde bleiben erhalten

Quelle: `backend/app/discovery.py:535`, `backend/app/discovery.py:552`, `backend/app/discovery.py:613`,
Tests: `backend/tests/test_discovery_mdns.py::test_discover_survives_mdns_and_ssdp_errors`,
`::test_discover_only_one_source_fails`, `::test_discover_sources_disabled`

### Requirement: Nur-Multicast-Geräte
Ein Gerät, das sich nur per mDNS/SSDP meldet, MUSS als lebend aufgenommen werden, wenn seine IP in
einem Scan-Bereich liegt und nicht ausgeschlossen ist. **[Muss]**

#### Szenario: Stummer Lautsprecher
- **WENN** eine IP nur per mDNS antwortet
- **DANN** erscheint sie als Fund ohne offene Ports

Quelle: `backend/app/discovery.py:857`

### Requirement: Shelly-Identität
Für Geräte, deren Hersteller, Banner oder mDNS-Text „shelly“ enthält, MUSS das System die
unauthentifizierte lokale API `/shelly` abfragen (Timeout 4 s/2 s; nur 200 + Objekt mit
`type|model|app`), bei Gen ≥ 2 zusätzlich `/rpc/Shelly.GetDeviceInfo`, sonst `/settings`. Ein vom
Besitzer vergebener Name ersetzt den Namen; sonst „Shelly <Modell>“. Das exakte Modell ersetzt ein
leeres oder bloßes „Shelly“-Modell. **[Muss]**

#### Szenario: Mehrere Shellys mit gleichem Titel
- **WENN** zwei Geräte „Shelly Web Admin“ als Titel liefern, eines heißt in der App „Küche“
- **DANN** heißt es „Küche“, das andere „Shelly <Modell>“

Quelle: `backend/app/discovery.py:372`, `backend/app/discovery.py:868`, `backend/app/discovery.py:917`

### Requirement: Namenspräzedenz
Das System MUSS den Gerätenamen nach fester Rangfolge bilden: manuell gepflegt (bestätigtes Gerät)
> UniFi-Name (nicht leerer `name` aus `extra.unifi`, aus dem Fund oder bereits gespeichert)
> Shelly-App-Name > „Shelly <Modell>“ (beides nur bei Antwort der Shelly-API) > UPnP `friendlyName`
> mDNS-Instanzname > DNS-Hostname (erstes Label) > Webseitentitel > „<erstes Wort des Herstellers>
(<letztes IP-Oktett>)“ > IP. Namen werden auf 80 Zeichen gekürzt. Die Stufen ab Shelly bildet der
Netzwerkscan je Fund; UniFi und „manuell“ greifen erst beim Zusammenführen ins Inventar (siehe
„Wiedererkennung bestehender Geräte“). Namen anderer Quellen (Docker, Omada, Proxmox, AdGuard,
KI-Einordnung) stehen nicht in dieser Kette: Bei unbestätigten Geräten überschreibt jeder nicht
leere Name des später zusammengeführten Funds den bisherigen (Reihenfolge im Scan: Netzwerkscan,
Docker, UniFi, Omada, Proxmox, AdGuard), außer ein UniFi-Name ist bekannt. **[Muss]**

#### Szenario: Bestätigtes Gerät
- **WENN** ein Gerät bestätigt wurde und der Scan einen anderen Namen findet
- **DANN** bleibt der manuelle Name

#### Szenario: Nur Hersteller bekannt
- **WENN** nur MAC-Hersteller „Raspberry Pi Trading“ bei `192.168.1.42` bekannt ist
- **DANN** Name „Raspberry (42)“

Quelle: `backend/app/discovery.py:633`, `backend/app/discovery.py:917`, `backend/app/pipeline.py:376`–`:470`,
`backend/app/db.py:1202`, `backend/app/db.py:1224`, `backend/app/db.py:1231`,
Tests: `backend/tests/test_db_docker_names.py::test_confirmed_row_keeps_name`,
`backend/tests/test_db_dedup.py::test_upsert_keeps_unifi_name_over_other_discovery_sources`

### Requirement: Regelbasierte Geräteart
Das System MUSS ohne LLM eine Ersteinordnung (Art, Modell, Zweck, „sicher“-Flag) liefern:
1. Produktsignaturen (Substring, kleingeschrieben, über Titel, Server-Header, Hersteller, mDNS-Typ/
   Name, SSDP-Server/Beschreibung) in fester Reihenfolge, spezifischste zuerst (FRITZ!Box, Repeater,
   Home Assistant, Synology, QNAP, Proxmox, UniFi, Drucker-mDNS, Cast, AirPlay, Sonos, HomeKit,
   ESPHome, Shelly, Tasmota, Hue, Kameras, OpenWrt, Plex, Jellyfin/Emby, Pi-hole, Nextcloud,
   Workstation/Windows, SMB, Heizung, PV-Wechselrichter, Wallbox, Klima) → sicher;
2. sonst Port-Hinweise in Katalogreihenfolge (`515, 631, 9100` Drucker, `554` Kamera, `1400` Sonos,
   `8008/8009` Chromecast, `32400` Plex, `8096` Jellyfin, `8123` Home Assistant, `8006` Proxmox,
   `5001` Synology, `2049` NAS, `502` Modbus/climate, `11434` Ollama, `1883` MQTT) → sicher;
3. sonst Platzhalter (nicht sicher): `server` bei 22/3306/5432/2049, `other` bei sonstigen Ports,
   `other` ohne Ports.
UPnP `manufacturer + modelName` hat als Modell Vorrang. **[Muss]** Die konkreten Signaturen sind
**[Impl]**.

#### Szenario: Drucker mit Weboberfläche
- **WENN** Ports 80 und 9100 offen, keine Signatur passt
- **DANN** Art `printer`, Zweck „Netzwerkdrucker“, sicher

Quelle: `backend/app/discovery.py:653`, `backend/app/discovery.py:675`, `backend/app/ports.py:79`, `backend/app/ports.py:111`

### Requirement: Gateway-Sonderbehandlung
Das Gerät mit der IP des Default-Gateways MUSS Art `router`, Wichtigkeit `critical`, sicher und
`extra.isGateway=true` erhalten; ein Zweck ohne „Router“ wird durch „Internet-Router -- die
Verbindung ins Internet läuft über dieses Gerät“ ersetzt. **[Muss]**

#### Szenario: Gateway
- **WENN** `ip route` `default via 192.168.1.1` meldet
- **DANN** ist `192.168.1.1` ein kritischer Router

Quelle: `backend/app/discovery.py:896`, `backend/app/discovery.py:941`

### Requirement: Fund-Datensatz und Wiedererkennung
Jeder Fund MUSS mit Schlüssel `mac:<mac>` (sonst `ip:<ip>`) gespeichert werden und enthält Name,
Hostname, IP, MAC, Hersteller, Modell, Zweck, URL der Weboberfläche, kuratierten Doku-Link, Status
`online`, Quellen (`ping/arp[+portscan][+mdns][+ssdp][+http]`), offene Ports, Dienste und Belege
(`extra.mdns, ssdp, httpBanner, randomizedMac, isGateway, routedTarget, guessConfident, nameSource`; `nameSource` = Herkunft des Namens: upnp/mdns/hostname/title/vendor/ip/shelly). **[Muss]**

#### Szenario: Zufalls-MAC
- **WENN** die MAC lokal administriert ist (Bit 1 im ersten Oktett)
- **DANN** `extra.randomizedMac = true`

Quelle: `backend/app/discovery.py:929`, `backend/app/oui.py:86`

### Requirement: Wiedererkennung bestehender Geräte
Beim Übernehmen eines Funds ins Inventar MUSS das System ein bestehendes Gerät in dieser
Reihenfolge suchen und das erste Ergebnis aktualisieren statt neu anzulegen: (1) gleicher
`discoveryKey`, (2) einer der `legacyDiscoveryKeys` des Funds, (3) Alias aus einer manuellen
Zusammenführung (Schlüssel, Alt-Schlüssel oder `mac:<mac>` des Funds), (4) gleiche MAC,
(5) Proxmox-Gast mit gleichem (node, vmid), (6) gleiche IP *und* gleicher Hostname, (7) genau ein
Gerät mit dieser IP, sofern Fund oder Gerät aus UniFi/Omada stammt und die MACs sich nicht
widersprechen. Ohne Treffer entsteht ein neues Gerät. Für das gefundene Gerät gilt: **[Muss]**
- immer aktualisiert: IP, Status, `extra` (zusammengeführt), `lastSeen`, `discoveryKey` (auf den
  Schlüssel des Funds);
- offene Ports/Dienste nur, wenn der Fund `openPorts` mitbringt – fehlen sie (UniFi, Omada,
  Proxmox), bleiben die gespeicherten erhalten;
- bringt der Fund keine MAC mit und hat das Gerät einen `mac:`-Schlüssel samt MAC, bleibt dieser
  Schlüssel (kein Hin- und Herspringen zwischen Scan und Controller);
- Alias-Treffer (3): Schlüssel, IP und MAC des Geräts bleiben unverändert; Ports landen im
  Eintrag dieser Adresse unter `extra.interfaces`;
- unbestätigtes Gerät: jedes nicht leere Feld aus `kind, name, hostname, mac, vendor, model, os,
  location, purpose, descriptionMd, url, docUrl, docLink, importance` wird übernommen; ist ein
  UniFi-Name bekannt (Fund oder gespeichertes `extra.unifi`), gewinnt er als `name`;
- bestätigtes Gerät: nur bisher leere Felder aus `hostname, mac, vendor, model, os, docUrl,
  docLink, purpose, location` werden gefüllt; `name`, `kind`, `descriptionMd`, `url`,
  `importance` bleiben unberührt.

#### Szenario: Scan sieht Gerät nur per IP, Controller per MAC
- **WENN** ein gerouteter Fund `ip:10.0.0.5` ohne MAC existiert und UniFi dasselbe Gerät mit
  MAC `aa:bb:cc:00:00:01` und IP `10.0.0.5` meldet
- **DANN** wird kein zweites Gerät angelegt; das Gerät erhält die MAC und den Schlüssel
  `mac:aa:bb:cc:00:00:01`, und der nächste Netzwerkscan (wieder ohne MAC) lässt diesen Schlüssel stehen

#### Szenario: UniFi-Name gegen Selbstauskunft
- **WENN** ein unbestätigtes Gerät den UniFi-Namen „Wohnzimmer-AP“ trägt und ein späterer Fund
  per UPnP „UAP-AC-Lite“ meldet
- **DANN** bleibt der Name „Wohnzimmer-AP“; bei einem bestätigten Gerät bliebe der manuelle Name

#### Szenario: Controller-Fund ohne Ports
- **WENN** der Netzwerkscan Ports 22 und 443 gefunden hat und danach ein Proxmox-Fund ohne
  `openPorts` dasselbe Gerät trifft
- **DANN** bleiben Ports 22 und 443 gespeichert

#### Szenario: Bestätigtes Gerät wird ergänzt
- **WENN** ein von Hand angelegtes, bestätigtes Gerät nur Name, IP und Hostname hat und ein Fund
  mit gleicher IP und gleichem Hostname MAC, Hersteller und Zweck liefert
- **DANN** werden MAC, Hersteller und Zweck gefüllt, Name und Art bleiben

Quelle: `backend/app/db.py:1133`, `backend/app/db.py:1168`–`:1184`, `backend/app/db.py:1087`–`:1105`,
`backend/app/db.py:1063`, `backend/app/db.py:1196`–`:1240`, `backend/app/db.py:772`,
Tests: `backend/tests/test_db_dedup.py::test_find_system_for_merge_prefers_mac_over_proxmox_over_ip_hostname`,
`::test_merge_controller_found_into_existing_ip_only_scan_row`, `::test_upsert_updates_unifi_name_but_preserves_confirmed_homeatlas_name`,
`::test_upsert_merges_device_found_by_ip_only_then_by_mac_via_ip_hostname_match`,
`backend/tests/test_db_merge_aliases.py::test_rescan_with_only_alias_mac_does_not_duplicate`,
`::test_finding_without_ports_does_not_wipe_scanned_ports`

### Requirement: Herstellererkennung über OUI
Das System MUSS den Hersteller aus den ersten drei MAC-Oktetten ermitteln. Quelle ist das
IEEE-Register (`https://standards-oui.ieee.org/oui/oui.csv`), lokal zwischengespeichert; ohne
Download nur eine kleine Fallback-Liste (AVM, Apple, Raspberry Pi, VMware, Hyper-V, VirtualBox,
QEMU/KVM, Docker). Präfix `02:42:` ergibt immer „Docker-Container“. Ist das Register nicht geladen,
MUSS der Scan es zuerst laden; Misserfolg ist nur eine Warnung. **[Muss]**

#### Szenario: Erster Scan ohne Internet
- **WENN** das Register fehlt und der Download scheitert
- **DANN** Warnung „Hersteller-Datenbank nicht geladen: …“, Scan läuft mit Fallback-Liste weiter

Quelle: `backend/app/oui.py:77`, `backend/app/oui.py:29`, `backend/app/pipeline.py:356`

### Requirement: OUI manuell aktualisieren
Ein Admin MUSS das Register neu laden können. Download mit Timeout 120 s (Connect 15 s), User-Agent
`HomeAtlas/1.0 (+https://github.com/TorstenAmshove/HomeAtlas)`; Antworten mit < 1000 erkannten
Einträgen oder HTTP ≥ 400 MÜSSEN verworfen werden (alter Cache bleibt). Antwort
`{ok, message, entries}`. **[Muss]** CSV-Spalten werden nicht positionsfest gelesen (erste
6-Hex-Zelle = Präfix, nächste nicht leere = Name). **[Impl]**

#### Szenario: Erfolgreicher Refresh
- **WENN** IEEE 1000 gültige Zeilen liefert
- **DANN** `ok=true`, `lookup("00:00:00:11:22:33") == "Vendor 0"`

Quelle: `backend/app/main.py:498`, `backend/app/oui.py:98`, `backend/app/oui.py:128`,
Test: `backend/tests/test_oui.py::test_refresh_identifies_homeatlas_to_ieee`

### Requirement: Docker-Container als Funde
Wenn `scanEnableDocker` (Default an) gesetzt ist, MUSS der Scan die Container des lokalen Docker-Hosts
als Funde aufnehmen (Details: Docker-Probe). Name: `<service> · <projekt>` bei Compose-Labels, sonst
Container-Name; stabiler Schlüssel `docker:<projekt>:<service>` bzw. `docker:<name>`, mit
Rückfall auf alten Schlüssel `docker:<id12>`. Fehlt der Docker-Socket, nur Protokollzeile; ist er da,
aber die API scheitert, Warnung. **[Muss]**

#### Szenario: Unbestätigter Container bekommt neuen Namen
- **WENN** ein unbestätigter Container-Eintrag existiert und der Scan `postgres · immich` liefert
- **DANN** heißt er `postgres · immich`; ein bestätigter behält seinen Namen

Quelle: `backend/app/docker_probe.py:87`, `backend/app/docker_probe.py:102`, `backend/app/pipeline.py:376`,
Tests: `backend/tests/test_db_docker_names.py::test_unconfirmed_row_gets_new_name`, `::test_confirmed_row_keeps_name`

### Requirement: Eindeutige Namen
Nach allen Quellen und der KI-Einordnung MUSS das System Namen, die im selben Scan mehrfach vorkommen,
eindeutig machen: Nicht-Container mit IP erhalten „Name (<letztes Oktett>)“, bei gleichem Oktett
zusätzlich „-n“ ab dem zweiten; Container erhalten ab dem zweiten Duplikat „ (n)“. Einmalige Namen
bleiben unverändert. **[Muss]**

#### Szenario: Zwei Shellys
- **WENN** „Shelly“ bei `.5` und `.6`
- **DANN** „Shelly (5)“ und „Shelly (6)“

#### Szenario: Skalierte Container
- **WENN** zweimal `web · app`
- **DANN** `web · app` und `web · app (2)`

Quelle: `backend/app/pipeline.py:307`, Tests: `backend/tests/test_pipeline_unique_names.py::test_non_containers_get_octet_suffix`,
`::test_identical_container_names_get_counter_not_octet`, `::test_distinct_container_names_untouched`,
`::test_container_without_ip_does_not_crash`

### Requirement: Scan-Ablauf und Fehlertoleranz
Das System MUSS die Phasen in dieser Reihenfolge ausführen: OUI laden (falls fehlend) → Netzwerk-
Discovery → Docker → Controller-Quellen (UniFi, Omada, Proxmox, AdGuard; je abschaltbar) →
KI-Einordnung (`scanUseLlm`, nur neue Funde) → eindeutige Namen → Inventar zusammenführen → nicht gesehene
entdeckte Geräte `offline` → Container dem Host zuordnen → Uplinks verknüpfen → Netze
synchronisieren → kritische Geräte überwachen → Abfrage mit Zugangsdaten (`scanUseCredentials`) →
Dokumentation neu schreiben. Nur ein Fehler in der Netzwerk-Discovery selbst (oder ein unerwarteter
Fehler) darf den Scan scheitern lassen; alle anderen Phasen degradieren zu Warnungen. **[Muss]**

#### Szenario: Doku-Erzeugung scheitert
- **WENN** die Dokumentation eine Ausnahme wirft
- **DANN** Scan `completed`, Inventar gespeichert, Warnung „Dokumentation konnte nicht vollständig erzeugt werden: …“

#### Szenario: Discovery-Warnungen im Protokoll
- **WENN** Discovery eine Warnung liefert
- **DANN** steht sie im Scan-Protokoll

Quelle: `backend/app/pipeline.py:341`, `backend/app/pipeline.py:533`, `backend/app/pipeline.py:554`,
Test: `backend/tests/test_pipeline_probe_warnings.py::test_pipeline_logs_discovery_warnings`

### Requirement: Offline-Markierung
Jedes zuvor entdeckte Gerät (`discovered=1`), das in keinem Fund dieses Scans auftaucht, MUSS auf
`offline` gesetzt werden; manuell angelegte Geräte bleiben unberührt. **[Muss]**

#### Szenario: Gerät ausgeschaltet
- **WENN** ein entdecktes Gerät beim nächsten Scan fehlt
- **DANN** Status `offline`

Quelle: `backend/app/db.py:1243`, `backend/app/pipeline.py:487`

### Requirement: Probe-Warnungen pro Zugang
Scheitert bei der Zugangs-Abfrage ein einzelner Zugang eines Geräts, MUSS das als Scan-Warnung
„<Gerät> (<Zugang>): <Fehler>“ und als Fehlerereignis am Gerät festgehalten werden, auch wenn ein
anderer Zugang desselben Geräts erfolgreich war. Details:
[credentialed-probing](../credentialed-probing/spec.md). **[Muss]**

#### Szenario: SSH ok, Home-Assistant-Token abgelehnt
- **WENN** ein Gerät beide Zugänge hat und nur HA scheitert
- **DANN** `probed=1`, Warnung mit „Zugriffstoken abgelehnt“, genau ein Fehlerereignis am Gerät

Quelle: `backend/app/pipeline.py:103`, Test: `backend/tests/test_pipeline_probe_warnings.py::test_probe_with_credentials_logs_failure_even_when_another_credential_on_same_system_succeeds`

### Requirement: Kritische Geräte überwachen
Nach dem Zusammenführen MUSS jedes Gerät mit Wichtigkeit `critical` und IP für die Dauerüberwachung
markiert werden (siehe [monitoring](../monitoring/spec.md)). **[Muss]**

#### Szenario: Gateway neu gefunden
- **WENN** das Gateway erstmals gefunden wird
- **DANN** `monitored=1`, Protokollzeile „1 wichtige Geräte zur Dauerüberwachung hinzugefügt“

Quelle: `backend/app/pipeline.py:512`

### Requirement: Scan-Ergebnis
Ein erfolgreicher Scan MUSS `summary = {devicesFound, created, updated, probed, routedTargets,
subnets, gateway, dnsServers, counts{addressesScanned, devicesFound, withMdns, withSsdp,
routedFound}, warnings}` speichern; ein gescheiterter `{error, warnings}` plus Protokollzeile
„FEHLER: …“. **[Muss]**

#### Szenario: Gescheitert
- **WENN** eine unerwartete Ausnahme auftritt
- **DANN** Status `failed`, `progress=100`, `summary.error` gesetzt

Quelle: `backend/app/pipeline.py:540`, `backend/app/pipeline.py:554`, `backend/app/db.py:1804`

### Requirement: Scan-Seite
`/scan` MUSS zuerst zusammenfassen: laufend Phase und Fortschritt
(abgefragt alle 1,5 s nur, solange der Scan läuft und der Browser-Tab sichtbar ist), sonst Ergebnis des
letzten Scans mit einer Zeile „Was ist neu?“ ausschließlich aus `summary.created`, `summary.updated`,
`summary.devicesFound` (und `gateway`), ohne neu berechnete Zahlen; danach Hinweise, Protokoll und die
früheren Scans (ohne den oben gezeigten). **[Muss]** (Texte **[Impl]**)

#### Szenario: Abgeschlossener Scan
- **WENN** der letzte Scan `created=2, updated=12, devicesFound=14` meldet
- **DANN** zeigt die Seite „Was ist neu? 2 neue Geräte · 12 aktualisiert · 14 gefunden“

Quelle: `frontend/src/pages/mehr/ScanPage.tsx`

### Requirement: Automatischer Scan (Zeitplan)
Ist `scanAutoEnabled` (Default aus) gesetzt, MUSS das System einen Scan starten, sobald der letzte
Scan (manuell oder automatisch, egal mit welchem Ausgang) länger als `scanAutoIntervalHours`
(Default 24, geklemmt 1–720) zurückliegt oder noch keiner existiert, und nie, solange ein Scan läuft.
Einstellungsänderungen MÜSSEN ohne Neustart wirken. **[Muss]** Geprüft wird beim Start und dann alle
300 s; Fehler im Zeitplan beenden die Schleife nicht. **[Impl]**

#### Szenario: Manueller Scan verschiebt den Zeitplan
- **WENN** Intervall 24 h und vor 3 h manuell gescannt wurde
- **DANN** startet kein automatischer Scan

Quelle: `backend/app/pipeline.py:568`, `backend/app/pipeline.py:598`, `backend/app/pipeline.py:604`, `backend/app/main.py:58`

## Daten

Siehe [data-model](../../contracts/data-model.md).

- **scans**: schreibt `id, startedAt, finishedAt, status (running|completed|failed), subnets
  (Bereichsliste als Text bzw. „automatisch (Zeitplan)“), progress, phase, summary (JSON), log`.
- **systems**: liest alle (Einzelziele, Bekanntes); schreibt über das Zusammenführen `kind, name,
  hostname, ip, mac, vendor, model, purpose, url, docUrl, importance, status, discoveryKey,
  discovered, discoverySource, openPorts, services, extra.*, lastSeen, parentId (Container),
  monitored`. Regeln zum Zusammenführen/Bestätigt-Schutz: [inventar](../inventar/spec.md).
- **networkResources** (kind network): liest für die Bereichsauswahl.
- **accessLog**: `scan.start`.
- Datei: OUI-Cache (`HOMEATLAS_OUI_PATH`, Default `/data/oui.json`).
- Settings gelesen: `scanSubnets, scanControllerNetworkIds, scanExtraTargets, scanExcludeIps,
  scanTimeoutMs, scanConcurrency, scanEnableMdns, scanEnableSsdp, scanEnableHttpBanner,
  scanEnableDocker, scanEnableUnifi, scanEnableOmada, scanEnableProxmox, scanEnableAdguard, scanEnableTraefik, scanEnableUnifiClassic, scanEnableExposureFiles, scanEnableFirewallUnifi, scanEnableFirewallNft,
  scanUseLlm, scanUseCredentials, scanAutoEnabled, scanAutoIntervalHours`.

## Schnittstellen

| Methode | Pfad | Rolle | Zweck |
|---|---|---|---|
| POST | /api/scans | ADMIN | Scan starten, `{scanId}`; 409 bei laufendem Scan |
| GET | /api/scans | MEMBER | Letzte 20 Scans + laufender Scan |
| GET | /api/scans/{scan_id} | MEMBER | Ein Scan inkl. Protokoll; 404 wenn unbekannt |
| POST | /api/settings/oui/refresh | ADMIN | IEEE-Herstellerdatenbank laden, `{ok, message, entries}` |

Berührt: `GET /api/settings` liefert `ouiLoaded`, `ouiEntries`
([einstellungen-und-llm-provider](../einstellungen-und-llm-provider/spec.md)).

UI-Seite(n): `frontend/src/pages/mehr/ScanPage.tsx` (Route `/scan`, admin-only; pollt alle 1,5 s nur
solange der Scan läuft und der Tab sichtbar ist). Scan-Einstellungen in `frontend/src/pages/SettingsPage.tsx`.

## Nicht-Ziele und Grenzen

- Nur IPv4 aktiv; kein IPv6-Scan.
- Keine Authentifizierung, kein Schreiben, keine Exploits; nur Connect-Scans, Multicast-Anfragen,
  HTTP-GETs.
- Geroutete Netze: keine MAC/Hersteller, kein mDNS/SSDP, stille Geräte unsichtbar
  (`docs/multi-vlan.md`).
- Kein Abbruch eines laufenden Scans über die API.
- Inhalt von Controller-Quellen, Zugangs-Abfrage, KI-Einordnung, Doku: eigene Specs
  ([netzwerkressourcen-vlans](../netzwerkressourcen-vlans/spec.md),
  [credentialed-probing](../credentialed-probing/spec.md),
  [klassifikation-llm](../klassifikation-llm/spec.md), [dokumentation](../dokumentation/spec.md)).

## Ist-Implementierung (nur Referenz, [Impl])

- Python/asyncio; Ping und `ip neigh`/`ip addr`/`ip route` als Subprozesse, `/proc/net/arp` als
  Rückfall; mDNS über `zeroconf` in einem Thread; Gateway aus `ip route show default`, DNS aus
  `/etc/resolv.conf`; Host-IP über verbundenen UDP-Socket zu 8.8.8.8:53 (sendet nichts).
- Fortschrittswerte: 1 OUI, 2 Bereiche, 5–35 Lebend-Erkennung (Update alle 16 Adressen), 36–60
  Ports, 62 Namen/Banner, 76 mDNS/UPnP, 78 Shelly, 86 Docker, 87 UniFi/Omada, 88 Proxmox/AdGuard,
  89 KI, 94 Inventar, 93 Zugänge, 96 Doku, 100 Fertig.
- Scan läuft als `asyncio.Task` im API-Prozess; Bezeichnung im Feld `subnets` beim manuellen Start
  = Bereichsliste oder „automatisch“.
- `Scheduler.status()` existiert, wird aber über keine Route ausgeliefert.

## OFFEN

- > OFFEN: Fortschritt springt rückwärts (94 % „Inventar aktualisieren“, dann 93 % Zugangs-Abfrage,
  `pipeline.py:480`/`:522`). → #138
- > OFFEN: Einzelziele umfassen IPs *aller* Inventar-Geräte außerhalb der Bereiche (auch entdeckte
  Controller-Clients/Proxmox-Gäste), nicht nur „von Hand eingetragene“ wie der Docstring sagt
  (`pipeline.py:42`). Kann viele geroutete Ziele erzeugen. → #138
- > OFFEN: Ungültiger Freitext-Bereich (z. B. „bad“) plus ein mDNS/SSDP-Fund außerhalb von
  `alive` führt in `discovery.py:859` zu `ValueError` aus `ip_network` und lässt den ganzen Scan
  scheitern. → #137
- > OFFEN: README behauptet, IPv6-Geräte erscheinen per mDNS/SSDP; der Code nimmt nur IPs in
  IPv4-Scan-Bereichen auf (`discovery.py:859`), IPv6-Funde werden verworfen. → #136
- > OFFEN: Port 81 steht in der Banner-Portliste, aber nicht im Port-Katalog, wird also nie als
  offen erkannt (`discovery.py:341`, `ports.py:12`). → #138
- > OFFEN: Ohne geladenes OUI-Register versucht jeder Scan erneut den Download (bis 120 s), auch
  offline. → #138
- > OFFEN: MEMBER darf `GET /api/scans*` inkl. Protokoll lesen (Gerätenamen, Fehlertexte der
  Zugangs-Abfrage), obwohl die Scan-Seite admin-only ist. Absicht? → #119
- > OFFEN: Start-Prüfung „läuft schon ein Scan“ und Anlegen sind nicht atomar (Rennen
  Zeitplan/manuell theoretisch möglich). → #129
- > OFFEN: Namensvergabe für Nicht-Container ohne IP bei Duplikaten: kein Suffix, Duplikat bleibt. → #138
- > OFFEN: Abgeschaltete Quelle (`scanEnableDocker=false`, Controller aus) setzt alle bisher aus
  dieser Quelle entdeckten Geräte beim nächsten Scan auf `offline`. → #139
