# Topologie (Netzplan)

> Status: Ist-Verhalten, aus dem Code zurückgewonnen (Stand 0159807). Quellen als `datei:zeile`.

## Zweck

Haushaltsmitglieder ohne Netzwerkwissen sollen auf einen Blick sehen, wie das Heimnetz aufgebaut
ist: wo das Internet hereinkommt, welche Router und Verteiler (Switche, Access Points) es gibt, wie
die als wichtig markierten Geräte angebunden sind und ob sie gerade erreichbar sind. Eine zweite
Ansicht zeigt dasselbe Inventar nach IP-Netzen (Subnetze/VLANs) gruppiert, sobald mehr als ein Netz
im Einsatz ist. Der Plan wird ohne manuelle Pflege aus dem Inventar abgeleitet.

## Rollen und Rechte

| Aktion | ADMIN | MEMBER |
|---|---|---|
| Physischen Plan ansehen | ja | ja |
| Layer-3-Plan ansehen | ja | ja |
| Kasten anklicken → Geräteseite / Geräteliste | ja | ja |
| Uplink-Verknüpfungen erzeugen (indirekt über Scan) | ja (fremde Route `POST /api/scans`) | nein |

Beide Routen setzen eine angemeldete Sitzung mit abgeschlossener TOTP-Einrichtung voraus (siehe
[auth-und-rollen](../auth-und-rollen/spec.md)).

## Anforderungen

### Requirement: Zwei Ansichten, immer aktuell
Das System MUSS zwei Netzplan-Ansichten als fertiges Bild liefern, eine physische und eine nach
IP-Subnetzen (Layer 3), jeweils bei jedem Abruf neu aus dem aktuellen Inventar berechnet und vom
Client nicht zwischenzuspeichern. Die UI MUSS zwischen „Physisch“ (Default) und „Layer 3
(Subnetze)“ umschalten und darunter eine kurze Erklärung der jeweiligen Ansicht zeigen. **[Muss]**

Ob das Bild server- oder clientseitig gezeichnet wird, ist frei (ADR-0008 beschreibt die heutige
Wahl). **[Impl]**

#### Szenario: Plan nach Scan
- **WENN** ein Scan ein neues Gerät mit Bedeutung „kritisch“ angelegt hat und der Plan neu geladen wird
- **DANN** enthält der physische Plan dieses Gerät ohne weitere Aktion

Quelle: `backend/app/main.py:1583`, `backend/app/main.py:1589`, `frontend/src/pages/geraete/PlanPage.tsx`

### Requirement: Feste Ebenenfolge im physischen Plan
Das System MUSS den physischen Plan von oben nach unten in fester Reihenfolge aufbauen, jede Ebene
beschriftet: „Internet“ → „Router“ (Art `router`) → „Verteilung (Switche, WLAN)“ (Art `network`) →
„Wichtige Geräte“ (Bedeutung `critical`). Leere Ebenen entfallen. Der Internet-Kasten trägt den
Untertitel „Zugang für <homeName>“, wenn ein Name des Zuhauses gesetzt ist. Router- und
Verteilerkästen zeigen Name und IP. **[Muss]**

#### Szenario: Nur Router vorhanden
- **WENN** das Inventar einen Router „FritzBox“ (192.168.1.1) und sonst nur nicht-kritische Endgeräte enthält
- **DANN** zeigt der Plan Internet → FritzBox und keine Ebene „Verteilung“ oder „Wichtige Geräte“

Quelle: `backend/app/topology.py:335`, `backend/app/topology.py:353`, `backend/app/topology.py:364`,
`backend/app/topology.py:386`, `backend/app/topology.py:420`

### Requirement: Verkettung nach Uplink
Das System MUSS Router untereinander und Verteiler untereinander nach ihrem bekannten Uplink
(Elterngerät) verketten: ein nachgelagertes Gerät steht eine Zeile tiefer und ist mit seinem eigenen
Elterngerät verbunden. Geräte ohne bekannten Uplink innerhalb derselben Ebene hängen an der
vorherigen Ebene. Geräte in einem Uplink-Zyklus MÜSSEN trotzdem erscheinen (eigene Restzeile).
**[Muss]**

Der Uplink eines Routers ist ein manuell gesetzter Uplink auf einen anderen Router, sonst der wie im
[Layer-3-Plan](#requirement-layer-3--router-kette) aus den Subnetzen abgeleitete Upstream-Router.
Beide Ansichten zeigen eine Router-Kaskade damit gleich. **[Muss]**

#### Szenario: Zweitrouter hinter FritzBox
- **WENN** „Mikrotik“ (Router) als Uplink „FritzBox“ (Router) hat
- **DANN** steht Mikrotik eine Zeile unter FritzBox mit Linie zu FritzBox, FritzBox hängt am Internet

#### Szenario: UniFi-Gateway hinter FritzBox
- **WENN** die UCG (Router, UniFi-Zugang zugeordnet) eine WAN-Adresse 192.168.178.2 meldet und die
  FritzBox 192.168.178.1 hat
- **DANN** steht die UCG eine Zeile unter der FritzBox mit Linie zu ihr

#### Szenario: Zyklus
- **WENN** zwei Switche sich gegenseitig als Uplink haben
- **DANN** erscheinen beide in einer zusätzlichen Zeile, kein Gerät fehlt

Quelle: `backend/app/topology.py:263`, `backend/app/topology.py:287`, `backend/app/topology.py:367`,
`backend/app/topology.py:389`

### Requirement: Obergrenzen je Ebene
Das System zeichnet höchstens 6 Router, 10 Verteiler und 10 wichtige Geräte; Auswahl in der
Reihenfolge Bedeutung (kritisch, normal, sonstige), dann Name ohne Groß/Klein. Weitere Geräte
dieser Arten werden nicht gezeichnet, stehen aber in der Liste „Nicht im Plan gezeichnet“ unter dem
Plan (siehe „Restliche Geräte unter dem Plan“). **[Impl]**

#### Szenario: Zwölf Access Points
- **WENN** 12 Geräte der Art `network` mit Bedeutung „normal“ existieren
- **DANN** zeigt die Ebene „Verteilung“ die alphabetisch ersten 10

Quelle: `backend/app/topology.py:30`, `backend/app/topology.py:367`, `backend/app/topology.py:389`,
`backend/app/topology.py:427`, `backend/app/db.py:632`

### Requirement: Wichtige Geräte einzeln, unabhängig von der Art
Das System MUSS jedes als „kritisch“ markierte Gerät als eigenen Kasten zeigen, auch Container und
VMs, soweit die Obergrenze reicht. Ein kritischer Router oder Verteiler, der schon in seiner
Backbone-Ebene gezeichnet ist, bekommt keinen zweiten Kasten; die Obergrenze gilt erst nach diesem
Abzug (ein kritischer Router jenseits der Router-Obergrenze erscheint hier). Nicht-kritische Server, NAS, Container, VMs und Endgeräte erscheinen im Bild nicht einzeln.
**[Muss]**

#### Szenario: Kritische VM
- **WENN** auf einem kritischen Proxmox-Host eine kritische VM „Wichtige VM“ und eine normale VM laufen
- **DANN** hat „Wichtige VM“ einen eigenen anklickbaren Kasten, die normale VM nicht, und der Host
  zählt im Untertitel nur „1 Container/VM“

Quelle: `backend/app/topology.py:408`, `backend/app/topology.py:412`, Tests:
`backend/tests/test_topology_critical_vm.py::test_critical_vm_gets_its_own_box_instead_of_only_a_host_summary`,
`backend/tests/test_topology_critical_vm.py::test_non_critical_vm_still_folds_into_host_summary`

### Requirement: Anbindung wichtiger Geräte
Das System MUSS ein wichtiges Gerät mit dem im Plan bereits gezeichneten Gerät verbinden, an dem es
tatsächlich hängt, in dieser Priorität: (1) sein eigenes Elterngerät (Host einer VM/eines
Containers, Controller-Uplink), (2) ein per Nachbarschaftsprotokoll erkannter Nachbar, (3) sonst die
unterste Backbone-Ebene (Mitte der letzten Verteilungs- bzw. Router-Zeile, sonst Internet). Eine
unsichere Zuordnung DARF NICHT geraten werden; dann gilt (3). **[Muss]**

#### Szenario: LLDP-Nachbar ist ein Switch
- **WENN** die ausgelesenen Nachbardaten eines Switches die MAC eines kritischen NAS enthalten
- **DANN** ist das NAS mit genau diesem Switch verbunden, nicht mit dem allgemeinen Strang

Quelle: `backend/app/topology.py:425`, `backend/app/topology.py:440`, `backend/app/topology.py:446`

### Requirement: Nachbarschaftsdaten auswerten
Das System MUSS aus den beim Auslesen gesammelten Nachbardaten (MikroTik-Neighbor-Liste, ArubaOS
LLDP-Remote-Tabelle, Cisco CDP-Detail, SNMP-LLDP-MIB-Walk) Kanten zwischen zwei bekannten
Inventargeräten bilden: Abgleich zuerst über MAC (format- und schreibweisenunabhängig), dann über
den Namen (ohne Groß/Klein, getrimmt). Kanten entstehen nur, wenn beide Enden bekannt sind, sind
ungerichtet, und Selbstbezüge werden verworfen. Ein nicht lesbares Format MUSS ohne Fehler zu
„keine Kante“ führen. **[Muss]**

Parserdetails (Regex statt fester Spalten; Aruba-Chassis-ID als sechs Hex-Oktette mit Leerzeichen;
CDP liefert nur Namen; SNMP gruppiert nach den letzten drei OID-Komponenten) **[Impl]**.

#### Szenario: Unbekannter Nachbar
- **WENN** ein Switch einen Nachbarn „printer-xyz“ meldet, den das Inventar nicht kennt
- **DANN** wird keine Kante gezeichnet und der Plan rendert normal

Quelle: `backend/app/topology.py:69`, `backend/app/topology.py:171`, `backend/app/topology.py:193`

### Requirement: Host-Zusammenfassung für Container/VMs
Das System MUSS bei einem wichtigen Host jeder Art (z. B. auch `pc`), dem nicht-kritische Container/VMs zugeordnet
sind, im Kasten „<IP> · <N> Container/VM, <M> aktiv ▸“ zeigen (M = Anzahl online). Ein Klick auf
diesen Kasten MUSS die Geräteliste gefiltert auf diesen Host öffnen (`/geraete?parentId=<id>`),
statt der Geräteseite. **[Muss]**

#### Szenario: Host mit zwei Containern
- **WENN** ein kritischer Server 10.0.0.5 zwei Container hat, einer online
- **DANN** lautet der Untertitel „10.0.0.5 · 2 Container/VM, 1 aktiv ▸“ und der Klick führt zur
  gefilterten Liste

Quelle: `backend/app/topology.py:430`, `backend/app/topology.py:240`,
`frontend/src/pages/geraete/PlanPage.tsx`, Test:
`backend/tests/test_topology_critical_vm.py::test_non_critical_vm_still_folds_into_host_summary`

### Requirement: Klickbare Kästen, statisches Bild
Das System MUSS jeden Kasten, der ein Inventargerät darstellt, mit dessen Geräteseite
(`/geraete/<id>`) verknüpfen. Internet- und Layer-3-Subnetzkästen stellen kein Gerät dar und sind
nicht klickbar (kein `data-system-id`). Der Plan MUSS ohne Zoomen, Ziehen oder Neu-Anordnen auskommen. **[Muss]**

#### Szenario: Klick auf Router
- **WENN** ein Nutzer im physischen Plan auf „FritzBox“ klickt
- **DANN** öffnet sich die Geräteseite der FritzBox

Quelle: `backend/app/topology.py:233`, `frontend/src/pages/geraete/PlanPage.tsx`,
`docs/adr/0008-topologie-als-server-svg.md`

### Requirement: Status sichtbar und erklärt
Das System MUSS bei jedem Gerätekasten (Router, Verteiler, wichtige Geräte, Router im Layer-3-Plan)
den Erreichbarkeitsstatus kennzeichnen: erreichbar (grün), nicht erreichbar (rot), unbekannt
(neutral), jeweils zusätzlich als Wort „● erreichbar“ / „● nicht erreichbar“ / „● unbekannt“
(jeder andere Statuswert gilt als unbekannt). Beide Pläne MÜSSEN die Legende „erreichbar“ /
„nicht erreichbar“ enthalten. Internet- und Subnetzkästen tragen kein Statuswort. **[Muss]**

#### Szenario: Ausgefallener Switch
- **WENN** ein Switch den Status `offline` hat
- **DANN** hat sein Kasten einen roten Rahmen und die Zeile „● nicht erreichbar“

Quelle: `backend/app/topology.py:_box`, `backend/app/topology.py:_legend`, Tests:
`backend/tests/test_topology_layout.py::test_box_shows_status_word`,
`backend/tests/test_topology_layout.py::test_layer3_has_legend_and_status`

### Requirement: Restliche Geräte unter dem Plan
Das System MUSS alle Geräte, die der physische Plan nicht zeichnet (Maßstab: die `data-system-id`
im SVG, in beiden Ansichten gleich), unter dem Plan in aufklappbaren Gruppen auflisten, in dieser
Reihenfolge: „Router & Verteilung“ (router, network), „Server & Speicher“ (server, nas),
„Container & VMs“ (container, vm), „Computer & Mobilgeräte“ (pc, mobile), „Smart Home“ (smarthome,
iot), „Wärme, Klima & Energie“ (heating, climate, energy), „Drucker, Medien & Kameras“ (printer,
media, camera), „Weitere Geräte“ (other). Gruppenkopf: Anzahl, Bezeichnung, „<n> erreichbar“ bzw.
„keins erreichbar“; Zeilen: Symbol, Name (Link), IP oder „—“, Status-Badge in Worten. Leere Gruppen
entfallen. Ist der Plan noch nicht geladen, bleibt die Liste ausgeblendet. **[Muss]**

#### Szenario: Sechs Smart-Home-Geräte
- **WENN** sechs normale Geräte der Art `iot` existieren, zwei online
- **DANN** steht unter dem Plan zugeklappt „6 Smart Home — 2 erreichbar“

Quelle: `frontend/src/pages/geraete/PlanPage.tsx`, `frontend/src/pages/geraete/PlanPage.tsx`

### Requirement: Netzplan-Seite
Die Route `/plan` MUSS die Seite `PlanPage` zeigen; das SVG selbst ist ein
statisches Bild (ADR-0008/0009). **[Muss]**
- Die Ansicht steht in der URL (`?view=layer3`; ohne Parameter physisch), Zurück und Neuladen behalten sie.
- Kein Seitentitel; der Erklärtext zur Ansicht steht hinter „ⓘ Wie lese ich den Plan?“.
- Genau eine Statuszeile statt Ausfall-Meldung plus Liste: Grundmenge sind die überwachten Geräte
  aus `/api/monitor` (dieselbe wie der Status-Hero der Startseite). Nur bei eingeschalteter
  Überwachung meldet sie „<n> von <m> überwachten Geräten nicht erreichbar“ mit Namen; sonst
  „Überwachung ist aus“, „Noch kein Gerät unter Beobachtung“, „Wird geprüft …“ oder „Alle <m>
  überwachten Geräte erreichbar“. Bei ausgeschalteter Überwachung zeigt die Liste den letzten Stand
  („zuletzt …“) ohne Alarmfarbe.
- Darunter „Überwachte Geräte“ als Liste mit Status-Chip (Adresse · Port bzw. Ping); auf dem Handy
  (unter 760 px) steht diese Liste vor dem Bild, das Bild dort in doppelter Bildschirmbreite in einem
  seitlich verschiebbaren Rahmen (die Seite selbst scrollt nicht seitlich). Kein Zoom- oder Ziehen-
  Bedienelement: bewusst keine Zoom-/Ziehen-Bedienelemente (ADR-0008, Constitution D5); auf dem Handy
  seitlich verschiebbar, Pinch-Zoom des Browsers. Eine Änderung bräuchte eine neue ADR.
- „Nicht im Plan gezeichnet“ (die Gruppen von oben) und „Letzte Zustandswechsel“ sind einklappbar.
- „Diagnose“: „Jetzt prüfen“ (ADMIN), „DNS testen“, „Speedtest“; Ergebnisse mit Uhrzeit.

#### Szenario: Ansicht in der URL
- **WENN** ein Benutzer auf „Layer 3“ wechselt, ein Gerät im Plan öffnet und Zurück drückt
- **DANN** zeigt `/plan?view=layer3` wieder den Layer-3-Plan

#### Szenario: Überwachung aus
- **WENN** die Überwachung abgeschaltet ist und ein überwachtes Gerät zuletzt `offline` war
- **DANN** sagt die Statuszeile „Überwachung ist aus“ statt einen Ausfall zu melden

Quelle: `frontend/src/pages/geraete/PlanPage.tsx`, `frontend/src/lib/time.ts`

### Requirement: Leerer physischer Plan
Das System MUSS bei leerem Inventar nur den Internet-Kasten und den Hinweis „Noch keine Geräte
erfasst — ein Netzwerk-Scan füllt diesen Plan.“ zeigen. **[Muss]**

#### Szenario: Frische Installation
- **WENN** noch kein Gerät existiert
- **DANN** zeigt der Plan Internet und den Hinweistext

Quelle: `backend/app/topology.py:451`

### Requirement: Layer-3 – Subnetzzuordnung
Das System MUSS im Layer-3-Plan jedes Nicht-Router-Gerät mit IP dem engsten aktiven Controller-Netz
(IPv4-CIDR aus [Netzwerkressourcen](../netzwerkressourcen-vlans/spec.md)) zuordnen, das seine IP
enthält; ohne passendes Controller-Netz dem /24 seiner IP; nicht als IPv4 lesbare Adressen dem
Knoten „unbekanntes Netz“. **[Muss]** (Fallback /24 **[Impl]**)

#### Szenario: Controller-Netz kleiner als /24
- **WENN** ein aktives Controller-Netz 192.168.20.0/26 existiert, der Router UCG 192.168.20.1 als
  Eigentümer hat und zwei Sensoren 192.168.20.2/.3 vorhanden sind
- **DANN** zeigt der Plan „192.168.20.0/26“ und nicht „192.168.20.0/24“

Quelle: `backend/app/topology.py:675`, `backend/app/topology.py:685`, Test:
`backend/tests/test_topology_critical_vm.py::test_layer3_plan_uses_controller_cidr_instead_of_assuming_a_24`

### Requirement: Layer-3 – Router und ihre Netze
Das System MUSS jedem Router alle Subnetze zuordnen, in denen er eine Schnittstellenadresse hat
(aus ausgelesenen Schnittstellendaten), alle aktiven Controller-Netze, deren Eigentümer er ist, und
das Netz seiner privaten WAN-Schnittstellenadresse (aktive WAN-Ressource mit `interfaceIp`, engstes
Controller-Netz, sonst /24; öffentliche Adressen zählen nicht). Ohne Schnittstellendaten gilt das /24
seiner eigenen IP. Subnetzmasken, `0.x`, `127.x`,
`255.255.255.255` und Zeilen mit „gateway“ zählen nicht als Schnittstellenadresse. **[Muss]**

Als Router gelten in dieser Ansicht alle Geräte der Art `router` mit IP oder als Eigentümer eines
aktiven Controller-Netzes, unabhängig von der IP-Endung; ein Router mit keinem von beiden fehlt in
dieser Ansicht. Router werden nach Name sortiert. **[Impl]**

Gerätezahlen der Subnetze (inkl. „N erreichbar“ und Mindestschwelle) zählen keine Docker-Container
und keine entdeckten, offline gemeldeten Geräte, deren `lastSeen` älter als 30 Tage ist (nicht
lesbares `lastSeen` zählt mit). **[Impl]**

Überlappt eine /24-Näherung aus Schnittstellendaten ein aktives exaktes Controller-CIDR, geht nur
das CIDR in die Ketteninferenz ein. **[Impl]**

#### Szenario: Router ohne .1/.254
- **WENN** ein Router 192.168.1.5 existiert
- **DANN** erscheint er als Router im Layer-3-Plan

#### Szenario: Controller-CIDR statt Näherung
- **WENN** ein Router ein Probe-/24 und ein Controller-/26 im selben Netz hat
- **DANN** zeigt der Plan nur das /26

#### Szenario: Ungeprüfter Router
- **WENN** ein Router 192.168.1.1 ohne ausgelesene Schnittstellendaten existiert
- **DANN** gilt 192.168.1.0/24 als sein Netz

Quelle: `backend/app/topology.py:507`, `backend/app/topology.py:632`, `backend/app/topology.py:669`,
`backend/app/topology.py:701`

### Requirement: Layer-3 – Router-Kette
Das System MUSS hintereinandergeschaltete Router als Kette Internet → erster Router → zweiter Router
→ dessen Netze zeigen. Ein manuell gesetzter Uplink auf einen anderen Router gewinnt; sonst ist der
Upstream derjenige Router mit den wenigsten Subnetzen, dessen nicht leere Subnetzmenge eine echte
Teilmenge der eigenen ist. Ein Subnetz, das ein Router mit seinem Upstream teilt, MUSS nur beim Upstream
erscheinen. Bei gleichwertigen Ansprüchen gewinnt der alphabetisch erste Router. **[Muss]**
(Inferenzverfahren **[Impl]**)

#### Szenario: Mikrotik hinter FritzBox
- **WENN** FritzBox die Netze {192.168.178.0/24} und Mikrotik {192.168.178.0/24, 10.1.1.0/24} hat
- **DANN** hängt Mikrotik unter FritzBox, 192.168.178.0/24 unter FritzBox und 10.1.1.0/24 unter
  Mikrotik (jeweils sofern das Subnetz mindestens 3 Geräte zählt)

#### Szenario: UniFi-Gateway ohne eigene IP hinter FritzBox
- **WENN** die UCG keine IP hat, aber die Controller-Netze 192.168.1.0/24 (VLAN 1) und
  192.168.20.0/24 (VLAN 20) besitzt und ihre WAN-Schnittstelle 192.168.178.2 meldet
- **DANN** hängt die UCG unter der FritzBox, ihre beiden Netze mit „VLAN 1“/„VLAN 20“ unter der UCG
  und 192.168.178.0/24 nur unter der FritzBox

Quelle: `backend/app/topology.py:597`, `backend/app/topology.py:707`, `backend/app/topology.py:719`,
Test: `backend/tests/test_topology_router_cascade.py`

### Requirement: Layer-3 – Subnetzkästen
Das System MUSS je Subnetz einen Kasten mit Titel = CIDR und Untertitel „<N> Gerät“/„<N> Geräte“
[· „VLAN <id>“] [· „<m> erreichbar“ bzw. „keins erreichbar“] zeigen. N zählt die zugeordneten
Geräte plus den besitzenden Router. Die VLAN-ID stammt aus dem Controller-Netz oder aus den
ausgelesenen Router-Schnittstellendaten. Ein Subnetz ohne besitzenden Router hängt direkt am
Internet. **[Muss]**

Subnetze mit N < 3 werden ausgeblendet. Die Kästen einer Ebene stehen numerisch aufsteigend nach
Adresse (10.0.0.0/24 vor 192.168.2.0/24 vor 192.168.10.0/24), bei gleicher Adresse kürzeres Präfix
zuerst, „unbekanntes Netz“ zuletzt; unabhängig von Einfügereihenfolge und Hash-Seed. **[Impl]**

#### Szenario: Kleines Netz
- **WENN** ein Subnetz nur 2 Geräte und keinen Router hat
- **DANN** erscheint es nicht im Layer-3-Plan

Quelle: `backend/app/topology.py:567`, `backend/app/topology.py:594`, `backend/app/topology.py:724`

### Requirement: Layer-3 – Leerzustände
Das System MUSS ohne Router und ohne angezeigte Subnetze einen Hinweis zeigen: „Noch keine Geräte
mit bekannter Adresse erfasst.“, falls kein Gerät eine IP hat, sonst „Nur Netze mit weniger als 3
Geräten gefunden — zur Übersichtlichkeit ausgeblendet.“ **[Muss]**

#### Szenario: Nur zwei Geräte
- **WENN** nur zwei Endgeräte mit IP und kein Router existieren
- **DANN** zeigt der Layer-3-Plan den zweiten Hinweistext

Quelle: `backend/app/topology.py:777`

### Requirement: Uplinks beim Scan ableiten
Das System MUSS bei jedem Scan nach dem Inventar-Update Elterngeräte ableiten: **[Muss]**
- Docker-Container → Gerät mit derselben IP wie der scannende Host (Vorrang Art server, nas, pc,
  sonstige), nur wenn der Container noch kein Elterngerät hat.
- Proxmox-Gast → Inventargerät (server/nas), dessen Hostname bzw. Name dem Proxmox-Knoten
  entspricht (ohne Groß/Klein), sonst das Gerät, dem der Proxmox-Zugang zugeordnet ist.
- Proxmox-Gäste werden bei jedem Scan neu zugeordnet (eine migrierte VM wandert mit).
- Omada-Gerät/-Client → Gerät mit der gemeldeten Uplink-MAC.
- UniFi-Gerät/-Client → Gerät mit der gemeldeten Controller-Geräte-ID des Uplinks.

Ein per PATCH gesetztes Elterngerät (`extra.parentSource = "manual"`) wird von Proxmox-, Omada- und
UniFi-Verknüpfung nie überschrieben; Controller-Verknüpfungen markieren `parentSource` mit
`proxmox`/`omada`/`unifi`. `parentId: null` im PATCH entfernt Elterngerät und Marker. Bestand ohne
Marker gilt als überschreibbar. **[Muss]**

Nicht auflösbare Uplinks und Selbstbezüge ändern nichts; ein erneuter Lauf ohne Änderung meldet
0 Verknüpfungen. Reihenfolge: Docker, Omada, UniFi; Log „<n> Omada-/UniFi-Gerät(e)/Client(s) im
Netzplan mit ihrem Uplink verknüpft“. **[Impl]**

#### Szenario: UniFi-Kette
- **WENN** Switch → Gateway, AP → Switch, Drucker → AP als UniFi-Uplinks gemeldet sind
- **DANN** sind 3 Elterngeräte gesetzt, ein zweiter Lauf meldet 0

#### Szenario: Manuelles Elterngerät
- **WENN** ein Gerät per PATCH ein Elterngerät erhalten hat und der Controller einen anderen Uplink meldet
- **DANN** bleibt das manuelle Elterngerät

#### Szenario: Unbekannte Uplink-MAC
- **WENN** ein Omada-AP eine Uplink-MAC meldet, die kein Inventargerät hat
- **DANN** bleibt sein Elterngerät leer

Quelle: `backend/app/pipeline.py:242`, `backend/app/pipeline.py:263`, `backend/app/pipeline.py:288`,
`backend/app/pipeline.py:492`, `backend/app/db.py:1110`, Tests:
`backend/tests/test_pipeline_topology.py::test_link_unifi_topology_resolves_controller_device_ids_instead_of_mac_addresses`,
`backend/tests/test_pipeline_topology.py::test_link_omada_topology_resolves_uplink_mac_to_parent_id`,
`backend/tests/test_pipeline_topology.py::test_link_omada_topology_ignores_unresolvable_uplink`,
`backend/tests/test_pipeline_topology.py::test_assign_proxmox_parents_matches_guest_to_its_own_node`,
`backend/tests/test_pipeline_topology.py::test_assign_proxmox_parents_falls_back_when_node_has_no_own_row`

### Requirement: Fremde Namen sicher darstellen
Das System MUSS alle Texte im Plan (Gerätenamen, Hostnamen, Name des Zuhauses) so maskieren, dass
sie weder Markup noch Skript einschleusen können, weil Namen von Geräten im Netz selbst gemeldet
werden und das Bild in die Seite eingebettet wird. **[Muss]**

#### Szenario: Bösartiger mDNS-Name
- **WENN** ein Gerät den Namen `<script>alert(1)</script>` meldet und kritisch ist
- **DANN** erscheint der Text maskiert und es wird kein Skript ausgeführt

Quelle: `backend/app/topology.py:45`, `frontend/src/pages/geraete/PlanPage.tsx`

### Requirement: Lesbarkeit
Das System MUSS lange Namen kürzen statt sie überlaufen zu lassen. **[Muss]** Maße: Breite 1000,
Kastenhöhe 64, Ebenenabstand 90, Kastenbreite max. 200 (Router 260, Internet/Layer-3 220),
Kastenbreite mindestens 90: Bei mehr Kästen je Ebene wächst die Breite (viewBox) über 1000,
Kürzung mit „…“ auf ca. Breite/7,2 Zeichen (min. 6; Untertitel +4). **[Impl]**

#### Szenario: Langer Name
- **WENN** ein Router „FRITZ!Box 7590 AX Wohnzimmer Erdgeschoss Hauptanschluss“ heißt
- **DANN** endet sein Titel im Kasten mit „…“

Quelle: `backend/app/topology.py:_canvas_width`, `backend/app/topology.py:_row`, `backend/app/topology.py:24`, `backend/app/topology.py:49`, `backend/app/topology.py:220`,
`backend/app/topology.py:246`

## Daten

Aus [data-model](../../contracts/data-model.md) gelesen: `systems` (`id`, `kind`, `name`,
`hostname`, `ip`, `mac`, `status`, `importance`, `parentId`, `extra.probe` (Nachbar-, Schnittstellen-,
VLAN-Fakten), `extra.omada.uplinkMac`, `extra.unifi.deviceId`/`uplinkDeviceId`,
`extra.proxmox.node`, `discoverySource`); `networkResources` (aktiv, Art `network`: `facts.cidr`,
`facts.vlanId`, `ownerSystemId`); `settings.homeName`.

Geschrieben (nur durch den Scan): `systems.parentId`.

## Schnittstellen

| Methode | Pfad | Rolle | Zweck |
|---|---|---|---|
| GET | `/api/topology.svg` | ADMIN, MEMBER | Physischer Plan als SVG (`image/svg+xml`, `Cache-Control: no-store`) |
| GET | `/api/topology-layer3.svg` | ADMIN, MEMBER | Layer-3-Plan als SVG (`image/svg+xml`, `Cache-Control: no-store`) |

Berührte fremde Routen: `POST /api/scans` ([discovery-und-scan](../discovery-und-scan/spec.md)),
`GET /api/systems` ([inventar](../inventar/spec.md)); Überwachung, DNS-Test und Speedtest auf
derselben Seite gehören zu [monitoring](../monitoring/spec.md) und [diagnose](../diagnose/spec.md).

UI-Seite(n): `frontend/src/pages/geraete/PlanPage.tsx` (Route `/plan`, Navigation „Netzplan“, alle Rollen).

## Nicht-Ziele und Grenzen

- Kein interaktiver Graph (Zoom, Ziehen, Umordnen); neue Interaktion braucht ein neues ADR.
- Kein manuelles Zeichnen oder Verschieben von Kästen; Uplinks werden nicht in der UI gepflegt.
- Nur IPv4; Layer-3 nutzt außerhalb von Controller-Netzen nur /24-Näherung.
- Nachbarschafts-Parser sind nicht gegen echte Hardware verifiziert (Modul-Docstring).
- VLAN-IDs aus Router-Fakten nur für MikroTik; Aruba/Cisco bekommen keine VLAN-Beschriftung.

## Ist-Implementierung (nur Referenz, [Impl])

- Serverseitiges SVG mit fester Farbpalette (dunkler Hintergrund), eingebettet per `fetch` +
  `dangerouslySetInnerHTML`, damit kein zweiter authentifizierter Bildabruf nötig ist
  (`frontend/src/pages/geraete/PlanPage.tsx`).
- Klickziele als `data-system-id`/`data-expand="1"` auf `<g>`-Elementen
  (`backend/app/topology.py:240`).
- Router-Schnittstellen aus Probe-Fakten `ip_addresses`/`ip` per Regex über alle Formate; VLAN-IDs
  per Join von MikroTik `vlan` (Interface → VLAN-ID) und `ip_addresses` (Subnetz → Interface)
  (`backend/app/topology.py:507`, `backend/app/topology.py:567`).
- Route deklariert `response_class=PlainTextResponse`, liefert aber `image/svg+xml`
  (`backend/app/main.py:1583`).

## OFFEN

- > OFFEN: ADR-0008 und CLAUDE.md beschreiben die Ebenen „Server → Endgeräte“ und „Container innerhalb ihres Hosts“; das Bild zeichnet aber nur „Wichtige Geräte“, Server/Endgeräte stehen als HTML-Listen darunter, Container nur als Zähler bei kritischen Hosts. Spec folgt dem Code; ADR-0009 hält diesen Stand fest. → kein Issue, ADR-0009 hält den Stand fest
