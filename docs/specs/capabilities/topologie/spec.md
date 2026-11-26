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
- **WENN** „UCG“ (Router) als Uplink „FritzBox“ (Router) hat
- **DANN** steht die UCG eine Zeile unter FritzBox mit Linie zu FritzBox, FritzBox hängt am Internet

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
tatsächlich hängt, in dieser Priorität: (1) sein eigenes Elterngerät (`parentId`: Host einer VM/eines
Containers, Controller-Uplink), (2) sonst die
unterste Backbone-Ebene (Mitte der letzten Verteilungs- bzw. Router-Zeile, sonst Internet). Eine
unsichere Zuordnung DARF NICHT geraten werden; dann gilt (2). **[Muss]**

Jede Verbindung MUSS durchgehend vom Elterngerät zum Kind gezeichnet sein: Die Waagerechte einer
Eltern-Gruppe reicht vom x des Elterngeräts bis zu allen Kindern, auch bei genau einem seitlich
versetzten Kind. Die Zeile „Wichtige Geräte“ MUSS nach Elterngeräten gruppiert sein, in der Reihenfolge
ihrer Elterngeräte von links nach rechts; Geräte ohne gezeichnetes Elterngerät stehen am Ende, innerhalb
einer Gruppe bleibt die Reihenfolge erhalten. Waagerechte verschiedener Eltern-Gruppen DÜRFEN sich NICHT
überlagern (#257). **[Muss]**

Überlappen (oder berühren) sich die x-Bereiche zweier Gruppen mit derselben Grundhöhe, wird die spätere
(nach linkem Rand) auf die nächste freie Ebene gelegt: Versatz 0, −5, +5, −10 px zur Grundhöhe, mehr
Ebenen werden auf die letzte geklemmt. Ohne Überlappung bleibt die Grundhöhe, das Bild ist dann
unverändert. Die Kinder werden nicht x-genau unter ihr Elterngerät gesetzt (`_row()` zentriert jede
Zeile). **[Impl]**

#### Szenario: Seitlich versetztes Kind
- **WENN** ein Access Point als einziges Kind an „U6+-OG“ hängt, aber seitlich davon gezeichnet wird
- **DANN** führt eine durchgehende Linie (senkrecht, waagerecht, senkrecht) von „U6+-OG“ zum Access
  Point, ohne Stummel ins Leere

#### Szenario: Zwei Eltern mit überlappender Linie
- **WENN** die Waagerechten zweier Elterngeräte sich auf derselben Höhe überlagern würden
- **DANN** liegen sie auf unterschiedlichen Höhen

#### Szenario: Elterngerät ist ein Switch
- **WENN** ein kritisches NAS als `parentId` einen im Plan gezeichneten Switch hat
- **DANN** ist das NAS mit genau diesem Switch verbunden, nicht mit dem allgemeinen Strang

#### Szenario: Unbekanntes Elterngerät
- **WENN** das `parentId` eines kritischen Geräts auf kein gezeichnetes Gerät zeigt
- **DANN** hängt es am allgemeinen Strang und der Plan rendert normal

Quelle: `backend/app/topology.py` (`render`, `_edges`, `_edge_levels`, `_order_by_parent`), Test: `backend/tests/test_topology_layout.py::test_important_device_edge_from_parent_id_and_unknown_parent_falls_back`,
`::test_single_offset_child_edge_is_continuous`, `::test_important_devices_grouped_in_parent_order`,
`::test_overlapping_parent_groups_use_different_heights`, `::test_non_overlapping_parent_groups_keep_mid_y`,
`::test_more_than_four_overlapping_groups_clamp`, `::test_layout_without_offset_children_unchanged`

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
(aus ausgelesenen Schnittstellendaten oder seinen weiteren bekannten Adressen, `systemAliases`,
nur private IPv4), alle aktiven Controller-Netze, deren Eigentümer er ist, und
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

#### Szenario: Zweitrouter hinter FritzBox
- **WENN** FritzBox die Netze {192.168.178.0/24} und die UCG {192.168.178.0/24, 10.1.1.0/24} hat
- **DANN** hängt die UCG unter FritzBox, 192.168.178.0/24 unter FritzBox und 10.1.1.0/24 unter
  der UCG (jeweils sofern das Subnetz mindestens 3 Geräte zählt)

#### Szenario: Weitere Adresse im FritzBox-Netz
- **WENN** die UCG 192.168.42.2 hat, als weitere Adresse 192.168.178.20 bekannt ist und die
  FritzBox 192.168.178.1 hat (ohne WAN-Daten der klassischen UniFi-API)
- **DANN** hängt die UCG in beiden Ansichten unter der FritzBox

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
- UniFi-Gerät/-Client → Gerät mit der gemeldeten Controller-Geräte-ID des Uplinks, außer Gäste mit
  `parentSource = proxmox` (die bleiben an ihrem Knoten; der Switchport bleibt über
  `extra.unifi.connection` sichtbar).

Rangfolge: manuell > Proxmox > UniFi. Ein per PATCH gesetztes Elterngerät (`extra.parentSource = "manual"`) wird von Proxmox- und
UniFi-Verknüpfung nie überschrieben; Controller-Verknüpfungen markieren `parentSource` mit
`proxmox`/`unifi`. `parentId: null` im PATCH entfernt Elterngerät und Marker. Bestand ohne
Marker gilt als überschreibbar. **[Muss]**

Nicht auflösbare Uplinks und Selbstbezüge ändern nichts; ein erneuter Lauf ohne Änderung meldet
0 Verknüpfungen. Reihenfolge: Docker, UniFi; Log „<n> UniFi-Gerät(e)/Client(s) im
Netzplan mit ihrem Uplink verknüpft“. **[Impl]**

#### Szenario: UniFi-Kette
- **WENN** Switch → Gateway, AP → Switch, Drucker → AP als UniFi-Uplinks gemeldet sind
- **DANN** sind 3 Elterngeräte gesetzt, ein zweiter Lauf meldet 0

#### Szenario: Proxmox-Gast mit UniFi-Uplink
- **WENN** ein Gast eine Proxmox-Zuordnung hat und UniFi ihn zusätzlich als Client mit Uplink meldet
- **DANN** bleibt der Proxmox-Knoten Elterngerät, und ein Folgelauf meldet 0 Verknüpfungen

#### Szenario: Manuelles Elterngerät
- **WENN** ein Gerät per PATCH ein Elterngerät erhalten hat und der Controller einen anderen Uplink meldet
- **DANN** bleibt das manuelle Elterngerät


Quelle: `backend/app/pipeline.py:242`, `backend/app/pipeline.py:263`, `backend/app/pipeline.py:288`,
`backend/app/pipeline.py:492`, `backend/app/db.py:1110`, Tests:
`backend/tests/test_pipeline_topology.py::test_link_unifi_topology_resolves_controller_device_ids_instead_of_mac_addresses`,
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
`hostname`, `ip`, `mac`, `status`, `importance`, `parentId`, `extra.probe` (Fakt `ip`), `extra.unifi.deviceId`/`uplinkDeviceId`,
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
- Senkrechte einer Eltern-Gruppe können die Waagerechte einer anderen kreuzen; die Ebenen verhindern
  nur das Überlagern von Waagerechten.
- Verkabelung kommt nur aus `parentId` (UniFi-Uplink, Proxmox/Docker-Host), VLAN-IDs nur aus Controller-Netzen; es gibt keine Nachbarschaftsprotokoll-Auswertung (LLDP/CDP) mehr.
- Das Bild zeichnet die Ebenen bis „Wichtige Geräte“; Server und Endgeräte stehen als HTML-Listen darunter, Container nur als Zähler bei kritischen Hosts. So festgehalten in [ADR-0009](../../../adr/0009-netzplan-ebenen-ist-stand.md).

## Ist-Implementierung (nur Referenz, [Impl])

- Serverseitiges SVG mit fester Farbpalette (dunkler Hintergrund), eingebettet per `fetch` +
  `dangerouslySetInnerHTML`, damit kein zweiter authentifizierter Bildabruf nötig ist
  (`frontend/src/pages/geraete/PlanPage.tsx`).
- Klickziele als `data-system-id`/`data-expand="1"` auf `<g>`-Elementen
  (`backend/app/topology.py:240`).
- Router-Schnittstellen aus dem Linux-Probe-Fakt `ip` per Regex, sonst aus der eigenen IP
  (`backend/app/topology.py`, `_router_subnets`); gespeicherte Altfakten anderer Art werden ignoriert.
- Route deklariert `response_class=PlainTextResponse`, liefert aber `image/svg+xml`
  (`backend/app/main.py:1583`).

## OFFEN

