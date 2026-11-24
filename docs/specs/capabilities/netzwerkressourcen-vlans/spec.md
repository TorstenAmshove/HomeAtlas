# Netzwerkressourcen und VLANs

> Status: Ist-Verhalten, aus dem Code zurückgewonnen (Stand 0159807). Quellen als `datei:zeile`.

## Zweck

Haushalte mit mehreren Netzen (Gäste-WLAN, IoT-VLAN) wollen sehen, welche Netze, WLANs und
Internet-Anschlüsse es gibt, ohne sich im Controller anzumelden. HomeAtlas übernimmt diese
Definitionen aus dem Netzwerk-Controller, hält sie aktuell und lässt pro Eintrag eine eigene Notiz
zu, die kein Abgleich überschreibt. Die übernommenen Netze dienen zusätzlich als Auswahl für den
Scan, als Abschnitt der Dokumentation und als genaue Subnetzgrenzen im Layer-3-Netzplan.

## Rollen und Rechte

| Aktion | ADMIN | MEMBER |
|---|---|---|
| Netzwerkressourcen lesen (Seite „Netze & WLAN“, `GET /api/network-resources`) | ja | ja |
| Notiz einer Ressource bearbeiten | ja | nein (403) |
| Technische Felder bearbeiten, Ressource anlegen oder löschen | nein (gibt es nicht) | nein |
| Abgleich mit dem Controller auslösen (Scan oder „Gerät auslesen“) | ja (fremde Routen) | nein |

Beide Routen setzen eine angemeldete Sitzung mit abgeschlossener TOTP-Einrichtung voraus (siehe
[auth-und-rollen](../auth-und-rollen/spec.md)).

## Anforderungen

### Requirement: Herkunft und Arten
Das System MUSS Netzwerkressourcen ausschließlich aus einem Controller-Abgleich übernehmen und genau
drei Arten kennen: `network` (Netz/VLAN), `wifi` (WLAN/SSID) und `wan` (Internet-Anschluss).
Einträge anderer Art oder ohne Standort-ID (Site) oder externe ID MÜSSEN verworfen werden. **[Muss]**

Heute liefert nur der UniFi-Controller Ressourcen; Discovery-Subnetze und Freitext-Netze
erzeugen keine Netzwerkressourcen. **[Impl]**

#### Szenario: Unbekannte Art wird ignoriert
- **WENN** ein Abgleich einen Eintrag mit Art `vpn` oder ohne `externalId` liefert
- **DANN** wird dafür keine Ressource gespeichert und kein Fehler gemeldet

Quelle: `backend/app/db.py:1259`, `backend/app/db.py:1309`, `backend/app/unifi_probe.py:128`,
`backend/app/unifi_probe.py:149`, `backend/app/unifi_probe.py:161`

### Requirement: Stabile Identität je Controller-Objekt
Das System MUSS eine Ressource über (Quelle, Controller-Zugang, Standort-ID, Art, externe ID)
identifizieren und bei jedem erneuten Abgleich denselben Datensatz (dieselbe ID) aktualisieren:
Name, Standortname, Eigentümer-Gerät, Aktiviert-Status und technische Fakten werden ersetzt, die
Ressource wird wieder aktiv, `lastSeen` aktualisiert, `firstSeen` bleibt. **[Muss]**

Ein fehlender Name wird durch die externe ID ersetzt (UniFi-Seite setzt vorher „Netzwerk“, „WLAN“
bzw. „Internet“ als Ersatz). **[Impl]**

#### Szenario: Umbenennung im Controller
- **WENN** ein Netz „IoT“ (VLAN 20, 192.168.20.0/24) im Controller zu „IoT und Sensoren“ mit
  10.20.0.0/23 geändert und erneut abgeglichen wird
- **DANN** behält die Ressource ihre ID, trägt den neuen Namen und die neuen Fakten und ist aktiv

Quelle: `backend/app/db.py:1262`, `backend/app/db.py:1311`, `backend/app/db.py:1318`,
Test: `backend/tests/test_db_network_resources.py::test_sync_network_resources_preserves_manual_note_while_refreshing_facts`

### Requirement: Lokale Notiz bleibt erhalten
Das System MUSS je Ressource eine lokale Notiz führen, die kein Controller-Abgleich verändert oder
leert. **[Muss]**

#### Szenario: Notiz übersteht Abgleich
- **WENN** ein ADMIN zur Ressource „IoT“ die Notiz „Nur fuer Geraete ohne Vertrauen.“ speichert und
  danach ein Abgleich die technischen Daten ändert
- **DANN** ist die Notiz unverändert vorhanden

Quelle: `backend/app/db.py:1318`, Test:
`backend/tests/test_db_network_resources.py::test_sync_network_resources_preserves_manual_note_while_refreshing_facts`

### Requirement: Verschwinden nur bei vollständig gelesenem Bereich
Das System MUSS eine Ressource nur dann als inaktiv markieren, wenn der Abgleich den zugehörigen
Bereich (Zugang + Standort + Art) vollständig gelesen hat und die Ressource darin fehlt. Ein
fehlgeschlagener oder nicht gelesener Bereich DARF bestehende Einträge NICHT deaktivieren.
Ressourcen werden nie physisch gelöscht. Ein vollständig gelesener, leerer Bereich deaktiviert seine
Ressourcen erst beim zweiten leeren Abgleich in Folge (`emptyScans`, schützt vor kurzzeitig leeren
Controller-Antworten); ein nicht gelesener Bereich lässt den Zähler unverändert, jede Aktualisierung
der Ressource setzt ihn auf 0. **[Muss]**

#### Szenario: Teilausfall löscht nichts
- **WENN** „LAN“ und „IoT“ bekannt sind und ein Abgleich nur „LAN“ liefert, ohne den Bereich
  (site-1, network) als vollständig zu melden
- **DANN** bleiben beide aktiv

#### Szenario: Leerer Bereich erst beim zweiten Mal
- **WENN** ein vollständig gelesener Bereich zum ersten Mal leer ist
- **DANN** bleiben seine Ressourcen aktiv; beim zweiten leeren Abgleich in Folge werden sie inaktiv

#### Szenario: Vollständiger Bereich ohne Eintrag
- **WENN** derselbe Abgleich den Bereich (site-1, network) als vollständig meldet
- **DANN** ist „LAN“ aktiv, „IoT“ inaktiv, beide behalten ihre ID

Quelle: `backend/app/db.py:1293`, `backend/app/db.py:1329`, `backend/app/unifi_probe.py:222`,
`backend/app/unifi_probe.py:229`, `backend/app/unifi_probe.py:236`, Test:
`backend/tests/test_db_network_resources.py::test_sync_network_resources_only_marks_missing_resource_inactive_for_completed_scope`

### Requirement: Löschen des Controller-Zugangs
Das System MUSS beim Löschen eines Zugangs alle von ihm stammenden Ressourcen behalten, aber als
inaktiv markieren; Notizen bleiben erhalten. **[Muss]**

#### Szenario: Zugang gelöscht
- **WENN** der UniFi-Zugang „UCG“ gelöscht wird
- **DANN** existiert die Ressource „LAN“ weiter mit `active = 0`

Quelle: `backend/app/db.py:1548`, Test:
`backend/tests/test_db_network_resources.py::test_delete_account_keeps_network_resource_and_marks_it_inactive`

### Requirement: Zeitpunkt des Abgleichs
Das System MUSS Ressourcen abgleichen (a) bei jedem vollständigen Scan für jeden UniFi-Zugang mit
„Zum Auslesen verwenden“, sofern die Quelle UniFi in den Einstellungen aktiv ist (`scanEnableUnifi`,
Default `true`), und (b) beim manuellen Auslesen eines Geräts, dem ein solcher UniFi-Zugang
freigegeben ist. Ein fehlgeschlagener Controller-Abruf DARF keine Ressource verändern. **[Muss]**

Im Scan erfolgt der Abgleich nach dem Inventar-Update und der Uplink-Verknüpfung (Fortschritt ab
87 %), Log-Zeile „UniFi (<Label>): <n> Netze, WLANs und WANs aktualisiert“. **[Impl]**

#### Szenario: Controller nicht erreichbar
- **WENN** der Controller beim Scan einen Verbindungsfehler liefert
- **DANN** erscheint eine Scan-Warnung „UniFi Controller (<Label>): …“, ein Fehlereintrag am
  zugeordneten Gerät, und alle Ressourcen bleiben unverändert

Quelle: `backend/app/pipeline.py:387`, `backend/app/pipeline.py:504`, `backend/app/main.py:1344`,
`backend/app/main.py:1377`

### Requirement: Übernommene Fakten
Das System MUSS mindestens folgende Fakten übernehmen. **[Muss]**

| Art | Felder |
|---|---|
| network | Name, Standortname, aktiviert, VLAN-ID, CIDR (normalisierte Netzadresse), Gateway-Adresse, DHCP-Bereich (`"<start> - <stop>"` oder leer), Management-Typ, Client-Isolation (bool) |
| wifi | Name, Standortname, aktiviert, Sicherheitstyp, Typ, externe ID und Name des zugehörigen Netzes (aus dem Netze-Block derselben Site; leer, wenn dieser fehlschlägt) |
| wan | Name, Standortname; aktiviert immer `true`, keine Fakten |

Eigentümer-Gerät (`ownerSystemId`) ist das Gerät, dem der UniFi-Zugang zugeordnet ist (kann leer
sein). Fehlt `enabled` in der Controller-Antwort, gilt die Ressource als deaktiviert. Ein CIDR, das
sich aus Adresse/Präfix nicht bilden lässt, wird als leerer String gespeichert. **[Impl]**

#### Szenario: Netz mit DHCP
- **WENN** der Controller ein Netz mit `hostIpAddress` 192.168.20.1, Präfix 24 und DHCP
  192.168.20.100–192.168.20.200 meldet
- **DANN** sind `cidr` = `192.168.20.0/24`, `gateway` = `192.168.20.1`,
  `dhcpRange` = `192.168.20.100 - 192.168.20.200`

Quelle: `backend/app/unifi_probe.py:128`, `backend/app/unifi_probe.py:149`,
`backend/app/unifi_probe.py:161`, `backend/app/unifi_probe.py:216`

### Requirement: Liste lesen
Das System MUSS jeder angemeldeten Rolle die Ressourcen liefern, optional gefiltert nach Art und
nach „nur aktive“. Ohne Filter werden auch inaktive Ressourcen geliefert. **[Muss]**

Sortierung: Standortname (ohne Groß/Klein), dann Art, dann Name (ohne Groß/Klein). Eine unbekannte
Art im Filter ergibt eine leere Liste (kein 422). **[Impl]**

#### Szenario: MEMBER liest
- **WENN** ein MEMBER `GET /api/network-resources?kind=network&activeOnly=true` aufruft
- **DANN** erhält er 200 mit `{"resources": [...]}` inklusive Notiz

Quelle: `backend/app/main.py:632`, `backend/app/db.py:1271`, Test:
`backend/tests/test_main_network_resources_api.py::test_network_resources_are_readable_by_members_and_manual_notes_require_an_admin`

### Requirement: Nur die Notiz ist bearbeitbar, nur durch ADMIN
Das System MUSS ADMINs erlauben, die Notiz einer Ressource zu setzen, und DARF über diese Route
keine anderen Felder ändern. MEMBER erhalten 403. Eine unbekannte ID ergibt 404 mit
„Netzwerkressource nicht gefunden.“. Antwort: `{"resource": <aktualisierte Ressource>}`. **[Muss]**

Ein Body ohne `manualMd` setzt die Notiz auf leer; die Notiz ist auf 2000 Zeichen
begrenzt (längere → 422). Jede erfolgreiche Änderung schreibt `networkresource.update` mit dem
Ressourcennamen (nicht dem Notiztext) ins Zugriffsprotokoll, auch bei unverändertem Text;
404 erzeugt keinen Eintrag. Entscheidung (#122): protokollieren, weil Notizen in Doku und
Assistenten-Kontext einfließen und eine Zeile billig ist. **[Impl]**

#### Szenario: Notiz setzen
- **WENN** ein ADMIN `PATCH /api/network-resources/<id>` mit `{"manualMd": "Nur IoT"}` sendet
- **DANN** antwortet das System 200 und die Ressource trägt `manualMd` = „Nur IoT“

#### Szenario: Unbekannte Ressource
- **WENN** ein ADMIN `PATCH /api/network-resources/missing` sendet
- **DANN** antwortet das System 404

Quelle: `backend/app/main.py:628`, `backend/app/main.py:638`, `backend/app/db.py:1286`, Tests:
`backend/tests/test_main_network_resources_api.py::test_network_resources_are_readable_by_members_and_manual_notes_require_an_admin`,
`backend/tests/test_main_network_resources_api.py::test_network_resource_manual_update_returns_404_for_unknown_resource`

### Requirement: Seite „Netze & WLAN“
Das System MUSS eine für alle Rollen sichtbare Seite bieten, die standardmäßig nur aktive Ressourcen in drei
Abschnitten zeigt: „Netze & VLANs“, „WLANs“, „Internet-Anschlüsse“ (leere Abschnitte entfallen).
Je Zeile: Name (Zusatz „(deaktiviert)“, wenn im Controller deaktiviert), Standort, Details, Notiz.
Details: Netz = CIDR · „VLAN <id>“; WLAN = Sicherheitstyp · Netzname. Die Schaltfläche „Bearbeiten“ erscheint
nur für ADMIN. Ohne Ressourcen: „Noch keine Controller-Daten. Lege unter Zugänge einen
UniFi-API-Key an und starte einen Scan.“ **[Muss]**

Die Notiz wird in einem mehrzeiligen Textfeld (max. 2000 Zeichen, mit Zähler) bearbeitet und als
Markdown gerendert (kein rohes HTML). Der Schalter „Inaktive anzeigen“ (Standard aus) blendet auch
nicht mehr im Controller vorhandene Ressourcen mit dem Hinweis „nicht mehr im Controller“ und ihrer
Notiz ein; ADMIN kann sie bearbeiten. **[Impl]**

#### Szenario: Deaktiviertes WLAN
- **WENN** ein aktives WLAN „Gast“ im Controller ausgeschaltet ist
- **DANN** steht es im Abschnitt „WLANs“ als „Gast (deaktiviert)“

Quelle: `frontend/src/pages/geraete/NetworksPage.tsx`, `frontend/src/lib/api.ts`

### Requirement: „Netze & WLAN“-Seite
Die Route `/netze` MUSS die Seite `NetworksPage` zeigen: kein Seitentitel, je Abschnitt
eine ruhige Liste (Name, Zusatz „deaktiviert“ bzw. „nicht mehr im Controller“, darunter Standort · Details, die Notiz als Markdown),
für ADMIN „Notiz hinzufügen“/„Notiz bearbeiten“ mit Speichern/Abbrechen, Skeleton beim Laden. Ohne
Ressourcen erklärt die Seite, dass die Einträge aus dem Netzwerk-Controller (UniFi) kommen und dafür
ein Zugang vom Typ „UniFi Network (API-Key)“ nötig ist; ADMIN bekommt „Zugang anlegen“ (`/zugaenge`)
und „Netzwerk scannen“ (`/scan`), MEMBER den Hinweis, dass ein Administrator den Zugang hinterlegt.
**[Muss]**

#### Szenario: Leere Seite für ein Mitglied
- **WENN** ein MEMBER `/netze` ohne Controller-Daten öffnet
- **DANN** liest er, dass ein Administrator unter „Zugänge“ einen UniFi-Zugang hinterlegen muss, und
  sieht keine Links zu Admin-Seiten

Quelle: `frontend/src/pages/geraete/NetworksPage.tsx`

### Requirement: Netze als Scan-Auswahl
Das System MUSS aktive, im Controller aktivierte Netze mit gültigem IPv4-CIDR als auswählbare
Scan-Netze anbieten; eine Auswahl, deren Ressource inaktiv, deaktiviert oder ohne CIDR ist, wird
ignoriert. Controller-Netze stehen vor Freitext-Netzen; gleiche CIDR werden nur einmal gescannt
(Controller-Eintrag gewinnt). Ist nichts gewählt und kein Freitext gesetzt, scannt das System die
Netze der eigenen Interfaces. Neu synchronisierte Netze sind nicht vorausgewählt und als „neu“
markiert. Details gehören zu [discovery-und-scan](../discovery-und-scan/spec.md) und
[einstellungen-und-llm-provider](../einstellungen-und-llm-provider/spec.md). **[Muss]**

#### Szenario: Inaktives Netz ausgewählt
- **WENN** die Auswahl `scanControllerNetworkIds` eine Ressource enthält, die inzwischen inaktiv ist
- **DANN** wird ihr CIDR nicht gescannt

Quelle: `backend/app/discovery.py:154`, `backend/app/discovery.py:190`, Tests:
`backend/tests/test_discovery_subnets.py::test_ignores_selected_networks_that_are_inactive_disabled_or_without_cidr`,
`backend/tests/test_discovery_subnets.py::test_selected_subnets_duplicate_keeps_controller_position`

### Requirement: Hinweis auf geroutete VLANs
Das System MUSS bei jedem Scan für jedes gescannte Netz, das nicht am eigenen Host anliegt, genau
eine Warnung ausgeben: „<CIDR> ist nur geroutet erreichbar: keine MAC/Hersteller, kein mDNS/SSDP.“,
ergänzt um „ Keine Adresse hat geantwortet.“ falls zutreffend, und den Verweis
„Siehe docs/multi-vlan.md“. Je Netz werden höchstens 1024 Adressen geprüft. Die Erklärseite
(Funktionsmatrix direkt vs. geroutet, Gateway-Einstellungen) MUSS Teil der Dokumentation sein. **[Muss]**

#### Szenario: IoT-VLAN über Gateway
- **WENN** der Host im 192.168.1.0/24 hängt und 192.168.20.0/24 gescannt wird
- **DANN** enthält der Scan-Log eine Warnung für 192.168.20.0/24, keine für 192.168.1.0/24

Quelle: `backend/app/discovery.py:44`, `backend/app/discovery.py:115`, `docs/multi-vlan.md`, Tests:
`backend/tests/test_discovery_subnets.py::test_routed_subnet_warnings_one_per_routed_subnet`,
`backend/tests/test_discovery_subnets.py::test_discover_warns_once_per_routed_subnet`

### Requirement: Weitere Verbraucher
Das System MUSS aktive Ressourcen in der generierten Netzwerk-Dokumentation als eigenen Abschnitt
„Vom Controller erfasste Netze“ (Tabellen je Art, inkl. Notiz) aufführen und aktive Netze mit CIDR,
VLAN-ID und Eigentümer-Gerät für den Layer-3-Netzplan bereitstellen. Inaktive Ressourcen erscheinen
dort nicht. **[Muss]**

#### Szenario: Dokumentation
- **WENN** ein aktives Netz „IoT“ (Standort „Haus“, VLAN 20, 192.168.20.0/24) existiert und die
  Doku neu erzeugt wird
- **DANN** enthält das Kapitel „netzwerk“ die Zeile `| IoT | Haus | 20 | 192.168.20.0/24 | - |`

Quelle: `backend/app/docs.py:380`, `backend/app/topology.py:676`, Test:
`backend/tests/test_docs_network_resources.py::test_network_documentation_includes_active_controller_resources`;
siehe [dokumentation](../dokumentation/spec.md), [topologie](../topologie/spec.md)

## Daten

Tabelle `networkResources` aus [data-model](../../contracts/data-model.md#networkresources--netze-wlans-wans-aus-controllern):
`id`, `kind`, `source`, `sourceKey` (eindeutig, `<source>:<accountId>:<siteId>:<kind>:<externalId>`),
`sourceAccountId` (→ `accounts`), `ownerSystemId` (→ `systems`, optional), `siteExternalId`,
`siteName`, `externalId`, `name`, `enabled`, `active`, `emptyScans`, `facts` (JSON), `manualMd`, `firstSeen`,
`lastSeen`, `updatedAt`. Geschrieben vom Abgleich (alles außer `manualMd`, `firstSeen`, `id`) und
von der Notiz-Route (`manualMd`, `updatedAt`); `accounts`-Löschung setzt `active = 0`.

Gelesene Settings (fremde Fähigkeiten, aber auf diese Daten bezogen): `scanEnableUnifi`,
`scanControllerNetworkIds`, `scanControllerNetworksSeen`, `scanSubnets`.

## Schnittstellen

| Methode | Pfad | Rolle | Zweck |
|---|---|---|---|
| GET | `/api/network-resources` | ADMIN, MEMBER | Liste; Query `kind` (`network`/`wifi`/`wan`), `activeOnly` (bool, Default `false`) |
| PATCH | `/api/network-resources/{resource_id}` | ADMIN | Notiz setzen; Body `{"manualMd": string}` (max. 2000 Zeichen) |

Berührte fremde Routen: `POST /api/scans` und `POST /api/systems/{system_id}/probe` lösen den
Abgleich aus ([discovery-und-scan](../discovery-und-scan/spec.md),
[credentialed-probing](../credentialed-probing/spec.md)); Zugangsverwaltung in
[zugangsdaten](../zugangsdaten/spec.md).

UI-Seite(n): `frontend/src/pages/geraete/NetworksPage.tsx` (Route `/netze`, Navigation „Netze & WLAN“, alle
Rollen). Scan-Netzauswahl in `frontend/src/pages/SettingsPage.tsx` (Route `/einstellungen`).

## Nicht-Ziele und Grenzen

- Keine Änderung von Netzen/WLANs im Controller; der UniFi-Zugriff ist ausschließlich lesend
  (feste GET-Endpunkte).
- Kein manuelles Anlegen oder Löschen von Ressourcen; Netze ohne Controller existieren nur als
  Scan-Freitext, nicht als Ressource.
- Kein Scanner-Agent je VLAN, keine Trunk-Konfiguration durch HomeAtlas (siehe
  `docs/multi-vlan.md`).
- Nur IPv4-CIDRs werden für Scan und Layer-3-Plan ausgewertet.
- Keine Ressourcen von Proxmox oder aus der Discovery.

## Ist-Implementierung (nur Referenz, [Impl])

- UniFi: lokale Integration-API unter `<url>/proxy/network/integration/v1`, Header `X-API-Key`,
  Timeout 15 s (Connect 5 s), TLS-Prüfung aus, Paging mit `limit=200` bis `totalCount`, je Netz ein
  Detailabruf (`/sites/{site}/networks/{id}`); fällt ein einziger Detailabruf aus, gilt der ganze
  Netz-Bereich des Standorts als nicht gelesen (`backend/app/unifi_probe.py:16`,
  `backend/app/unifi_probe.py:182`, `backend/app/unifi_probe.py:216`).
- Abgleich als Upsert per `ON CONFLICT(sourceKey)` in einer Transaktion
  (`backend/app/db.py:1318`).
- Frontend-Default `activeOnly = true` in `api.listNetworkResources`; die API selbst liefert ohne
  Parameter auch inaktive Einträge (`frontend/src/lib/api.ts:488`).

## OFFEN

- > OFFEN: Der manuelle Abgleich beim Verbindungstest (`backend/app/routes/systems.py:262`) nutzt dieselbe `sync_network_resources` und zählt `emptyScans` mit; zwei Klicks bei leer gemeldetem Bereich deaktivieren dessen Ressourcen also ebenso wie zwei Scans. Gewollt?
