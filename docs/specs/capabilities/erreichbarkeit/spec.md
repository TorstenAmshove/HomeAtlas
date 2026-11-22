# Erreichbarkeit von außen

> Status: neu (Issue #102, Teil 3 von 6: Datenmodell, Kettenlogik, Kapitel, Traefik, Datei-Quellen). Die weiteren Quellen
> (Caddy/cloudflared/ddclient, UniFi, Cloudflare, öffentliches DNS) folgen in den nächsten Teilen.

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

### Requirement: Traefik als Quelle
Das System MUSS die Routen eines internen Traefik per GET auf die festen Pfade `/api/http/routers`,
`/api/http/services` und `/api/entrypoints` lesen, nur mit einem Zugang der Kategorie `traefik` mit
`allowProbe` und solange `scanEnableTraefik` (Default an) gesetzt ist. Es speichert je Router nur Hosts,
Ziel-URL, Zertifikats-Resolver, Middleware-Namen und Entrypoints (nie Regel im Rohformat, Hashes,
Antwortkörper). Router ohne `Host(...)` werden ohne Host aufgeführt. **[Muss]**

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
Zugang der Kategorie `unifi_classic` (lokaler Benutzer „View Only“) mit `allowProbe` und solange
`scanEnableUnifiClassic` (Default an) gesetzt ist. Der einzige POST ist der Login (`/api/auth/login`);
danach nur GET auf `/self/sites`, `rest/portforward` und `stat/health`. Gespeichert werden je
Weiterleitung nur Protokoll, Ports, Ziel-IP und „aktiv“ (nie Name, Quellfilter, Passwort, Cookie, CSRF-Token),
und die WAN-IP als `wan`-Netzwerkressource. Ein erfolgreicher Lauf ohne Weiterleitungen zeigt
„keine Portweiterleitungen“; die WAN-Tabelle zeigt vorhandene Adressen statt leerer Zeilen. **[Muss]**

#### Szenario: Klassische API nicht lesbar
- **WENN** Login oder Abruf fehlschlägt
- **DANN** bleiben die alten Fakten als veraltet erhalten, ein Geräte-Fehler-Event entsteht am System des Zugangs und die übrigen Quellen laufen weiter

#### Szenario: Opt-in entfällt
- **WENN** `allowProbe` oder `scanEnableUnifiClassic` abgeschaltet wird
- **DANN** werden die Portweiterleitungs-Fakten beim nächsten Scan gelöscht

Quelle: `backend/app/unifi_classic_probe.py`, `backend/app/pipeline.py`, Test: `backend/tests/test_unifi_classic_probe.py`, `backend/tests/test_exposure_boundaries.py`

### Requirement: Datei-Quellen per Forced-Command
Das System MUSS die Konfiguration von cloudflared (Ingress), Caddy (Site-Blöcke, Client-Zertifikat ja/nein)
und ddclient (Protokoll, Server, Hostnamen, IPv4/IPv6) per SSH lesen, nur mit einem Zugang der Kategorie
`exposure_cloudflared`, `exposure_caddy` bzw. `exposure_ddclient` mit `allowProbe` und solange
`scanEnableExposureFiles` (Default an) gesetzt ist. Je Quelltyp gibt es genau einen festen Befehl
(`_FILE_COMMANDS`, ohne Pfad, Interpolation oder Parameter); die Datei bestimmt allein das Zielsystem über
`authorized_keys` (`command=`). Die Parser behalten nur Hostnamen, Ziele, Anbieter und Schalter; Passwörter,
Tokens, Tunnel-Zugangsdaten und Rohdateien werden verworfen, Fehlertexte enthalten nie Dateiinhalt. Die
Ausgabe ist auf 256 KB begrenzt, ein `import` anderer Dateien wird nicht verfolgt. **[Muss]**

#### Szenario: Eine Quelle fällt aus
- **WENN** eine Datei-Quelle nicht lesbar ist
- **DANN** bleiben ihre alten Fakten als veraltet erhalten, am Zielsystem entsteht ein Geräte-Fehler-Event und die übrigen Quellen laufen weiter

#### Szenario: Opt-in entfällt
- **WENN** `allowProbe` oder `scanEnableExposureFiles` abgeschaltet wird
- **DANN** werden die Fakten dieser Quellen beim nächsten Scan gelöscht

Quelle: `backend/app/exposure_files.py`, `backend/app/pipeline.py`, Test: `backend/tests/test_exposure_files.py`, `backend/tests/test_exposure_boundaries.py`
