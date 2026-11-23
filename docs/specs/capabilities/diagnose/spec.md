# Diagnose (Live-Netzwerkprüfungen)

> Status: Ist-Verhalten, aus dem Code zurückgewonnen (Stand 0159807). Quellen als `datei:zeile`.

## Zweck

Wenn „das Internet nicht geht“ oder ein Gerät nicht antwortet, sollen auch Laien im Haushalt
herausfinden, *wo* es klemmt: Internet, Namensauflösung, Router oder ein einzelnes Gerät. Die
Prüfungen laufen live vom HomeAtlas-Server aus, sind streng lesend, zeitlich begrenzt und
liefern zu jedem Ergebnis eine Erklärung in verständlichem Deutsch. Dieselben Prüfungen (außer
Speedtest) nutzt der Assistent.

## Rollen und Rechte

| Aktion | ADMIN | MEMBER |
|---|---|---|
| Einzelprüfung (Internet, Ping, Port, DNS-Lookup, HTTP, Traceroute) | ja | ja |
| DNS-Gesamtprüfung | ja | ja |
| Speedtest | ja | ja |
| Prüfnamen für DNS-Gesamtprüfung festlegen (Einstellungen) | ja | nein |

## Anforderungen

### Requirement: Für alle angemeldeten Rollen
Das System MUSS alle Diagnose-Routen jedem angemeldeten Benutzer mit abgeschlossener TOTP-Einrichtung (ADMIN und MEMBER) anbieten; nicht angemeldete Aufrufe werden abgewiesen. **[Muss]**

#### Szenario: MEMBER prüft das Internet
- **WENN** ein MEMBER `POST /api/diagnostics` mit `{"tool":"internet_check"}` aufruft
- **DANN** erhält er `{"result": {...}}`

Quelle: `backend/app/main.py:1468`, `backend/app/main.py:1595`, `backend/app/main.py:1602`

### Requirement: Nur lesend und ohne Shell
Das System MUSS Diagnosen streng lesend ausführen: keine Anmeldung an Geräten, keine Konfigurationsänderung. Externe Programme (`ping`, `traceroute`) werden mit fester Argumentliste ohne Shell gestartet; fehlt ein Programm, MUSS das Ergebnis dies verständlich melden („Das Programm 'x' ist im Container nicht installiert.“) statt zu scheitern. **[Muss]**

#### Szenario: Hostname mit Shell-Zeichen
- **WENN** als Host `router;rm -rf /` übergeben wird
- **DANN** wird er als ungültig abgelehnt (siehe Eingabevalidierung), es startet kein Prozess

#### Szenario: traceroute fehlt
- **WENN** `traceroute` nicht installiert ist
- **DANN** `hops: []` und die Erklärung nennt das fehlende Programm

Quelle: `backend/app/diagnostics.py:7`–`backend/app/diagnostics.py:11`, `backend/app/diagnostics.py:53`–`backend/app/diagnostics.py:67`

### Requirement: Eingabevalidierung
Das System MUSS Hostnamen/IP-Adressen gegen ein striktes Muster prüfen (nur Buchstaben, Ziffern, `.`, `_`, `:`, `-`; Beginn und Ende alphanumerisch; max. 253 Zeichen) und Ports auf 1–65535; HTTP-Prüfungen nur für Adressen mit `http://` oder `https://`. Verstöße MÜSSEN mit HTTP 400 und deutscher Meldung abgelehnt werden. Zahlen MÜSSEN begrenzt werden: Ping-Anzahl 1–10, Traceroute-Hops 1–30, DNS-Gesamtprüfung max. 8 Namen. **[Muss]**

#### Szenario: Ungültiger Port
- **WENN** `check_port` mit `port: 70000` aufgerufen wird
- **DANN** 400 „Portnummern liegen zwischen 1 und 65535.“

#### Szenario: Option statt Host
- **WENN** als Host `-f` übergeben wird
- **DANN** 400 „'-f' ist kein gültiger Hostname und keine gültige IP-Adresse.“

#### Szenario: Ping-Anzahl zu groß
- **WENN** `count: 1000` übergeben wird
- **DANN** werden 10 Pakete gesendet

Quelle: `backend/app/diagnostics.py:29`–`backend/app/diagnostics.py:50`, `backend/app/diagnostics.py:74`, `backend/app/diagnostics.py:152`, `backend/app/diagnostics.py:176`, `backend/app/diagnostics.py:208`, `backend/app/main.py:1483`

### Requirement: Feste Zeitgrenzen
Jede Prüfung MUSS zeitlich begrenzt sein; bei Überschreitung wird der Prozess beendet und „Zeitüberschreitung -- das Gerät hat nicht rechtzeitig geantwortet.“ gemeldet. Werte: Ping `count·3+5` s gesamt, 2 s je Antwort; Port 3 s; DNS-Lookup 6 s; Reverse-DNS 5 s; HTTP 10 s (Connect 5 s); Traceroute `2·maxHops+10` s, 1 s je Hop; Internet-Check HTTP 10 s (Connect 5 s); Speedtest 30 s (Connect 8 s, gilt je Anfrage; die Latenzmessung macht vor dem Download 6 weitere kleine Anfragen). **[Muss]** (Einzelwerte **[Impl]**)

#### Szenario: Traceroute zu 15 Hops
- **WENN** eine Traceroute mit Default-Hops läuft
- **DANN** bricht sie spätestens nach 40 s ab

Quelle: `backend/app/diagnostics.py:62`–`backend/app/diagnostics.py:66`, `backend/app/diagnostics.py:75`, `backend/app/diagnostics.py:102`, `backend/app/diagnostics.py:118`, `backend/app/diagnostics.py:124`, `backend/app/diagnostics.py:157`, `backend/app/diagnostics.py:178`, `backend/app/diagnostics.py:259`, `backend/app/diagnostics.py:312`

### Requirement: Einzelprüfungen über eine Route
Das System MUSS über `POST /api/diagnostics` mit `{"tool": <name>, "args": {...}}` genau diese Prüfungen anbieten und jeden anderen Namen mit 400 „Unbekannte Prüfung '<name>'.“ ablehnen: `internet_check` (keine Args), `ping` (`host`, `count`=3), `check_port` (`host`, `port`), `dns_lookup` (`name`), `http_check` (`url`), `traceroute` (`host`, `maxHops`=15). Jedes Ergebnis MUSS ein Feld `explanation` mit einer laienverständlichen Deutung enthalten. **[Muss]** (Tool-Namen **[Impl]**) Die REST-Namen bleiben bewusst eigenständig: nur `ping` weicht vom LLM-Werkzeug `ping_host` ab, kein Alias; das Frontend nutzt über diese Route nur `internet_check`, und die LLM-Namen gehören zur Grenze von `tools.py`/MCP. **[Impl]**

#### Szenario: Unbekanntes Tool
- **WENN** `{"tool":"nmap"}` gesendet wird
- **DANN** 400 „Unbekannte Prüfung 'nmap'.“

Quelle: `backend/app/main.py:1463`–`backend/app/main.py:1485`

### Requirement: Ping
Das System MUSS die Erreichbarkeit per ICMP prüfen und `host`, `reachable` (Verlust < 100 %), `packetLossPercent`, `averageMs` (oder leer), `explanation`, `raw` (max. 2000 Zeichen) liefern. Erklärung nach Verlust: 0 % „erreichbar und antwortet zuverlässig (durchschnittlich n Millisekunden)“; 1–99 % Hinweis auf instabile Verbindung/WLAN; 100 % „antwortet gar nicht“ mit möglichen Ursachen. **[Muss]**

#### Szenario: Teilweiser Verlust
- **WENN** 1 von 3 Paketen verloren geht
- **DANN** `reachable: true`, `packetLossPercent: 33`, Erklärung nennt 33 % Verlust und WLAN als typische Ursache

Quelle: `backend/app/diagnostics.py:72`–`backend/app/diagnostics.py:94`

### Requirement: Keine Ziele auf dem Server selbst (SSRF)
Port- und HTTP-Prüfung MÜSSEN Ziele ablehnen (400 bzw. Werkzeugfehler), die auf Loopback
(127.0.0.0/8, ::1), Link-Local (169.254.0.0/16 inkl. Cloud-Metadaten, fe80::/10), unspezifizierte,
Multicast- oder reservierte Adressen zeigen; bei Namen gilt das für jede aufgelöste Adresse, bei
HTTP auch für jedes Weiterleitungsziel. Adressen im Heimnetz (privat) bleiben erlaubt. Ping und
Traceroute sind nicht betroffen. **[Muss]** Restrisiko: DNS-Rebinding zwischen Prüfung und Verbindung.

#### Szenario: Backend über Loopback
- **WENN** ein MEMBER oder der Assistent `http_check` mit `http://127.0.0.1:8281/` aufruft
- **DANN** lehnt das System ab, ohne eine Verbindung aufzubauen

#### Szenario: Weiterleitung auf eine verbotene Adresse
- **WENN** eine erlaubte Seite auf `http://169.254.169.254/` weiterleitet
- **DANN** lehnt das System ab

Quelle: `backend/app/diagnostics.py` (`_ensure_allowed_target`, `_fetch_page`; die Adresslogik liegt in `backend/app/netguard.py`), Tests:
`backend/tests/test_diagnostics.py`

### Requirement: Port-Prüfung
Das System MUSS per TCP-Verbindungsaufbau prüfen, ob ein Port offen ist, und drei Fälle unterscheiden: offen (`open: true`, `elapsedMs`), keine Antwort (Timeout – Dienst aus oder Firewall verwirft) und aktiv abgelehnt (Dienst läuft nicht). Das Ergebnis nennt den Dienstnamen aus dem Port-Katalog. **[Muss]**

#### Szenario: Port abgelehnt
- **WENN** das Ziel die Verbindung mit RST ablehnt
- **DANN** `open: false`, Erklärung „… ist geschlossen -- die Verbindung wurde aktiv abgelehnt …“

Quelle: `backend/app/diagnostics.py:124`–`backend/app/diagnostics.py:147`

### Requirement: DNS-Lookup
Das System MUSS einen Namen über den Resolver des Servers auflösen und `resolved`, sortierte eindeutige `addresses` und eine Erklärung liefern; bei Fehlschlag MUSS die Erklärung auf einen möglichen DNS-Ausfall am Router hinweisen. **[Muss]**

#### Szenario: Name nicht auflösbar
- **WENN** `dns_lookup` für einen nicht existierenden Namen läuft
- **DANN** `resolved: false`, `addresses: []`, Erklärung mit Hinweis auf DNS/Router

Quelle: `backend/app/diagnostics.py:97`–`backend/app/diagnostics.py:111`

### Requirement: HTTP-Prüfung
Das System MUSS eine Web-Adresse per GET abrufen, höchstens 5 Weiterleitungen folgen (jede Zieladresse wird erneut geprüft) und Zertifikatsfehler ignorieren (Heimgeräte nutzen selbstsignierte Zertifikate). Gelesen werden höchstens 256 KiB der Antwort, die ganze Prüfung dauert höchstens 15 s. Ergebnis: `reachable`, `status`, `title` (aus den ersten 20 000 Zeichen, Leerraum normalisiert, max. 120 Zeichen), `server`-Header, `elapsedMs`, Erklärung. **[Muss]**

#### Szenario: Router-Oberfläche mit Selbstsigniert-Zertifikat
- **WENN** `https://192.168.1.1` geprüft wird
- **DANN** `reachable: true`, Status und Seitentitel werden gemeldet

Quelle: `backend/app/diagnostics.py:150`–`backend/app/diagnostics.py:171`

### Requirement: Traceroute
Das System MUSS den Weg zu einem Ziel ermitteln (1 Probe je Hop, numerisch) und `hops` (`hop`, `address`), `raw` (max. 3000 Zeichen) sowie eine Erklärung liefern, die den ersten Hop als eigenen Router einordnet. **[Muss]**

#### Szenario: Kein Weg
- **WENN** keine Hop-Zeile auswertbar ist
- **DANN** `hops: []`, Erklärung „Zu <host> ließ sich kein Weg ermitteln.“

### Requirement: Traceroute begrenzen
Das System MUSS höchstens 2 Traceroutes gleichzeitig zulassen (über REST, Chat und MCP zusammen; weitere scheitern sofort mit einer verständlichen Meldung, im Chat als Werkzeugfehlertext) und über `POST /api/diagnostics` höchstens 3 Traceroutes je Benutzer und Minute (Gleitfenster; auch Anfragen mit ungültigem Ziel zählen). **[Muss]** (Zahlen **[Impl]**)

#### Szenario: Zu viele Traceroutes
- **WENN** ein Benutzer innerhalb einer Minute eine vierte Traceroute über die Route anfordert
- **DANN** antwortet das System mit 429 und `Retry-After` (Sekunden); andere Benutzer sind nicht betroffen

#### Szenario: Gleichzeitige Obergrenze
- **WENN** bereits 2 Traceroutes laufen und eine dritte startet
- **DANN** wird sie abgelehnt (REST: 429, Chat/MCP: Fehlertext an das Modell)

Quelle: `backend/app/diagnostics.py`, `backend/app/routes/diagnostics.py`, `backend/app/limits.py`

### Requirement: Internet-Check in drei Schichten
Das System MUSS die Internetverbindung in drei unabhängigen Schichten prüfen – Namensauflösung (`www.google.com`), Erreichbarkeit (2 Pings an `1.1.1.1`), Webseiten (`GET https://www.gstatic.com/generate_204`, Erfolg bei 200/204) – und `dnsWorks`, `internetReachable`, `websitesLoad`, `explanation`, `details` liefern. Verdikt in dieser Reihenfolge: alles ok ⇒ „funktioniert vollständig“; Ping ok, DNS nicht ⇒ DNS-Störung am Router; Ping+DNS ok, HTTP nicht ⇒ Filter/Kindersicherung/Proxy; Ping nicht ⇒ keine Verbindung, Hinweis auf DSL-Lampe; sonst „nur teilweise nutzbar“. **[Muss]** (Zielhosts **[Impl]**)

#### Szenario: DNS gestört
- **WENN** `1.1.1.1` antwortet, `www.google.com` aber nicht auflösbar ist
- **DANN** `dnsWorks: false`, `internetReachable: true`, Erklärung verweist auf eine Router-Einstellung

Quelle: `backend/app/diagnostics.py:248`–`backend/app/diagnostics.py:283`, UI: `frontend/src/pages/start/StartPage.tsx`

### Requirement: DNS-Gesamtprüfung
Das System MUSS mehrere externe Namen nacheinander auflösen und je Name Ergebnis und Dauer (`elapsedMs`) liefern, dazu die konfigurierten DNS-Server des Servers (`servers`), `resolvedCount`, `totalCount`, ein Verdikt und `serversExplanation`. Namen: aus dem Request (`names`), sonst Einstellung `dnsTestNames`, sonst `www.google.com`, `heise.de`, `github.com`; max. 8. Verdikt: keiner auflösbar ⇒ Namensauflösung gestört (Router/Pi-hole); einige nicht ⇒ Filter/Sperre einzelner Adressen; alle, aber ≥ 1 langsamer als 1500 ms ⇒ „auffällig langsam“; sonst „funktioniert einwandfrei“. Kein DNS-Server eingetragen ⇒ `serversExplanation` nennt das als Ursache. **[Muss]**

#### Szenario: Ein Name gesperrt
- **WENN** `heise.de` nicht, die anderen schon auflösbar sind
- **DANN** Verdikt „… aber nicht für: heise.de …“ (Hinweis auf Filter)

#### Szenario: Langsamer Resolver
- **WENN** alle Namen auflösbar sind, einer aber 2 s braucht
- **DANN** Verdikt „… 1 davon auffällig langsam (über 1,5 Sekunden) …“

Quelle: `backend/app/main.py:1595`–`backend/app/main.py:1599`, `backend/app/diagnostics.py:194`–`backend/app/diagnostics.py:245`, `backend/app/discovery.py:215`, `backend/app/db.py:456`

### Requirement: Speedtest nur auf ausdrücklichen Klick
Das System MUSS höchstens einen Speedtest gleichzeitig zulassen und MUSS einen Durchsatztest gegen einen öffentlichen Speedtest-Dienst nur auf direkte Anforderung eines Benutzers ausführen und DARF ihn dem Assistenten/MCP NICHT als Werkzeug anbieten. Gemessen werden Latenz (Median von 5 Anfragen mit 0 Byte auf der bereits aufgebauten Verbindung, nach einer verworfenen Aufwärm-Anfrage), Download (25 MB) und Upload (10 MB); Ergebnis `ok`, `downloadMbps`, `uploadMbps` (1 Nachkommastelle), `pingMs`, `explanation`; bei Netzwerkfehler `ok: false` mit verständlicher `error`-Meldung (HTTP 200). **[Muss]** (Dienst, Datenmengen und Anzahl der Latenz-Anfragen **[Impl]**)

#### Szenario: Keine Internetverbindung
- **WENN** der Speedtest-Dienst nicht erreichbar ist
- **DANN** `ok: false`, `error` „Speedtest fehlgeschlagen -- ist eine Internetverbindung vorhanden? (…)“, alle Messwerte leer

#### Szenario: Erste Anfrage mit Verbindungsaufbau
- **WENN** der Speedtest startet und die erste Anfrage TCP- und TLS-Aufbau enthält
- **DANN** zählt diese Aufwärm-Anfrage nicht zur Latenz; `pingMs` ist der Median der 5 Folgeanfragen

#### Szenario: Zweiter paralleler Speedtest
- **WENN** bereits ein Speedtest läuft und ein weiterer angefordert wird
- **DANN** antwortet `POST /api/diagnostics/speedtest` mit 429 („Es läuft bereits ein Speedtest. Bitte kurz warten.“); die Sperre wird auch bei Abbruch freigegeben

Quelle: `backend/app/diagnostics.py:392`–`backend/app/diagnostics.py:453`, `backend/app/main.py:1602`, `backend/app/tools.py:38` (kein Speedtest-Tool)

## Daten

Aus [data-model](../../contracts/data-model.md): keine Entitäten gelesen/geschrieben, keine Protokolleinträge.
Settings (nur lesend; geschrieben über [einstellungen-und-llm-provider](../einstellungen-und-llm-provider/spec.md)): `dnsTestNames` (Default `["www.google.com","heise.de","github.com"]`). Liest `/etc/resolv.conf` des Servers für die DNS-Server-Liste.

## Schnittstellen

| Methode | Pfad | Rolle | Zweck |
|---|---|---|---|
| POST | /api/diagnostics | MEMBER | Einzelprüfung: `{"tool","args"}` → `{"result"}` |
| POST | /api/diagnostics/dns | MEMBER | DNS-Gesamtprüfung, Body optional `{"names": [...]}` |
| POST | /api/diagnostics/speedtest | MEMBER | Durchsatztest Download/Upload/Latenz |

Berührt: dieselben Funktionen als LLM-Werkzeuge `internet_check`, `ping_host`, `check_port`, `dns_lookup`, `reverse_dns`, `http_check`, `traceroute` ([llm-tools](../../contracts/llm-tools.md), [assistent-chat-und-mcp](../assistent-chat-und-mcp/spec.md)); Port-/Ping-Prüfung des [monitoring](../monitoring/spec.md).

UI-Seite(n): `frontend/src/pages/start/StartPage.tsx` (Route `/`, Internet-Check), `frontend/src/pages/geraete/PlanPage.tsx` (Route `/plan`, DNS-Prüfung und Speedtest), `frontend/src/pages/SettingsPage.tsx` (Route `/einstellungen`, `dnsTestNames`).

## Nicht-Ziele und Grenzen

- Keine Portscans über Bereiche, kein beliebiger Befehl, keine Anmeldung an Geräten.
- Kein Verlauf: Ergebnisse werden nicht gespeichert.
- `ping`, `check_port`, `dns_lookup`, `http_check`, `traceroute` haben über REST keine UI; nur `internet_check` wird im Frontend genutzt. Reverse-DNS gibt es nur als LLM-Werkzeug, nicht über REST.
- Unter Windows-Containern fehlen `ping`/`traceroute`; die Prüfungen melden das als Ergebnis.
- Praktisch nur IPv4: IPv6-Literale, die mit `:` beginnen (z. B. `::1`), scheitern am Muster.

## Ist-Implementierung (nur Referenz, [Impl])

- `ping -c <n> -W 2 -n <host>`; `traceroute -n -w 1 -q 1 -m <hops> <host>`; Auswertung per Regex der Textausgabe (`% packet loss`, `= min/avg/…`).
- DNS über `getaddrinfo` des Servers (Resolver aus `/etc/resolv.conf`), Reverse-DNS über `gethostbyaddr` im Thread-Pool.
- Speedtest gegen `https://speed.cloudflare.com/__down?bytes=…` / `__up`; Upload-Daten sind Zufallsbytes. Latenz: 1 Aufwärm-Anfrage (`bytes=0`, verworfen) + 5 Anfragen auf der Keep-Alive-Verbindung, Median, jeweils bis zum vollständigen Body gemessen.
- Fehlerklasse `DiagnosticError` → HTTP 400 in `/api/diagnostics`; im Assistenten als `{"error": …}` an das Modell.

## OFFEN

