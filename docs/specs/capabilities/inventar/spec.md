# Inventar

> Status: Ist-Verhalten, aus dem Code zurückgewonnen (Stand 0159807). Quellen als `datei:zeile`.

## Zweck

Das Inventar ist die zentrale Liste aller Geräte, Container und VMs im Heimnetz, ob per Scan
gefunden oder von Hand eingetragen. Der Haushalt schlägt dort nach, was ein Gerät ist, wo es steht
und ob es erreichbar ist. Der Admin pflegt Namen, Zweck, Standort und Wichtigkeit; diese Angaben
überstehen jeden späteren Scan. Doppelt erfasste Geräte (z. B. ein Router, der pro Subnetz einmal
gefunden wird) führt der Admin bewusst von Hand zusammen.

## Rollen und Rechte

| Aktion | ADMIN | MEMBER |
|---|---|---|
| Geräteliste, Gerätedetail ansehen | ja | ja |
| Konfigurationsversionen auflisten und Inhalt lesen | ja | ja (siehe OFFEN) |
| Fehlerereignisse eines Geräts ansehen | ja | ja |
| Fehlerereignisse quittieren (einzeln/alle) | ja | nein (403) |
| Gerät anlegen, bearbeiten, löschen | ja | nein (403) |
| Duplikat-Vorschläge, Aliase ansehen | ja | nein (403) |
| Zusammenführen, „kein Duplikat" markieren | ja | nein (403) |

Rollenprüfung: `backend/app/main.py:509`, `:523`, `:529`, `:536`, `:547`, `:560`, `:568`, `:579`,
`:585`, `:1406`, `:1413`, `:1421`. Test: `backend/tests/test_main_duplicates_api.py::test_endpoints_require_admin`.

## Anforderungen

### Requirement: Geräteliste
Das System MUSS allen angemeldeten Rollen die Liste aller Geräte liefern, optional gefiltert nach
exakt einer Art (`kind`), sortiert nach Wichtigkeit (`critical` → `normal` → alles andere) und dann
Name ohne Groß/Klein; jedes Gerät mit der Anzahl direkt zugeordneter Zugänge (`accountCount`, ohne
Zuordnungsregeln), der Anzahl offener, d. h. nicht quittierter Fehlerereignisse (`errorCount`) und einer abgeleiteten
Kurzbeschreibung (`description`); dazu die Anzeigenamen der Arten (`kindLabels`). **[Muss]**

#### Szenario: Filter und Reihenfolge
- **WENN** `GET /api/systems?kind=router` aufgerufen wird
- **DANN** enthält die Antwort nur Geräte mit `kind = router`, kritische zuerst, dann alphabetisch

#### Szenario: Fehlerzähler
- **WENN** Gerät A zwei, Gerät B ein und Gerät C kein offenes Fehlerereignis hat
- **DANN** ist `errorCount` 2 / 1 / 0
- Test: `backend/tests/test_db_error_events.py::test_count_error_events_by_system_is_one_query_for_all_devices`

Quelle: `backend/app/main.py:508`, `backend/app/db.py:626`, `backend/app/db.py:632`, `backend/app/db.py:1774`

### Requirement: Abgeleitete Kurzbeschreibung
Das System MUSS je Gerät eine Kurzbeschreibung liefern: die eigene Beschreibung (`descriptionMd`),
sonst der Zweck (`purpose`, außer er beginnt mit „Gerät "), sonst ein Satz aus der Art plus dem
aussagekräftigsten Dienst (bevorzugt Port 8123, 32400, 8096, 9100, 631, 445, 5001, 8006, 1883, 554,
sonst der erste) und ggf. dem Container-Image; sonst leer. Sie wird nie gespeichert, sondern bei
jedem Abruf berechnet. **[Muss]** (Formulierungen **[Impl]**)

#### Szenario: Eigene Beschreibung hat Vorrang
- **WENN** ein Gerät `descriptionMd` gesetzt hat
- **DANN** ist `description` genau dieser Text, unabhängig von Diensten

Quelle: `backend/app/docs.py:159`

### Requirement: Gerätedetail
Das System MUSS für ein Gerät liefern: alle gespeicherten Felder, die zugehörigen Zugänge
(direkt zugeordnet mit `viaAssignment=false`, über Zuordnungsregeln mit `viaAssignment=true`, ein
direkt zugeordneter Zugang erscheint nicht zusätzlich als Regel-Treffer), jeweils ohne Geheimnis,
aber mit `hasSecret`/`hasPassphrase`; die abgeleitete Kurzbeschreibung; die effektiv überwachten
Ports (`monitorPortsEffective`). Unbekannte ID → 404 „Gerät nicht gefunden.". **[Muss]**

#### Szenario: Geheimnisse bleiben verborgen
- **WENN** einem Gerät ein Zugang mit Passwort zugeordnet ist und das Detail abgerufen wird
- **DANN** enthält der Zugang weder `secretEnc` noch `passphraseEnc`, aber `hasSecret: true`

Quelle: `backend/app/main.py:546`, `backend/app/main.py:619`, `backend/app/db.py:1464`,
`backend/app/monitor.py:40`

### Requirement: Anschluss am Switch / Access Point
Das System MUSS an einem Gerät, das der UniFi-Scan zuordnen konnte, `extra.unifi.connection`
(`type` `wired`|`wifi`, `systemId` und `deviceMac` von Switch/AP, `port` bzw. `ssid`, `site`,
`accountId`) speichern und im Gerätedetail (Überblick, Steckbrief) als „Angeschlossen an: <Name>,
Port N“ bzw. „Verbunden mit: <Name> (WLAN <SSID>)“ mit Link auf das Gerät zeigen; die Oberfläche
zeigt nur Namen, Port und SSID, nie IDs oder MACs. Ein kabelgebundener Client, dessen Switch nicht im
Inventar steht, bekommt keine Verbindung; ein WLAN-Client dann nur die SSID. Wird ein Zugang
vollständig gelesen, verliert jedes Gerät mit `accountId` dieses Zugangs, das nicht mehr gemeldet wird,
die Verbindung; bei Fehler oder abgeschalteter Quelle bleibt alles. `parentId` ändert sich dadurch
nie. **[Muss]**

Quelle: `backend/app/pipeline.py`, `frontend/src/pages/device/UeberblickTab.tsx`,
Test: `backend/tests/test_pipeline_unifi_classic.py::test_connection_removed_when_client_gone_only_after_successful_read`

### Requirement: Port-VLANs am Switch
Das System MUSS an einem UniFi-Switch, den der Scan per MAC zuordnen konnte, `extra.unifi.ports`
(`accountId`, `site`, `ports[]` mit `port`, `name`, `profile`, `native` {`vlan`, `name`, `known`},
`tagged` {`mode` `all`|`none`|`custom`|``, `vlans`, `excluded`}) speichern
([ADR-0026](../../../adr/0026-unifi-port-vlans-netzaufloesung.md)); es enthält nur aufgelöste VLAN-IDs
und Netznamen, nie Netz-IDs, MACs oder Zähler. Der Wert wird bei jedem Scan ersetzt, aber nur, wenn
`stat/device`, `rest/portconf` und `rest/networkconf` aller Sites gelesen wurden; bei Fehler bleibt der
alte Stand. Ein Switch dieses Zugangs, der nicht mehr gemeldet wird, verliert die Ports, ein anderer
Zugang wird nie angefasst. Es entsteht nie ein Gerät, mehrdeutige MACs werden nicht zugeordnet. Das
Gerätedetail (Tab „Technik“) zeigt die Tabelle Port | Name | Nativ | Tagged | Angeschlossenes Gerät;
`all` liest sich „alle“ (ggf. „alle außer …“), `none` „keine“, eine nicht auflösbare Netz-ID
„unbekanntes Netz“. **[Muss]**

Quelle: `backend/app/pipeline.py`, `frontend/src/pages/device/TechnikTab.tsx`,
Test: `backend/tests/test_pipeline_unifi_classic.py::test_switch_ports_stored`,
`::test_switch_ports_replaced_each_scan`, `::test_switch_ports_kept_on_partial_failure`,
`::test_switch_ports_removed_when_switch_gone_after_full_read`

### Requirement: Absprung-Links zur Verwaltung
Das System MUSS Admins über `GET /api/systems/{id}/admin-links` Deep-Links liefern (`{"links": [{label, url}]}`,
bei keinem Link eine leere Liste, unbekannte ID 404, Member 403): für ein lokales Docker-Gerät
(`kind=container`, `extra.docker.containerId`) „In Portainer öffnen“ →
`<portainerUrl>/#!/<portainerEnvId>/docker/containers/<containerId>`, sofern URL und Umgebungs-ID gesetzt
sind; für einen Proxmox-Gast (`extra.proxmox.node` und `vmid`; `vm` → `qemu`, `container` → `lxc`)
„In Proxmox öffnen“ → `<basis>/#v1:0:=<qemu|lxc>%2F<vmid>`. Basis ist `proxmoxWebUrl`, sonst die
auf Schema+Host+Port gekürzte URL des ersten Proxmox-Zugangs am Eltern-System, sonst dessen `url`.
Entfernte Docker-Hosts bekommen keine Container-Links; das Feld `url` bleibt unverändert. Die Links
öffnen im neuen Tab mit `rel="noopener noreferrer"`. **[Muss]**

#### Szenario: Container mit Portainer
- **WENN** Portainer-URL und Umgebungs-ID gesetzt sind und ein Admin einen lokalen Container öffnet
- **DANN** enthält `links` den Portainer-Deep-Link

#### Szenario: Nichts konfiguriert
- **WENN** weder Portainer noch eine Proxmox-Basis auflösbar ist
- **DANN** ist `links` leer

Quelle: `backend/app/admin_links.py`, `backend/app/routes/systems.py`

### Requirement: Effektive Überwachungsports
Das System MUSS die überwachten Ports so bestimmen: von Hand gesetzte `monitorPorts` (erste 3);
sonst bis zu 3 bekannte offene Ports, die für die Art typisch sind; sonst die ersten 3 offenen
Ports; sonst bis zu 3 für die Art typische Ports (nur Vermutung). Leere Liste = Ping. **[Muss]**

#### Szenario: Handkonfiguration gewinnt
- **WENN** `monitorPorts = [443, 445, 22, 80]`
- **DANN** ist `monitorPortsEffective = [443, 445, 22]`

Quelle: `backend/app/monitor.py:40`, Details: [monitoring](../monitoring/spec.md)

### Requirement: Gerät von Hand anlegen
Das System MUSS ADMIN erlauben, ein Gerät mit den von Hand pflegbaren Feldern (Liste unter „Gerät
bearbeiten") anzulegen; es wird als „bestätigt" (`confirmed=1`) und „nicht gefunden" (`discovered=0`)
gespeichert. Eine mitgeschickte `id` und Systemfelder werden ignoriert; ungültige Werte → 422. Leere Felder erhalten
Defaults: `kind=other`, `name="Unbenannt"`, `importance=normal`, `status=unknown`, Rest leer.
`firstSeen`, `lastSeen`, `updatedAt` = jetzt (UTC, `YYYY-MM-DDTHH:MM:SSZ`). **[Muss]**

#### Szenario: Anlegen über die Liste
- **WENN** ADMIN in der Geräteliste „+ Gerät anlegen" wählt und einen Namen eingibt
- **DANN** wird ein Gerät mit diesem Namen und `kind=other` angelegt und oben in der Liste gezeigt

#### Szenario: Mitgeschickte ID und ungültige Werte
- **WENN** ADMIN eine bereits vergebene `id` oder eine unbekannte `kind` mitschickt
- **DANN** entsteht ein Gerät mit neuer ID (die `id` wird ignoriert) bzw. die Antwort ist 422
- Test: `backend/tests/test_main_systems_validation.py::test_post_ignores_client_id_and_system_fields`,
  `::test_post_invalid_kind_422`

Quelle: `backend/app/routes/systems.py`, `backend/app/db/systems.py`,
`frontend/src/pages/geraete/InventoryPage.tsx`

### Requirement: Gerät bearbeiten
Das System MUSS ADMIN erlauben, per Teil-Update genau diese Felder zu ändern: `kind, name,
hostname, ip, mac, vendor, model, os, location, purpose, descriptionMd, url, docUrl, docLink, notes,
importance, parentId, monitored, monitorPorts, tags`. Alle anderen Schlüssel (insbesondere die
Systemfelder `id, status, discovered, confirmed, discoverySource, discoveryKey, extra, openPorts,
services, lastSeen`) werden still ignoriert und sind nur durch Scan/Überwachung schreibbar. Nur im
Patch enthaltene Felder werden geschrieben (kein Lost Update); die UI schickt nur geänderte Felder.
Jede Bearbeitung setzt `confirmed=1` (und damit `updatedAt`, auch bei leerem Patch). Ungültige Werte
→ 422: `kind` nicht in den 17 Arten, `importance` nicht `critical|normal|low` (auch `null`/`""`),
`monitorPorts` mit mehr als 3 Einträgen, Nicht-Ganzzahlen, Ports außerhalb 1–65535 oder Duplikaten
(`null`/`[]` erlaubt), `parentId` unbekannt, das Gerät selbst oder ein Zyklus (`null`/`""` löscht
den Verweis). Pydantic-Fehler kommen vor dem 404; unbekannte ID mit gültigem Body → 404. **[Muss]**

#### Szenario: Veralteter Body überschreibt keine Scan-Daten
- **WENN** ein Scan `status`/`openPorts`/`extra` ändert, nachdem ADMIN das Gerät geladen hat, und ADMIN dann speichert
- **DANN** bleiben die Scan-Daten erhalten
- Test: `backend/tests/test_main_systems_validation.py::test_patch_stale_body_keeps_scan_data`,
  `::test_patch_ignores_system_fields`, `::test_patch_monitor_ports_invalid`

#### Szenario: Bearbeiten schützt vor Scans
- **WENN** ADMIN den Namen eines gefundenen Containers ändert
- **DANN** behält der nächste Scan diesen Namen bei
- Test: `backend/tests/test_db_docker_names.py::test_confirmed_row_keeps_name`

Quelle: `backend/app/main.py:567`, `backend/app/main.py:569`, `backend/app/db.py:618`, `backend/app/db.py:671`,
`backend/app/db.py:675`, `backend/app/db.py:686`

Editierbar in der UI (Formular „Gerät bearbeiten"): Name, Adresse, Hostname, Hersteller, Modell,
Standort, Weboberfläche-URL, Hersteller-Doku-URL, eigene Doku-URL, Zweck, Art (17 Arten, siehe
[data-model](../../contracts/data-model.md)), Bedeutung (`critical`/`normal`/`low`), Beschreibung
(Markdown), interne Notiz, Schlagworte (kommagetrennt), „Dauerhaft überwachen", Prüfports (max. 3,
1–65535). `frontend/src/pages/device/DevicePage.tsx`.

### Requirement: Gepflegte Angaben überstehen Scans
Das System MUSS bei einem bestätigten Gerät (`confirmed=1`) durch Scans nur flüchtige Fakten
aktualisieren (IP, Status, Ports/Dienste, `extra`, `lastSeen`, Discovery-Schlüssel) und leere Felder
`hostname, mac, vendor, model, os, docUrl, docLink, purpose, location` ergänzen; `name`, `kind`,
`importance`, `descriptionMd` u. a. bleiben unangetastet. **[Muss]**

#### Szenario: Bestätigter Name bleibt trotz UniFi
- **WENN** ein bestätigtes Gerät einen eigenen Namen hat und UniFi einen anderen meldet
- **DANN** bleibt der HomeAtlas-Name
- Test: `backend/tests/test_db_dedup.py::test_upsert_updates_unifi_name_but_preserves_confirmed_homeatlas_name`

Quelle: `backend/app/db.py:1133`, `backend/app/db.py:1224`, `backend/app/db.py:1237`; Suchreihenfolge,
Feldregeln für bestätigte/unbestätigte Geräte und UniFi-Namensvorrang: Requirement „Wiedererkennung
bestehender Geräte“ in [discovery-und-scan](../discovery-und-scan/spec.md)

### Requirement: „Kritisch" schaltet die Überwachung einmalig ein
Das System MUSS beim Übergang einer Bedeutung auf `critical` (Anlegen, Bearbeiten, Zusammenführen,
Scan-Übernahme) für ein Gerät mit nicht-leerer IP oder Hostname einmalig `monitored=1` setzen.
„Kritisch ⇒ überwacht" ist nur dieser Standard beim Markieren, keine feste Regel: ADMIN kann die
Überwachung danach abwählen und sie bleibt aus (kein Zurücksetzen bei PATCH, Monitor-Runde, Scan
oder Start). Ein im selben Schreibvorgang mitgeschickter `monitored`-Wert gewinnt immer über den
Standard, auch wenn er dem gespeicherten entspricht; das Bearbeiten-Formular schickt `monitored`
deshalb bei jeder Änderung der Bedeutung mit.
Ohne Adresse bleibt `monitored` unverändert (eine später nachgetragene Adresse schaltet nichts
ein). Entfernen von „kritisch" ändert `monitored` nicht; erneutes Markieren ist ein neuer Übergang
und schaltet wieder ein. **[Muss]**

#### Szenario: Gerät wird kritisch
- **WENN** ADMIN ein Gerät mit IP auf „kritisch" setzt
- **DANN** ist es in der Antwort des PATCH bereits `monitored=1`

#### Szenario: Beim Markieren gleich wieder abgewählt
- **WENN** ADMIN ein nicht überwachtes Gerät auf „kritisch" setzt, den automatisch gesetzten Haken abwählt und speichert
- **DANN** bleibt `monitored=0`

#### Szenario: Überwachung abgewählt
- **WENN** ADMIN bei einem kritischen Gerät `monitored` auf 0 setzt
- **DANN** bleibt es 0, auch nach weiteren PATCHes, Monitor-Runden und Scans

Quelle: `backend/app/db/systems.py::_enables_monitoring_on_critical`, Test: `backend/tests/test_critical_monitoring.py`

### Requirement: Gerät löschen
Das System MUSS ADMIN erlauben, ein Gerät zu löschen. Dabei MÜSSEN mitgelöscht werden: direkt
zugeordnete Zugänge, deren Zuordnungsregeln, Zuordnungsregeln, die auf dieses Gerät zeigen, seine
Aliase und „kein Duplikat"-Markierungen sowie die Konfigurationsversionen, Fehler- und
Monitor-Ereignisse des Geräts. Kinder (Container/VMs) verlieren ihren Host-Verweis
(`parentId=NULL`), bleiben aber bestehen. Eine unbekannte ID liefert 404. Hat das Gerät direkt
zugeordnete Zugänge, liefert DELETE ohne `?withAccounts=true` 409 (mit der Anzahl, ohne etwas zu
löschen); mit dem Parameter werden die Zugänge mitgelöscht. Ohne Zugänge genügt DELETE ohne
Parameter. Antwort sonst `{"ok": true}`. **[Muss]**

#### Szenario: Aliase und Markierungen verschwinden
- **WENN** ein zusammengeführtes Gerät mit „kein Duplikat"-Markierung gelöscht wird
- **DANN** existieren weder Aliase noch Markierungen mehr
- Test: `backend/tests/test_db_merge_aliases.py::test_delete_system_removes_aliases_and_dismissals`,
  `backend/tests/test_db_account_assignments.py::test_delete_system_removes_assignments_targeting_it_and_owned_by_its_accounts`

#### Szenario: Verlauf verschwindet
- **WENN** ein Gerät mit Konfigurationsversion, Fehler- und Monitor-Ereignis gelöscht wird
- **DANN** bleiben davon keine Zeilen zurück; die eines anderen Geräts bleiben
- Test: `backend/tests/test_db_merge_aliases.py::test_delete_system_removes_history_rows`

#### Szenario: Unbekannte ID
- **WENN** ein ADMIN ein unbekanntes Gerät löscht
- **DANN** antwortet die API mit 404
- Test: `backend/tests/test_main_systems_delete.py::test_delete_unknown_id_is_404`

#### Szenario: Zugänge nur auf ausdrücklichen Wunsch
- **WENN** ein Gerät mit Zugang ohne bzw. mit `withAccounts=false` gelöscht wird
- **DANN** antwortet die API mit 409 und nennt die Anzahl; Gerät und Zugang bleiben
- **WENN** `?withAccounts=true` gesendet wird
- **DANN** sind Gerät und Zugang gelöscht
- Test: `backend/tests/test_main_systems_delete.py::test_delete_with_accounts_needs_parameter`,
  `backend/tests/test_main_systems_delete.py::test_delete_with_accounts_parameter_removes_both`,
  `backend/tests/test_main_systems_delete.py::test_delete_without_accounts_needs_no_parameter`

Quelle: `backend/app/main.py:578`, `backend/app/db.py:692`

### Requirement: Duplikat-Vorschläge
Das System MUSS ADMIN Paare möglicher Duplikate vorschlagen, nie selbst zusammenführen. Grund
`hostname`: gleicher erster DNS-Label des Hostnamens (ohne Groß/Klein; reine IP-Hostnamen zählen
nicht). Grund `selfName`: gleicher selbstgemeldeter Name (UPnP `friendlyName` oder mDNS-Name, ohne
Groß/Klein, getrimmt). Hersteller/Modell sind kein Grund. Ein Schlüssel, den mehr als 3 Geräte
teilen, gilt als generisch und wird ignoriert. Ein Paar erscheint einmal mit allen Gründen
(`{aId, bId, aName, bName, reasons}`, `aId < bId`); markierte Paare fehlen. **[Muss]**

#### Szenario: Gleicher Hostname
- **WENN** „Router.fritz.box" und „router" existieren, plus zwei Geräte mit Hostname „10.0.0.1"
- **DANN** gibt es genau einen Vorschlag mit Grund `hostname`
- Test: `backend/tests/test_db_duplicates.py::test_same_hostname_flagged`

#### Szenario: Baugleiche Geräte
- **WENN** zwei Geräte gleichen Hersteller und gleiches Modell haben
- **DANN** gibt es keinen Vorschlag
- Test: `backend/tests/test_db_duplicates.py::test_identical_vendor_and_model_not_flagged`

#### Szenario: Generischer Name
- **WENN** vier Geräte Hostname „espressif" tragen
- **DANN** gibt es keinen Vorschlag; bei drei Geräten mit gleichem Namen gibt es 3 Paare
- Test: `backend/tests/test_db_duplicates.py::test_generic_name_shared_by_many_not_flagged`,
  `backend/tests/test_db_duplicates.py::test_three_devices_same_hostname_give_three_pairs`

Weitere Tests: `test_db_duplicates.py::test_self_reported_name_flagged`,
`::test_pair_with_several_reasons_is_one_entry`, `::test_same_vendor_only_not_flagged`,
`::test_merged_pair_no_longer_suggested`, `test_main_duplicates_api.py::test_duplicates_route_not_shadowed`.

Quelle: `backend/app/main.py:522`, `backend/app/db.py:897`, `backend/app/db.py:916`, `backend/app/db.py:925`, `backend/app/db.py:928`

### Requirement: „Kein Duplikat" markieren
Das System MUSS ADMIN erlauben, ein Paar dauerhaft (auch über künftige Scans) als „kein Duplikat"
zu markieren. Die Markierung ist richtungsunabhängig und idempotent. Fehlt `otherId` oder ist es
die eigene ID → 400; existiert eines der Geräte nicht → 404. **[Muss]**

#### Szenario: Validierung und Wirkung
- **WENN** `otherId` fehlt / gleich der eigenen ID / unbekannt / gültig ist
- **DANN** 400 / 400 / 404 / `{"ok": true}` und der Vorschlag verschwindet
- Test: `backend/tests/test_main_duplicates_api.py::test_not_duplicate_endpoint`,
  `backend/tests/test_db_duplicates.py::test_dismissed_pair_not_suggested_after_rescan`

Quelle: `backend/app/main.py:535`, `backend/app/db.py:963`

### Requirement: Zusammenführen
Das System MUSS ADMIN erlauben, ein Gerät (`removeId`) in ein anderes (Pfad-ID, „behalten")
zusammenzuführen; nur auf ausdrückliche Anforderung, nicht umkehrbar. Regeln:
- Bei Konflikten gewinnt das behaltene Gerät; leere Felder `ip, hostname, mac, vendor, model, os,
  location, purpose, descriptionMd, url, docUrl, docLink, notes` werden vom entfernten gefüllt.
- Quellspezifische Gerätedetails (`extra`) werden vereinigt, verschachtelte Objekte (z. B.
  Probe-Ergebnisse je Ziel) eine Ebene tief; offene Ports und Dienste werden je Adresse
  (`extra.interfaces`) geführt und als Vereinigung angezeigt.
- War das behaltene Gerät Kind des entfernten, übernimmt es dessen Elterngerät (sonst `null`), nie
  sich selbst; Kinder des entfernten hängen danach am behaltenen.
  Test: `backend/tests/test_db_merge_aliases.py::test_merge_keep_child_of_removed_gets_removed_parent`,
  `backend/tests/test_db_merge_aliases.py::test_merge_keep_child_of_removed_gets_null_without_grandparent`
- `importance` des entfernten wird übernommen, solange das behaltene nicht bestätigt ist;
  `confirmed` und `monitored` (+ `monitorPorts`) werden übernommen, wenn das behaltene sie nicht hat.
- Zugänge, Zuordnungsregeln, Überwachungsereignisse, Konfigurationsversionen, Fehlerereignisse,
  Kinder und Aliase des entfernten wandern zum behaltenen; danach wird das entfernte gelöscht.
- `removeId` fehlt → 400 „removeId fehlt."; gleich der Pfad-ID → 400; eines unbekannt → 404.
**[Muss]**

#### Szenario: Historie bleibt erhalten
- **WENN** B mit Zugang, Überwachungs- und Fehlerereignis in A zusammengeführt wird
- **DANN** hängen Zugang und beide Ereignisse an A
- Test: `backend/tests/test_db_merge_aliases.py::test_merge_keeps_accounts_and_history`

#### Szenario: Ports und Gerätedetails
- **WENN** ein Handeintrag mit einem gescannten Eintrag (UniFi-Daten, Ports 22/443) verschmilzt
- **DANN** trägt das Ergebnis UniFi-Daten, beide Probe-Einträge, Ports `[22, 443]` und zwei Interfaces
- Test: `backend/tests/test_db_merge_aliases.py::test_merge_keeps_extra_ports_and_services_of_removed_row`,
  `::test_merge_same_ip_unites_ports`

Quelle: `backend/app/main.py:584`, `backend/app/db.py:799`, `backend/app/db.py:831`, `backend/app/db.py:849`, `backend/app/db.py:853`

### Requirement: Aliase machen das Zusammenführen dauerhaft
Das System MUSS beim Zusammenführen Discovery-Schlüssel und MAC des entfernten Geräts (mit der dort
gesehenen IP) als Aliase des behaltenen speichern (kein leerer Alias, keiner gleich dem eigenen
Schlüssel/der eigenen MAC). Spätere Scans, die einen Alias finden, MÜSSEN das behaltene Gerät
aktualisieren statt ein neues anzulegen; dabei bleiben dessen Schlüssel/IP/MAC unverändert, die
Alias-IP wird nachgeführt, nur die Ports dieser Adresse werden ersetzt. Aliase sind transitiv. ADMIN
kann die Aliase eines Geräts abrufen (`aliasKey, ip, mac, createdAt`; unbekanntes Gerät → 404). **[Muss]**

#### Szenario: Erneuter Scan
- **WENN** nach dem Zusammenführen der Schlüssel des entfernten Geräts wieder gefunden wird
- **DANN** entsteht kein neues Gerät und die Alias-IP wird aktualisiert
- Test: `backend/tests/test_db_merge_aliases.py::test_rescan_with_alias_key_does_not_recreate`,
  `::test_rescan_with_alias_updates_alias_ip`, `::test_rescan_with_only_alias_mac_does_not_duplicate`,
  `::test_transitive_aliases_survive_second_merge`, `::test_merge_records_aliases`,
  `::test_merge_without_discovery_key_adds_no_empty_alias`, `::test_rescan_of_each_interface_keeps_the_others_ports`,
  `test_main_duplicates_api.py::test_aliases_endpoint`

Quelle: `backend/app/main.py:528`, `backend/app/db.py:799`, `backend/app/db.py:970`, `backend/app/db.py:1133`

### Requirement: Eindeutige Namen pro Scan
Das System MUSS gleichnamige, aber verschiedene Funde eines Scans unterscheidbar benennen:
Nicht-Container erhalten das letzte IP-Oktett als Suffix (`Shelly (5)`; bei Kollision `(5-2)`),
Container (teilen die Host-IP) nur bei exakt gleichem Namen einen Zähler ab dem zweiten
(`web · app (2)`); eindeutige Namen bleiben unverändert. **[Muss]** (Suffixformat **[Impl]**)

#### Szenario: Container und Geräte
- **WENN** zwei Shelly mit IP .5/.6 und zwei Container „web · app" gefunden werden
- **DANN** heißen sie „Shelly (5)", „Shelly (6)", „web · app", „web · app (2)"
- Test: `backend/tests/test_pipeline_unique_names.py::test_non_containers_get_octet_suffix`,
  `::test_identical_container_names_get_counter_not_octet`, `::test_distinct_container_names_untouched`,
  `::test_container_without_ip_does_not_crash`

Quelle: `backend/app/pipeline.py:307`, `backend/app/pipeline.py:478`

### Requirement: Fehlerereignisse je Gerät
Das System MUSS je Gerät die letzten 50 Fehlerereignisse (neueste zuerst; `id, systemId, level,
message, createdAt, acknowledgedAt`) liefern; unbekanntes Gerät → 404. Gespeichert werden höchstens 100 pro Gerät
(älteste fallen weg), Meldungen auf 2000 Zeichen gekürzt, `level` Default `error`. Ereignisse ohne
Gerätezuordnung werden verworfen. Ein Admin MUSS Ereignisse
quittieren können (`acknowledgedAt`, `NULL` = offen), einzeln oder alle eines Geräts; quittierte
Ereignisse bleiben als Verlauf erhalten (keine Löschfunktion), zählen aber nicht mehr in `errorCount`.
Erneutes Quittieren ändert den ersten Zeitstempel nicht (200); ein Ereignis eines anderen Geräts
oder unbekannte Ids → 404. Ein neu auftretender Fehler ist wieder offen. Die Kappung
trimmt unabhängig vom Quittierstatus. **[Muss]** (Grenzen **[Impl]**)

#### Szenario: Reihenfolge und Begrenzung
- **WENN** 10 Fehler bei Limit 3 gespeichert werden
- **DANN** bleiben die 3 neuesten, der neueste zuerst
- Test: `backend/tests/test_db_error_events.py::test_add_and_list_device_error_events`,
  `::test_error_events_are_capped_per_device`, `::test_add_device_error_event_is_a_noop_without_a_system_id`

Quelle: `backend/app/main.py:1420`, `backend/app/db.py:1741`, `backend/app/db.py:1744`, `backend/app/db.py:1766`;
Erzeuger: `backend/app/pipeline.py:92`, `backend/app/monitor.py:172`

#### Szenario: Quittieren
- **WENN** ein Admin ein Ereignis oder alle Ereignisse eines Geräts quittiert
- **DANN** verschwinden sie aus `errorCount` (Badge), bleiben aber in der Liste mit `acknowledgedAt`; MEMBER erhält 403
- Test: `backend/tests/test_db_error_events.py::test_acknowledge_single_event_sets_timestamp`,
  `::test_acknowledge_is_idempotent_and_keeps_first_timestamp`, `::test_acknowledge_all_only_touches_that_device`,
  `::test_count_ignores_acknowledged_and_new_event_counts_again`, `::test_cap_trims_regardless_of_acknowledged`,
  `::test_init_db_adds_column_to_legacy_table`, `backend/tests/test_main_error_ack.py::test_acknowledge_requires_admin`,
  `::test_event_of_other_system_is_404_and_untouched`, `::test_acknowledge_all_returns_count_and_zero_is_200`,
  `::test_systems_list_error_count_only_unacknowledged`

### Requirement: Geräteliste in der Oberfläche
Die Geräteliste MUSS Freitextsuche (Name, Hostname, IP, MAC, Hersteller, Modell, Standort, Zweck),
Filter nach Art, nach Host (`parentId`) und nach Compose-Projekt (URL-Parameter `kind`, `parentId`,
`project`; zusätzlich nach Netz, `subnet`) sowie Sortierung nach Name/Adresse (IPv4 numerisch)/Art/Standort/Zustand bieten.
Container mit Compose-Projekt (`extra.docker.composeProject`) werden je Projekt in einer
einklappbaren Gruppe („Compose: <projekt> (n Container)", alphabetisch) nach den übrigen Geräten
gezeigt; Suche/Sortierung wirken innerhalb der Gruppen. Badges: kritisch, Fehleranzahl, PoE
(Schlagwort enthält „poe"). ADMIN zusätzlich: Mehrfachauswahl mit Löschen, bei genau 2 Geräten
Zusammenführen mit Wahl des Behaltenen, Duplikat-Hinweise mit „Behalte X"/„Kein Duplikat". **[Muss]**
(Layout **[Impl]**)

#### Szenario: Compose-Gruppe
- **WENN** drei Container des Projekts „immich" und zwei Geräte ohne Projekt vorhanden sind
- **DANN** stehen die zwei Geräte oben, darunter eine Gruppe „Compose: immich (3 Container)"

Quelle: `frontend/src/pages/geraete/InventoryPage.tsx`, `frontend/src/pages/geraete/inventoryModel.ts`

### Requirement: Listenzustand in der URL
Suchtext und Sortierung der Geräteliste MÜSSEN in der URL stehen (`q`, `sort` = `name`/`ip`/`kind`/
`location`/`status`, absteigend mit `-` davor, ohne `sort` die Reihenfolge der API mit kritischen
Geräten zuerst), damit Zurück nach dem Öffnen eines Geräts, Neuladen und ein geteilter Link dieselbe
Liste zeigen. Zusätzlich zu `kind`, `parentId`, `project` MÜSSEN `status` (`online`/`offline`/
`unknown`), `importance` (`critical`/`normal`/`low`) und `subnet` (CIDR, `none` = Geräte ohne gültige
IPv4-Adresse) filtern; Aktive Filter ohne eigenes Bedienelement
stehen als Chips mit × und „Filter aufheben“.
**[Muss]**

#### Szenario: Suche überlebt Zurück
- **WENN** ein Benutzer „nas“ sucht, ein Gerät öffnet und Zurück drückt
- **DANN** steht „nas“ wieder im Suchfeld und die Liste ist gefiltert (`/geraete?q=nas`)

#### Szenario: Netz filtern
- **WENN** ein Benutzer „Netz“ auf ein Netz stellt
- **DANN** zeigt die Liste nur dessen Geräte, die URL enthält `?subnet=<CIDR>` und Neuladen sowie
  Zurück behalten den Filter

#### Szenario: Spaltenkopf sortiert
- **WENN** ein Benutzer dreimal auf „Adresse“ klickt
- **DANN** steht nacheinander `?sort=ip`, `?sort=-ip` und kein `sort` in der URL

#### Szenario: Wichtige Geräte von der Startseite
- **WENN** die Startseite „+2 weitere“ anzeigt und ein Benutzer darauf tippt
- **DANN** öffnet `/geraete?importance=critical` mit genau den kritischen Geräten

Quelle: `frontend/src/pages/geraete/inventoryModel.ts`, `frontend/src/pages/geraete/InventoryPage.tsx`,
`frontend/src/pages/start/StartPage.tsx`, `frontend/e2e/smoke.spec.ts`

### Requirement: Geräteliste (Ansicht `InventoryPage`)
Die Route `/geraete` MUSS die ruhige Liste `InventoryPage` zeigen (ohne Seitentitel und
Erklärabsatz; Skeleton beim Laden). Sie rechnet nur aus derselben `GET /api/systems`-Liste:
**[Muss]**
- Filterzeile „Alle N · Nicht erreichbar N · Wichtig N · Art ▾ · Netz ▾ · Compose ▾“; N zählt über das ganze
  Inventar (Alle = alle Geräte, Nicht erreichbar = `status = offline` aller Geräte, Wichtig =
  `importance = critical`), nicht über die gerade gefilterte Liste. Weitere aktive Filter (Host,
  andere Zustände/Bedeutungen) stehen als eigene Chips mit ×.
- Sortieren über ein sichtbares Menü **und** klickbare Spaltenköpfe (Gerät, Adresse, Art, Standort,
  Zustand; Klick: aufsteigend → absteigend → unsortiert), beide lesen und schreiben `?sort=`. Die
  aktive Spalte zeigt ▲/▼ und `aria-sort`. Das Menü hat für jeden Wert, den `sort` annehmen kann,
  einen Eintrag (auch absteigend). Auf dem Handy ist die Kopfzeile ausgeblendet, das Menü bleibt.
- Netz-Filter (Dropdown „Netz“, Einfachauswahl, `?subnet=`): das Netz eines Geräts wird aus seiner
  IPv4 berechnet – das engste passende UniFi-Netz (`facts.cidr` der Netz-Ressourcen, Option „Name
  (CIDR)“), sonst das /24 (nur CIDR); ohne gültige IPv4 „ohne Adresse“ (`subnet=none`). Angeboten
  werden nur belegte Netze mit Anzahl über das ganze Inventar, nach Netzadresse sortiert; bei
  weniger als zwei Netzen ohne aktiven Filter entfällt das Dropdown.
- Duplikat-Vorschläge (ADMIN) als Chip „N mögliche Duplikate“, der eine Prüfansicht öffnet
  (`?duplikate=1`) mit „Behalte A“ / „Behalte B“ / „Kein Duplikat“ je Paar.
- Unter 640 px Breite wird jede Zeile ein Listeneintrag (Name, IP · Art, Status-Chip), ohne seitliches
  Scrollen.
- Mehrfachauswahl (ADMIN) erst nach „Auswählen“; „Löschen …“ öffnet einen Prüfdialog, der die
  Namen der Geräte nennt, die Zahl der mitgelöschten Zugänge und der Container/VMs, die ihren Host
  verlieren, und dass es kein Rückgängig gibt. Zusammenführen (genau 2 ausgewählt) steht getrennt
  davon und hat einen eigenen Prüfdialog. Die Auswahl folgt der Ansicht: blenden Suche oder Filter
  ein ausgewähltes Gerät aus, ist es nicht mehr ausgewählt, damit „Löschen …“ nur sichtbare Geräte trifft.
- „+ Gerät“ (ADMIN) öffnet einen Dialog mit Name und Art; danach öffnet sich die Geräteseite des
  neuen Geräts.
- Eingeklappte Compose-Gruppen bleiben für den Browser-Tab eingeklappt (`sessionStorage`).

#### Szenario: Löschen prüfen
- **WENN** ein Admin zwei Geräte auswählt, von denen eines einen Zugang hat, und „Löschen …“ wählt
- **DANN** nennt der Dialog beide Namen und „1 hinterlegter Zugang wird mitgelöscht“; erst „2 Geräte
  löschen“ löscht; die UI sendet dabei `withAccounts=true`. Ein 404 (Gerät schon weg) zählt als erledigt,
  nicht als Fehler

Quelle: `frontend/src/pages/geraete/InventoryPage.tsx`, `frontend/src/pages/geraete/geraete.css`

### Requirement: Detailseite
Die Detailseite MUSS zeigen: Kopf (Name, Zweck, Zustand, kritisch, Fehleranzahl als Schalter zum
Fehlerprotokoll, PoE, überwacht mit Port/Ping, „automatisch gefunden", Links Weboberfläche /
Hersteller-Doku / eigene Doku), Beschreibung (eigene oder abgeleitet mit Hinweis) und Notiz,
technische Daten (IP, Hostname, MAC, Hersteller, Modell, Standort, zuletzt/erstmals gesehen,
Quelle; nur befüllte), je nach Daten: Container-Details, „Direkt vom Gerät ausgelesen", erreichbare Dienste (mit
Adressspalte bei mehreren Interfaces). ADMIN zusätzlich: Bearbeiten, Löschen, Auslesen,
Zusammenführen-Bereich („Weitere IPs/MACs", Duplikat-Hinweise, „Zusammenführen…") und
Zugänge. Es gibt keine Fernwartung (Neustart, Schalten, Konsolen, Container-Steuerung; ADR-0023). **[Impl]** (Inhalte fachlich **[Muss]**: Mitglieder sehen keine
Zugänge und keine Schreibaktionen)

#### Szenario: Mitglied
- **WENN** ein MEMBER die Detailseite öffnet
- **DANN** sieht er keine Buttons zum Bearbeiten/Löschen/Zusammenführen und keinen Bereich „Zugänge"

Quelle: `frontend/src/pages/device/DevicePage.tsx`

### Requirement: Detailseite in Tabs
`/geraete/:id` MUSS alle Inhalte und Aktionen der Detailseite zeigen, aufgeteilt auf Tabs in `?tab=` (`ueberblick`
Standard · `technik` · `verlauf` · `zugaenge`); für jede Rolle entfällt nichts, was sie
vorher erreichen konnte. Nur „Überblick“ trägt die
Zusammenfassung (Status, seit wann, Adresse, Quelle, Wichtigkeit/Überwachung) und genau eine
Hauptaktion: nicht erreichbar, live überwacht und ADMIN → „Jetzt neu prüfen“ (`POST /api/monitor/run`)
plus „Assistent fragen“; nicht erreichbar, aber nicht live überwacht (oder MEMBER) → „Assistent
fragen“ (ein Überwachungslauf prüft unbeobachtete Geräte gar nicht); sonst „Weboberfläche ↗“, falls
eine URL hinterlegt ist. Die Weboberfläche bleibt im ersten Fall als Nebenaktion erreichbar.
Wechselt die Seite direkt zu einem anderen Gerät, baut das Formular nur auf den Daten des Geräts aus
der URL auf, nie auf denen des vorherigen; die Seite wird dabei neu aufgebaut (`key` = Geräte-ID in
`App.tsx`), sodass angezeigte Passwörter und Seitenzustand nicht mitwandern. Der Status ist nur
„live“, wenn die Dauerüberwachung an ist und das Gerät beobachtet (`GET /api/monitor`), sonst „Stand
letzter Scan“ (dieselbe Regel wie die Startseite). „Zugänge“ gibt es nur für ADMIN
(Mitglieder sehen wie bisher keine Zugänge). Einen Tab „Steuern“ gibt es nicht mehr (ADR-0023);
`?tab=steuern` und jeder andere unbekannte Wert landen auf „Überblick“. Löschen und Zusammenführen liegen unter „⋯“ und
verlangen einen Prüfdialog; der Lösch-Dialog nennt die mitgelöschten, direkt zugeordneten Zugänge und
sagt, dass es kein Rückgängig gibt. Duplikat-Hinweise erscheinen nur, wenn es Kandidaten gibt.
Ein angezeigtes Passwort wird nach 30 s wieder verborgen. **[Muss]** (Aufteilung und Texte **[Impl]**)

#### Szenario: Tab bleibt beim Neuladen
- **WENN** jemand `/geraete/<id>?tab=technik` neu lädt
- **DANN** ist wieder der Tab „Technik“ offen

#### Szenario: Zurück überspringt die Tabs
- **WENN** jemand aus der Geräteliste (oder Netzplan, Suche) ein Gerät öffnet und mehrere Tabs wechselt
- **DANN** ersetzt jeder Tab-Wechsel den Verlaufseintrag, und Zurück (Kopf-Button und Browser) führt in einem
  Schritt dorthin zurück, wo das Gerät geöffnet wurde; bei Direktaufruf geht der Kopf-Button zur Geräteliste

#### Szenario: Passwort verbirgt sich
- **WENN** ein ADMIN im Tab „Zugänge“ „Passwort anzeigen“ klickt
- **DANN** ist das Passwort nach 30 s nicht mehr zu sehen

Quelle: `frontend/src/pages/device/DevicePage.tsx`, `frontend/src/pages/device/ZugaengeTab.tsx`,
`frontend/src/App.tsx`

### Requirement: Bearbeiten verliert keinen Entwurf
Die Oberfläche MUSS ungespeicherte Änderungen im Formular „Gerät bearbeiten“ im
`sessionStorage` des Tabs halten (Schlüssel `homeatlas.draft.device.form.<id>`, nur die Formularfelder)
und beim Verlassen per Link nachfragen; Zurück und Wiederkommen oder Neuladen stellt den Entwurf
wieder her. Speichern und Abbrechen entfernen ihn, Abmelden ebenfalls. Nach dem Zusammenführen
bleibt die Seite auf dem behaltenen Gerät und lädt es neu, ohne die ganze Seite neu zu laden. **[Muss]**

#### Szenario: Zurück und wieder hin
- **WENN** ein ADMIN den Standort ändert, Zurück drückt und wieder zur Seite geht
- **DANN** steht der geänderte Standort wieder im Formular

Quelle: `frontend/src/lib/deviceDraft.ts`, `frontend/src/components/DeviceEditForm.tsx`,
`frontend/src/pages/device/DevicePage.tsx`

## Daten

Aus [data-model](../../contracts/data-model.md):
- `systems`: gelesen und geschrieben (alle Felder; `confirmed`, `monitored` gezielt).
- `systemAliases`, `duplicateDismissals`: geschrieben bei Merge/Markierung, gelöscht bei Delete.
- `accounts`, `accountAssignments`: gelesen (Detail, Zähler), umgehängt (Merge), gelöscht (Delete).
- `deviceErrorEvents`, `monitorEvents`: gelesen, bei Merge umgehängt, bei Delete gelöscht.

## Schnittstellen

| Methode | Pfad | Rolle | Zweck |
|---|---|---|---|
| GET | /api/systems | MEMBER | Geräteliste (+`accountCount`, `errorCount`, `description`, `kindLabels`), Query `kind` |
| POST | /api/systems | ADMIN | Gerät anlegen → `{system}` |
| GET | /api/systems/duplicates | ADMIN | Duplikat-Vorschläge → `{candidates}` |
| GET | /api/systems/{system_id} | MEMBER | Detail → `{system, accounts, description, monitorPortsEffective}` |
| PATCH | /api/systems/{system_id} | ADMIN | Teil-Update → `{system}` |
| DELETE | /api/systems/{system_id}?withAccounts=false | ADMIN | Löschen → `{ok}`; 404 unbekannt; 409 bei Zugängen ohne `withAccounts=true` |
| GET | /api/systems/{system_id}/aliases | ADMIN | Aliase → `{aliases}` |
| POST | /api/systems/{system_id}/merge | ADMIN | Body `{removeId}` → `{system}` |
| POST | /api/systems/{system_id}/not-duplicate | ADMIN | Body `{otherId}` → `{ok}` |
| GET | /api/systems/{system_id}/errors | MEMBER | Fehlerereignisse → `{events}` |
| POST | /api/systems/{system_id}/errors/acknowledge | ADMIN | alle offenen quittieren → `{acknowledged}` |
| POST | /api/systems/{system_id}/errors/{event_id}/acknowledge | ADMIN | ein Ereignis quittieren → `{ok}` |
| GET | /api/systems/{system_id}/exposure | MEMBER | „Erreichbar über …“ → `{entries}` (aus gespeicherten Fakten, siehe [erreichbarkeit](../erreichbarkeit/spec.md)) |
| GET | /api/systems/{system_id}/admin-links | ADMIN | Absprung-Links nach Portainer/Proxmox → `{links}`, leer wenn keine zutreffen |

Berührte fremde Routen (nur verlinkt): Auslesen `POST /api/systems/{id}/probe`, KI-Einordnung `POST /api/systems/{system_id}/classify` ([klassifikation-llm](../klassifikation-llm/spec.md))
([credentialed-probing](../credentialed-probing/spec.md)), Zugänge ([zugangsdaten](../zugangsdaten/spec.md)).
LLM-Lesezugriff aufs Inventar: [llm-tools](../../contracts/llm-tools.md).

UI-Seite(n): `frontend/src/pages/geraete/InventoryPage.tsx` (Route `/geraete`),
`frontend/src/pages/device/DevicePage.tsx` (Route `/geraete/:id`).

## Nicht-Ziele und Grenzen

- Kein automatisches Zusammenführen aus Vorschlägen; einzige Ausnahme ist die Wiedererkennung beim
  Scan (Schlüssel, Alt-Schlüssel, Alias, MAC, Proxmox, IP+Hostname, Controller-IP), Requirement
  „Wiedererkennung bestehender Geräte“ in [discovery-und-scan](../discovery-und-scan/spec.md).
- Kein Rückgängigmachen eines Merges, kein Entfernen einzelner Aliase, kein Aufheben von
  „kein Duplikat".
- Keine Löschung von Fehlerereignissen (nur Quittieren), kein Bearbeiten oder Zurückspielen von
  Konfigurationsversionen.
- Keine serverseitige Suche/Paginierung; die Liste wird komplett geliefert und im Client gefiltert.

## Ist-Implementierung (nur Referenz, [Impl])

- IDs sind UUID-Hex; Zeitstempel als Text `YYYY-MM-DDTHH:MM:SSZ`; JSON-Felder als Text in SQLite.
- Eindeutigkeit über generierte Spalte `identityKey` (`discoveryKey` oder `id:<id>`), Unique-Index.
- Kein Fremdschlüssel in SQLite; Kaskaden bei Delete/Merge sind handgeschrieben.
- UI speichert beim Bearbeiten das gesamte Gerät als Patch (`setDraft(system)`), nicht nur Änderungen.
- Merge in der UI navigiert danach auf das behaltene Gerät und lädt dessen Daten neu (kein
  `window.location.reload()` mehr).

## OFFEN

- > OFFEN: `GET /api/systems/{id}` liefert MEMBER die Zugangs-Metadaten (Label, Benutzername, URL, Notizen) des Geräts; nur die UI blendet sie aus. Gewollt? → entschieden in #48: in Ordnung, solange keine Secrets
