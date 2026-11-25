# Erreichbarkeit von außen

> Status: neu (Issue #102, Teil 5 von 6: Datenmodell, Kettenlogik, Kapitel, Traefik, Datei-Quellen, UniFi, Cloudflare,
> öffentliches DNS, DynDNS-Container). Das Assistenten-Werkzeug und die Systemseite folgen im letzten Teil.

## Zweck

Haushalt und Admin sollen sehen, welche Dienste aus dem Internet und welche intern per TLS erreichbar
sind und über welchen Weg, und wo Konfiguration und Wirklichkeit auseinanderlaufen (z. B. ein alter
Proxy-Pfad neben dem Tunnel).

## Rollen und Rechte

| Aktion | ADMIN | MEMBER |
|---|---|---|
| Kapitel `erreichbarkeit` lesen (Hostnamen, WAN-IP) | ja | ja |

## Anforderungen

### Requirement: Fakten statt Rohdaten
Das System MUSS Erreichbarkeits-Fakten in der Tabelle `exposureFacts` nur mit den nicht geheimen,
je Art festen Feldern speichern; Rohdateien und Rohantworten werden nicht gespeichert. **[Muss]**

#### Szenario: Quelle fällt aus
- **WENN** das Lesen einer Quelle fehlschlägt
- **DANN** bleiben ihre Fakten erhalten und sind als veraltet (`stale`) markiert; ersetzt wird nur nach erfolgreichem Lesen

Quelle: `backend/app/db/exposure.py`, Test: `backend/tests/test_db_exposure.py`

### Requirement: Ketten und Pfadstatus
Das System MUSS je öffentlichem Hostnamen jeden konfigurierten Pfad mit Status *aktiv*, *verwaist*
oder *unklar* ausweisen und Ziele über IP und Docker-Portzuordnung dem Inventar zuordnen. Fehlende
Datenlage ergibt *unklar*, nie *verwaist*. Die Kettenlogik ist rein (kein Netz, keine DB). **[Muss]**

#### Szenario: Doppelter Pfad
- **WENN** ein Hostname im Caddyfile und im Tunnel-Ingress steht und DNS auf den Tunnel zeigt
- **DANN** ist der Tunnel *aktiv*, der Caddy-Pfad *verwaist* mit festem Empfehlungstext

Quelle: `backend/app/exposure.py`, Test: `backend/tests/test_exposure_chain.py`

### Requirement: Kapitel
Das System MUSS das Kapitel `erreichbarkeit` erzeugen, bei fehlenden Quellen mit Leerzustand, und
Texte aus Fremdquellen escapen und kürzen. **[Muss]**

Quelle: `backend/app/docs.py`, Test: `backend/tests/test_docs_exposure.py`

### Requirement: Firewall-Ergebnis je Schritt
Die Ketten MÜSSEN je Schritt das Firewall-Ergebnis (erlaubt/blockiert/unklar) tragen, in Kapitel und Werkzeug `list_exposure`. Siehe [firewall](../firewall/spec.md). **[Muss]**

### Requirement: Traefik als Quelle
Das System MUSS die Routen eines internen Traefik per GET auf die festen Pfade `/api/http/routers`,
`/api/http/services` und `/api/entrypoints` lesen, nur mit einem Zugang der Kategorie `traefik` mit
`allowProbe` und solange `scanEnableTraefik` (Default an) gesetzt ist. Es speichert je Router nur Hosts,
Ziel-URL, Zertifikats-Resolver, Middleware-Namen und Entrypoints (nie Regel im Rohformat, Hashes,
Antwortkörper). Router ohne `Host(...)` werden ohne Host aufgeführt. Ein TLS-Router ohne eigenen Resolver
erscheint als „TLS, Standardzertifikat“. Ziele auf einem Docker-Netz werden über die Netzadresse des
Containers dem Inventar zugeordnet. **[Muss]**

#### Szenario: Traefik nicht lesbar
- **WENN** die Traefik-API fehlschlägt
- **DANN** bleiben die alten Fakten als veraltet erhalten, ein Geräte-Fehler-Event entsteht am System des Zugangs und die übrigen Quellen laufen weiter

#### Szenario: Opt-in entfällt
- **WENN** `allowProbe` oder `scanEnableTraefik` abgeschaltet wird
- **DANN** werden die Traefik-Fakten beim nächsten Scan gelöscht

Quelle: `backend/app/traefik_probe.py`, `backend/app/pipeline.py`, Test: `backend/tests/test_traefik_probe.py`, `backend/tests/test_exposure_boundaries.py`

### Requirement: UniFi-Portweiterleitungen und WAN-Adresse
Das System MUSS Portweiterleitungen und die WAN-IP über die klassische UniFi-API lesen, weil die
Integration-API weder Portweiterleitungen noch eine WAN-Adresse liefert. Das geschieht nur mit einem
Zugang der Kategorie `unifi` (API-Key) mit `allowProbe` und solange `scanEnableUnifiClassic`
(Default an) gesetzt ist ([ADR-0018](../../../adr/0018-wan-status-und-lesepfade.md)). Es gibt keinen
Login: nur GET mit `X-API-Key` auf `/self/sites`, `rest/portforward`, `rest/networkconf` und `stat/device`
(per [ADR-0025](../../../adr/0025-unifi-scan-client-port-und-port-vlans.md) künftig zusätzlich `stat/sta` und `rest/portconf`, Umsetzung in Folge-Issue),
ohne Cookie, CSRF-Token und ohne Weiterleitungen. Ein früherer Zugang `unifi_classic` wird bei der Migration gelöscht. Gespeichert werden je
Weiterleitung nur Protokoll, Ports, Ziel-IP und „aktiv“ (nie Name, Quellfilter, Key). Die WAN-Zeilen werden
über den Namen zugeordnet; nur der aktive Anschluss bekommt eine Adresse. Rangfolge der öffentlichen Adresse:
WAN-Schnittstelle, FRITZ!Box, zuletzt `geo_info` (mit Hinweis, weil sie veralten kann). Aus `networkconf` bleiben nur Name, Zweck, Gruppe und Typ. Eine FRITZ!Box mit freigegebenem Zugang
liefert zusätzlich ihre öffentliche Adresse per `GetExternalIPAddress`, ohne Zugangsdaten; ohne FRITZ!Box entfällt
das. Ein erfolgreicher Lauf ohne Weiterleitungen zeigt „keine Portweiterleitungen“; die WAN-Tabelle zeigt vorhandene
Adressen statt leerer Zeilen. **[Muss]**

#### Szenario: UCG hinter einem Router
- **WENN** die WAN-Schnittstelle eine private Adresse hat
- **DANN** nutzt der DNS-Abgleich die Adresse der FRITZ!Box, ohne FRITZ!Box die Standortadresse von UniFi mit Hinweis

#### Szenario: Hostname zeigt direkt auf den Anschluss
- **WENN** ein Hostname (Cloudflare-Eintrag oder DynDNS) öffentlich auf die WAN-Adresse auflöst und kein Tunnel- oder Proxy-Pfad dafür bekannt ist
- **DANN** steht er unter „Direkt über den Internetanschluss erreichbar“ mit den aktiven Portweiterleitungen; ohne Weiterleitung ist er „verwaist“, ohne gelesene Weiterleitungen „unklar“

#### Szenario: Klassische API nicht lesbar
- **WENN** der Abruf fehlschlägt (Key abgelehnt, Endpunkt nicht verfügbar, Timeout)
- **DANN** bleiben die alten Fakten als veraltet erhalten, ein Geräte-Fehler-Event entsteht am System des Zugangs und die übrigen Quellen laufen weiter

#### Szenario: Opt-in entfällt
- **WENN** `allowProbe` oder `scanEnableUnifiClassic` abgeschaltet wird
- **DANN** werden die Portweiterleitungs-Fakten beim nächsten Scan gelöscht

Quelle: `backend/app/unifi_classic_probe.py`, `backend/app/pipeline.py`, Test: `backend/tests/test_unifi_classic_probe.py`, `backend/tests/test_pipeline_unifi_classic.py`, `backend/tests/test_exposure_boundaries.py`

### Requirement: Datei-Quellen per Forced-Command
Das System MUSS die Konfiguration von cloudflared (Ingress), Caddy (Site-Blöcke, Client-Zertifikat ja/nein)
und ddclient (Protokoll, Server, Hostnamen, IPv4/IPv6) per SSH lesen, nur mit einem Zugang der Kategorie
`exposure_cloudflared`, `exposure_caddy` bzw. `exposure_ddclient` mit `allowProbe` und solange
`scanEnableExposureFiles` (Default an) gesetzt ist. Je Quelltyp gibt es genau einen festen Befehl
(`_FILE_COMMANDS`, ohne Pfad, Interpolation oder Parameter); die Datei bestimmt allein das Zielsystem über
`authorized_keys` (`command=`). Die Parser behalten nur Hostnamen, Ziele, Anbieter und Schalter; Passwörter,
Tokens, Tunnel-Zugangsdaten und Rohdateien werden verworfen, Fehlertexte enthalten nie Dateiinhalt. Die
Ausgabe ist auf 256 KB begrenzt, ein `import` anderer Dateien wird nicht verfolgt. Das Zugangsformular
nimmt den privaten Schlüssel dieser Kategorien mehrzeilig entgegen, samt optionaler Passphrase. **[Muss]**

#### Szenario: Schlüssel eintragen
- **WENN** ein Admin einen privaten SSH-Schlüssel in einen Zugang dieser Kategorien einfügt
- **DANN** bleiben die Zeilenumbrüche erhalten und der Schlüssel ist beim Scan lesbar

#### Szenario: Eine Quelle fällt aus
- **WENN** eine Datei-Quelle nicht lesbar ist
- **DANN** bleiben ihre alten Fakten als veraltet erhalten, am Zielsystem entsteht ein Geräte-Fehler-Event und die übrigen Quellen laufen weiter

#### Szenario: Opt-in entfällt
- **WENN** `allowProbe` oder `scanEnableExposureFiles` abgeschaltet wird
- **DANN** werden die Fakten dieser Quellen beim nächsten Scan gelöscht

Quelle: `backend/app/exposure_files.py`, `backend/app/pipeline.py`, Test: `backend/tests/test_exposure_files.py`, `backend/tests/test_exposure_boundaries.py`

### Requirement: Cloudflare, öffentliches DNS und DynDNS-Container
Das System MUSS Cloudflare-DNS-Einträge, Tunnel-Status und mTLS-WAF-Regeln (nur der Ausdruck) per GET lesen und
öffentliche Hostnamen über einen festen DoH-Resolver auflösen, beides nur mit Schalter (`scanEnableCloudflare`,
`scanEnablePublicDns`, Standard **aus**) und `allowProbe`-Zugang (Kategorie `cloudflare`: Adresse = Zone-ID,
Benutzername = Account-ID, Geheimnis = Token). Das Tunnel-Token wird nie abgerufen; das öffentliche DNS fragt nur
validierte Hostnamen ohne Wildcards, höchstens 200 Abfragen je Scan. DynDNS-Container werden am Image erkannt
(feste Liste); die Hostnamen kommen aus dem Label `homeatlas.ddns.hosts` des Containers (kommagetrennt, validiert,
höchstens 20), der IPv6-Schalter aus `homeatlas.ddns.ipv6` (Standard: nur bei Cloudflare an). Die Container-Umgebung
wird nie gelesen (kein Inspect, ADR-0024); ohne Label bleibt die Hostliste leer. Sind Tunnel-Status oder
WAF-Regeln nicht lesbar, läuft der Scan weiter und meldet das als Warnung. **[Muss]**

#### Szenario: WAF-Regeln nicht lesbar
- **WENN** Cloudflare die WAF-Regeln nicht liefert
- **DANN** nennt der Scan eine Warnung „mTLS unbekannt“, statt still so zu tun, als gäbe es keine Regel

#### Szenario: Schalter aus
- **WENN** `scanEnableCloudflare` oder `scanEnablePublicDns` aus ist (Standard)
- **DANN** erfolgt kein Aufruf nach außen, bereits gespeicherte Fakten dieser Quelle werden gelöscht und das Kapitel nennt den Pfadstatus „unklar“

#### Szenario: Extern gehosteter Hostname
- **WENN** ein Cloudflare-Eintrag weder auf die WAN-IP noch in einen Tunnel führt und kein Pfad dafür konfiguriert ist
- **DANN** steht er im Abschnitt „Extern gehostet“ (Ziel, Reverse-DNS-Anbieterlabel) ohne Kette und ohne Warnung; ohne WAN-IP bleibt er unklar

#### Szenario: Tunnel nicht verbunden
- **WENN** die Cloudflare-Tunnel-API den Tunnel eines DNS-Eintrags als `down`/`inactive` meldet
- **DANN** erscheint ein Hinweis

Quelle: `backend/app/cloudflare_probe.py`, `backend/app/public_dns.py`, `backend/app/docker_probe.py`, `backend/app/exposure.py`, Test: `backend/tests/test_cloudflare_probe.py`, `backend/tests/test_public_dns.py`, `backend/tests/test_exposure_dyndns.py`, `backend/tests/test_exposure_secrets.py`

### Requirement: Assistent-Werkzeug und Systemseite
Das System MUSS `list_exposure` (nur lesend, nur aus gespeicherten Fakten, ohne Live-DNS, begrenzt mit
Kürzungshinweis, ohne Geheimnisse und Quell-Zugangs-IDs) für ADMIN, MEMBER und Assistent bereitstellen.
`tools.py` DARF aus den Erreichbarkeits-Modulen nur `exposure` importieren (ADR-0014). Die Systemseite
(Tab „Technik“) MUSS über `GET /api/systems/{id}/exposure` „Erreichbar über …“ zeigen, wenn das System
Ziel einer Kette, einer Traefik-Route oder einer Portweiterleitung ist. **[Muss]**

#### Szenario: Frage nach einem Hostnamen
- **WENN** der Assistent `list_exposure` mit `host` aufruft
- **DANN** enthält die Antwort nur Ketten, interne Routen und Extern-Zeilen zu diesem Host
