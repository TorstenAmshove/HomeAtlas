# HomeAtlas 🧭

**Dein Zuhause, dokumentiert.**

HomeAtlas durchsucht das eigene Heimnetz, erkennt selbstständig, was darin steht, und schreibt
daraus eine nach Themen sortierte Dokumentation — in einer Sprache, die auch jemand ohne
IT-Kenntnisse versteht. Dazu kommt ein KI-Assistent, der bei Störungen nicht nur redet, sondern
selbst nachmisst: pingt, Ports prüft, die Internetverbindung in drei Schichten testet.

Läuft als Docker-Container im eigenen Netz. Keine Cloud, keine Registrierung.

---

## Was es kann

| | |
|---|---|
| **Selbstständige Erkennung** | Ping/ARP-Sweep, Portscan, Reverse-DNS, mDNS/Bonjour, UPnP/SSDP, HTTP-Banner und Docker-API — fünf unabhängige Quellen, weil keine davon allein alles sieht |
| **Container-Namen & Compose-Stacks** | Docker-Container heißen `<service> · <projekt>` (z. B. `postgres · immich`); die Geräteliste gruppiert sie nach Compose-Projekt (einklappbar, mit Projekt-Filter), die Dokumentation zeigt eine Überschrift je Stack. Die KI-Einordnung benennt nie ein Gerät um, dessen Name aus einer Quelle stammt (UniFi, Docker, Proxmox, Omada) oder vom Gerät selbst gemeldet wird (UPnP, mDNS) |
| **Verständliche Doku** | 14 Kapitel nach Themen (Internet & Router, Netzwerk, Server, Container, Smart Home, Wärme & Energie, Erreichbarkeit von außen, Zugänge, Notfall, Wer darf mit wem sprechen …) als Markdown im Browser |
| **KI-Assistent** | Kennt das Inventar, misst live nach und führt Schritt für Schritt durch die Fehlersuche |
| **Zugangsverwaltung** | Passwörter, SSH-Schlüssel und Passphrasen verschlüsselt gespeichert, nie in der Doku, nie beim KI-Anbieter |
| **Geräte auslesen** | Mit freigegebenen Zugängen anmelden und Eckdaten lesen — streng lesend, feste Befehlsliste (SSH, HTTP, FRITZ!Box TR-064) |
| **Hersteller-Doku** | Link zur passenden Support-Seite je Gerät; von der KI vorgeschlagene Links werden vor dem Speichern auf Erreichbarkeit geprüft |
| **Versionierte Doku** | Jeder frühere Stand jeder Seite bleibt abrufbar und wiederherstellbar |
| **Zwei Rollen** | Administrator sieht und ändert alles; Mitglieder lesen die Doku und nutzen den Chat — ohne Passwörter. Jeder sieht nur seine eigenen Unterhaltungen mit dem Assistenten |
| **Dauerüberwachung** | Wichtige Geräte alle paar Sekunden per Port oder Ping geprüft, mit Ausfallverlauf |
| **Übersichtsplan** | Automatisch erzeugter Netzplan vom Internet bis zu den Endgeräten |
| **UniFi Network** | Liest Geräte, physische Uplinks, VLANs, WLANs und WANs direkt über die lokale UniFi-API aus |
| **Anmeldeschutz** | Passwortrichtlinie, verpflichtende Zwei-Faktor-Anmeldung per Authenticator-App, Zugriffsprotokoll |

Der Anbieter für die KI ist frei wählbar: **Anthropic Claude, OpenAI, Google Gemini, DeepSeek**
oder ein **lokaler Ollama-Server** (dann verlässt kein einziges Byte das Haus).

---

## Installation

### Per Ansible auf docker.lan (empfohlen)

HomeAtlas wird dort als GHCR-Image durch
[`ansible-docker.lan`](https://github.com/TorstenAmshove/ansible-docker.lan) ausgerollt. Wenn ein
Pull Request mit einer Code-Änderung nach `master` gemergt wird, erzeugt der Workflow **Release
container images** anhand der [Conventional Commits](https://www.conventionalcommits.org/)
automatisch einen Git-Tag `vX.Y.Z` und veröffentlicht beide Images mit `X.Y.Z`, `X.Y` und
`latest`. Ein manueller Workflow-Lauf dient für den ersten Release oder als Fallback.

Das Ansible-Repository übernimmt neue vollständige Versionen per Renovate. Für einen manuellen
Deployment-Lauf ist keine Image-Tag-Variable mehr erforderlich:

```bash
ansible-playbook --vault-password-file .secret/docker playbook.yml \
  -t traefik,uptimekuma,homeatlas
```

Die Anwendung ist danach über `https://homeatlas.malt10.de` erreichbar. Das persistente
Verzeichnis `/opt/homeatlas` muss vollständig gesichert werden: Datenbank `homeatlas.db` und
Verschlüsselungsschlüssel `secret.key` gehören zusammen. Das Administratorpasswort wird beim
allerersten Start einmalig im Backend-Protokoll ausgegeben und nicht in Ansible hinterlegt.

GitHub Packages legt neue Container-Packages zunächst privat an. Vor dem ersten Ansible-Deployment
müssen `homeatlas-backend` und `homeatlas-frontend` in den jeweiligen Package-Einstellungen auf
**public** gesetzt werden, weil der Docker-Host ohne GHCR-Anmeldedaten pullt.

### Auf einem anderen Docker-Host per docker compose

Direkt auf dem Docker-Host, auf dem HomeAtlas laufen soll (beide Container nutzen das Host-Netz):

```bash
git clone https://github.com/TorstenAmshove/HomeAtlas.git
cd HomeAtlas
docker compose up -d --build
```

Danach: **http://<host>:8280**

Sind die Ports dort schon belegt, andere wählen:

```bash
HOMEATLAS_PORT=8380 HOMEATLAS_API_PORT=8381 docker compose up -d --build
```

### Erste Anmeldung

Beim allerersten Start wird ein Administrator angelegt und sein Passwort **einmalig** ins
Protokoll geschrieben:

```bash
docker compose logs backend | grep -A4 Anmeldedaten
```

Ein eigenes Passwort lässt sich stattdessen in `docker-compose.yml` über `ADMIN_USERNAME` /
`ADMIN_PASSWORD` vorgeben (wirkt nur, solange noch kein Benutzer existiert).

Direkt nach der ersten Anmeldung verlangt HomeAtlas die Einrichtung der Zwei-Faktor-Anmeldung:
QR-Code mit einer Authenticator-App (z. B. Aegis, Google Authenticator, 1Password) scannen und den
angezeigten Code bestätigen. Erst danach ist der Rest der Anwendung erreichbar — das gilt für jedes
Konto, auch für später angelegte Mitglieder.

### Passwort verloren?

Das generierte Passwort wird **genau einmal** ausgegeben — ins Startprotokoll des Containers, der
den Benutzer angelegt hat. Ist dieser Container weg (Absturzschleife, `docker compose down`,
Log-Rotation), das Datenvolume aber noch da, hilft `ADMIN_PASSWORD` nicht mehr weiter: es greift
nur, solange überhaupt kein Benutzer existiert. Dafür gibt es das Wiederherstellungswerkzeug:

```bash
docker compose exec backend python -m app.reset_password                       # Benutzer auflisten
docker compose exec backend python -m app.reset_password admin neuespasswort   # Passwort setzen
```

Das legt den Benutzer auch neu als Administrator an, falls gar keiner mehr existiert.

**Authenticator verloren?** Die Zwei-Faktor-Anmeldung lässt sich normalerweise nur von einem
anderen Administrator zurücksetzen (*Benutzer*, Spalte Zwei-Faktor → *Zurücksetzen*). Gibt es keinen
anderen, hilft dasselbe Werkzeug mit `--reset-mfa`:

```bash
docker compose exec backend python -m app.reset_password admin --reset-mfa                 # nur 2FA entfernen
docker compose exec backend python -m app.reset_password admin neuespasswort --reset-mfa   # beides
```

Das entfernt den hinterlegten zweiten Faktor, beendet alle offenen Sitzungen des Benutzers und
vermerkt den Vorgang im Zugriffsprotokoll (`mfa.reset`, ausgeführt von „(Kommandozeile)“). Beim
nächsten Anmelden richtet der Benutzer die Zwei-Faktor-Anmeldung wie beim ersten Mal neu ein. Ein
reiner Passwort-Reset ohne `--reset-mfa` lässt einen eingerichteten zweiten Faktor bewusst
bestehen — wer nur das Passwort vergessen hat, verliert so nicht nebenbei den Schutz.

---

## Der erste Durchlauf

1. **Anmelden**, die Zwei-Faktor-Anmeldung einrichten und den kurzen Einrichtungsassistenten
   ausfüllen — Name des Zuhauses, die wichtigsten Geräte, die wichtigsten Konten. Alles optional
   und jederzeit änderbar.
2. **Einstellungen → KI-Assistent**: Anbieter wählen, Schlüssel eintragen, *Verbindung testen*.
   Ohne diesen Schritt funktioniert HomeAtlas weiter, nur ohne KI-Texte und ohne Chat.
3. **Netzwerk-Scan starten.** Der Durchlauf sucht Geräte, erkennt Dienste, fragt Docker ab, lässt
   die KI Unbekanntes einordnen und schreibt anschließend die Dokumentation neu. Dauer: wenige
   Minuten für ein typisches /24-Netz.

Von Hand gepflegte Angaben sind ab dem Moment geschützt, in dem du sie speicherst: der nächste
Scan aktualisiert nur noch die veränderlichen Fakten (IP, Zustand, offene Ports) und lässt Name,
Standort und Beschreibung unangetastet.

### Eigene Notizen je Kapitel

Jedes Doku-Kapitel hat einen festen Bereich, den die Generierung **nie** anfasst — für alles, was
kein Scan herausfinden kann: wo die Sicherung für den Serverschrank sitzt, dass der Switch nach
einem Stromausfall fünf Minuten braucht, wer den Wartungsvertrag für die Heizung hat.

Der Bereich liegt technisch in einer eigenen Spalte, nicht als markierter Abschnitt im erzeugten
Text. Dadurch kann eine Neuerzeugung ihn gar nicht erst beschädigen, statt sich darauf zu
verlassen, dass ein Parser ihn jedes Mal korrekt wiederfindet. Beides bleibt unabhängig: die
Notiz steht dauerhaft, während Gerätetabellen und Beschreibungen weiter automatisch aktuell
bleiben.

Der KI-Assistent bekommt diesen Teil getrennt und ausdrücklich als verlässlicher gekennzeichnet —
was Bewohner über ihr eigenes Haus aufschreiben, wiegt schwerer als jede Scan-Schlussfolgerung.

Wer stattdessen eine **ganze** Seite selbst schreiben will, kann das weiterhin tun; sie wird dann
als *von Hand bearbeitet* markiert und gar nicht mehr aktualisiert (über *Neu erzeugen*
zurücknehmbar). Für dauerhafte Ergänzungen sind die eigenen Notizen aber meist die bessere Wahl.

---

## Architektur

```
                    ┌──────────────────────────────────────────────┐
Browser ── :8280 ──▶│ nginx (Frontend, React + TypeScript)         │
                    │   └─ /api/* ──▶ 127.0.0.1:8000               │
                    └──────────────────────────────────────────────┘
                                        │
                    ┌───────────────────▼──────────────────────────┐
                    │ FastAPI-Backend (Host-Netz)                  │
                    │   discovery ─ ping/ARP, Ports, mDNS, SSDP    │
                    │   docker_probe ─ /var/run/docker.sock (ro)   │
                    │   classify ─ KI-Einordnung unbekannter Geräte│
                    │   docs ─ Markdown-Kapitel                    │
                    │   tools ─ Werkzeuge für den Assistenten      │
                    │   SQLite + Fernet-verschlüsselte Zugänge     │
                    └──────────────────────────────────────────────┘
```

**Warum Host-Netzwerk?** Discovery liest die ARP-Tabelle des Hosts und verschickt Multicast
(mDNS/SSDP). Über ein Docker-Bridge-Netz käme davon nichts an — die App würde nur das
Docker-Netz sehen, nie das echte Heimnetz. Deshalb bindet das Backend bewusst nur an
`127.0.0.1`: nginx ist das Einzige, was es erreicht.

mDNS lauscht nur auf den Interfaces, deren Adresse in einem der Scan-Bereiche liegt — nicht auf
jeder Docker-Bridge des Hosts. Erscheint im Scan-Log „mDNS-Erkennung übersprungen“ (z. B.
`[Errno 105] No buffer space available`), ist das Limit `net.ipv4.igmp_max_memberships` des Hosts
erschöpft. Der Scan läuft dann ohne mDNS-Daten weiter; Abhilfe: Scan-Bereiche prüfen oder das Limit
per `sysctl` erhöhen.

---

## UniFi Network einrichten

HomeAtlas nutzt ausschließlich die dokumentierte lokale UniFi Network Integration API unter
`https://<controller>/proxy/network/integration/v1`. In UniFi Network einen API-Schlüssel mit
lesenden Berechtigungen erstellen und ihn in HomeAtlas unter **Zugänge** als **UniFi Network
(API-Key)** hinterlegen. Als Adresse dient die HTTPS-Adresse des Controllers, zum Beispiel
`https://192.168.1.1`; Benutzername und Port bleiben leer. Erst mit dem Haken **Zum Auslesen
verwenden** fragt der nächste Netzwerk-Scan den Controller ab. Auf der Detailseite des Controllers
startet **Gerät auslesen** dieselbe vollständige Synchronisierung sofort, ohne auf den nächsten
Vollscan zu warten.

Der Import umfasst alle verfügbaren Sites und ist strikt lesend: HomeAtlas sendet nur `GET`
Anfragen. API-Schlüssel bleiben verschlüsselt gespeichert, erscheinen weder in der Doku noch im
KI-Kontext und werden nicht protokolliert. Nicht vertrauenswürdige lokale Zertifikate werden für
den Controllerzugriff akzeptiert; deshalb darf die Controller-Adresse nur in einem vertrauenswürdigen
Heimnetz hinterlegt werden.

Ein in UniFi vergebener Geräte- oder Clientname ist in HomeAtlas der führende automatisch ermittelte
Name. Er hat Vorrang vor DNS, mDNS, KI und anderen Datenquellen; ein manuell in HomeAtlas bearbeiteter
Name bleibt davon unberührt.

Clients (z. B. aus dem Gäste-WLAN) übernimmt HomeAtlas nur, wenn ihre IP in den gescannten Netzen
liegt (in den Scan-Einstellungen gewählte Netze plus Freitext-Netze, ohne Auswahl die Netze der
Host-Interfaces); Clients ohne IP werden übersprungen. UniFi-Geräte (Gateway, Switches, APs) werden
immer übernommen. Bereits importierte Einträge löscht der Filter nicht, das geschieht manuell. Beim
allerersten Sync kennt HomeAtlas die UniFi-Netze noch nicht und filtert nach Freitext bzw.
Host-Interfaces.

Unter **Netze & WLAN** stehen die übernommenen VLANs, SSIDs und WANs. Technische Controllerdaten
werden bei jedem Scan aktualisiert; eigene Notizen bleiben dabei erhalten.

---

## Sicherheit

Diese App speichert absichtlich Router-, NAS- und WLAN-Passwörter. Deshalb hier offen, was sie
schützt und was nicht:

**Verschlüsselung.** Zugangsdaten liegen Fernet-verschlüsselt in der Datenbank. Der Schlüssel
liegt im selben Docker-Volume. Das schützt gegen eine **abhandengekommene Datenbankkopie**
(Backup, `docker cp`, versehentlicher Dump) — **nicht** gegen jemanden, der bereits root auf dem
Docker-Host ist, denn der liest auch die Schlüsseldatei. Die Alternative wäre eine Passphrase bei
jedem Containerstart, was einen unbeaufsichtigten Neustart unmöglich machte.

**Die KI sieht keine Passwörter.** Das Werkzeug `list_accounts` gibt Bezeichnung, Benutzername
und Notiz zurück und streicht das Passwort — auch wenn das Modell „vertrauenswürdig" ist. Ein
Passwort im Prompt landet im Protokoll des Anbieters, im Chatverlauf und in jedem künftigen
Kontextfenster. Der Assistent kann sagen, *wo* ein Zugang hinterlegt ist; ansehen muss ihn der
Mensch in der App.

**Home Assistant live lesen.** Der Assistent kann Zustände, Verlauf, Logbuch und Fehlerlog von
Home Assistant live abfragen, dazu Automations-Traces (Auslöser und Ablauf; per WebSocket, nur die
Befehle `trace/list`, `trace/get` und als Rückfall für das Fehlerlog `system_log/list`). Sonst nur lesende GET-Aufrufe, höchstens 7 Tage und eine
feste Zahl an Einträgen. Texte werden vor der Ausgabe von Tokens, Passwörtern und Zugangs-URLs bereinigt; das
Zugriffstoken bleibt auf dem Server. Das Opt-in „Zum Auslesen verwenden“ gilt für diese
Abfragen nicht (wie bei `list_switches`), und sie stehen allen Rollen und MCP-Clients offen.

**UniFi live lesen.** Der Assistent kann Live-Werte vom UniFi-Controller abfragen: eines verbundenen
Clients (Signal, Retries, Roaming, Access Point; `get_unifi_client`), eines UniFi-Geräts (Last, Uplink,
Port-Fehler; `get_unifi_device`), von WAN/LAN und Firewall-Zusammenfassung (`get_unifi_network`) sowie
Controller-Ereignisse der letzten bis zu 7 Tage (`get_unifi_events`). Es sind feste Pfade der klassischen
API per GET plus genau eine lesende POST-Abfrage des Ereignislogs (fester Pfad, Body nur aus berechneten
Zahlen); Auth allein mit dem API-Key des Zugangs „UniFi“ (kein Login, kein Cookie). WAN-IP, Nameserver,
Firewall-Adresslisten und Geräteschlüssel werden nie weitergegeben.
Nur ausdrücklich freigegebene Felder werden weitergegeben, der Key bleibt auf dem Server, nichts wird
gespeichert. Der Controller wird wie beim Scan ohne Zertifikatsprüfung angesprochen (selbstsigniertes
Zertifikat im LAN; der Key geht im Header an den Controller im LAN). Das Opt-in „Zum Auslesen
verwenden“ gilt für diese Abfrage nicht, und sie steht allen Rollen und MCP-Clients offen.
Geprüft gegen UniFi Network 11.0.103. Hintergrund: ADR-0015, ADR-0016.

**Erreichbarkeit im Assistenten und auf der Geräteseite.** Das Werkzeug `list_exposure` beantwortet
Fragen wie „warum ist app2.example.net nicht erreichbar?“. Es liest nur die beim letzten Scan
gespeicherten Fakten (kein Live-DNS, keine Geheimnisse, höchstens 15 Zeilen je Liste mit Hinweis auf
Kürzung) und ist für Administratoren und Mitglieder gleich. Auf der Geräteseite (Tab „Technik“) steht
„Erreichbar über …“, wenn das Gerät Ziel einer Kette, einer Traefik-Route oder einer Portweiterleitung ist.

**Traefik lesen (Erreichbarkeit).** Für „Intern per TLS erreichbare Dienste“ liest HomeAtlas die
Traefik-API, ausschließlich per GET auf `/api/http/routers`, `/api/http/services` und
`/api/entrypoints` (nie die Middleware-Liste, weil dort BasicAuth-Hashes stehen können). Minimal
nötige Rechte: ein eigener BasicAuth-Nutzer nur für den API-Entrypoint, den Traefik nur im LAN
erreichbar macht. Der Zugang (Kategorie „Traefik API“) braucht „Zum Auslesen verwenden“; die Quelle
ist in den Einstellungen abschaltbar (`scanEnableTraefik`). Gespeichert werden nur Hostname,
Ziel-URL, Zertifikats-Resolver und Middleware-Namen, nie die Regel im Rohformat oder Zugangsdaten.

**Portweiterleitungen und WAN-Adresse (UniFi, Erreichbarkeit).** Die Integration-API von UniFi kennt
weder Portweiterleitungen noch die WAN-Adresse, deshalb liest HomeAtlas sie über die klassische API.
Dafür genügt der API-Key des Zugangs „UniFi Network (API-Key)“, kein Benutzer und kein Login: nur GET
mit `X-API-Key`, ohne Cookie und ohne Weiterleitungen. Minimal nötige Rechte: Der Key hat die Rechte
seines Erstellers (mehr als „View Only“); lege ihn deshalb mit einem möglichst eingeschränkten lokalen
Konto an. Der Zugang braucht „Zum Auslesen verwenden“; die Quelle ist in den Einstellungen
abschaltbar (`scanEnableUnifiClassic`). Gespeichert werden nur Protokoll, Ports, Ziel-IP und die
WAN-Adresse, nie Name, Quellfilter oder Key. Ein früherer Zugang „UniFi klassische API“ wird beim
Start gelöscht; nötig ist stattdessen ein `unifi`-Zugang mit „Zum Auslesen verwenden“ (ADR-0016).

**Firewall-Regeln (UniFi).** Optional liest HomeAtlas die Firewall-Zonen, -Policies und Adress-/Port-Gruppen
des UniFi-Gateways, um später auszuwerten, welche Netze miteinander sprechen dürfen. Das ist
standardmäßig **aus** (`scanEnableFirewallUnifi`) und braucht denselben Zugang wie oben: „UniFi Network
(API-Key)“ mit „Zum Auslesen verwenden“. Nur GET mit `X-API-Key` auf drei feste Pfade je Site, ohne Login und
Weiterleitungen. Minimal nötige Rechte: wie oben, der Key hat die Rechte seines Erstellers (ADR-0017).
Gespeichert werden nur Zonen, Regelname, Reihenfolge, Aktion, Protokoll, Ports und IPs, nie Kommentare,
Trefferzähler oder Schlüssel. Ist die Quelle nicht lesbar, bleiben die alten Regeln als veraltet markiert.
Der Assistent bewertet damit Wege: `check_firewall_path` (von, nach, Port, Protokoll) liefert je Station (UniFi-Gateway,
Host-Firewall) „erlaubt“, „blockiert“ oder „unklar“ mit auslösender Regel, `list_firewall_rules` listet die gespeicherten
Regeln. HomeAtlas wertet aus, der Assistent erklärt nur; „unklar“ heißt nicht auswertbar (Quelle fehlt oder veraltet,
Zeitplan, Gruppen, IPv6, ICMP …), nie „erlaubt“. Nicht ausgewertet werden Proxmox-Firewall, nftables-`forward` und
NAT/Portweiterleitung. Das Kapitel „Wer darf mit wem sprechen“ zeigt die Zonenmatrix, Ausnahmen und Host-Firewalls; jede Erreichbarkeits-Kette trägt je Schritt das Firewall-Ergebnis.

**Firewall-Regeln (nftables der Hosts).** Optional liest HomeAtlas den live geladenen nftables-Regelsatz
einzelner Hosts, weil nur er zeigt, was tatsächlich gilt. Standardmäßig **aus** (`scanEnableFirewallNft`)
und zusätzlich je Host opt-in: Zugang der Kategorie „nftables-Firewall lesen“ (Zielsystem, Benutzername,
Port, privater Schlüssel) mit „Zum Auslesen verwenden“. HomeAtlas sendet genau einen im Code festen Befehl
(`nft -j list ruleset`); was wirklich läuft, bestimmt der Zielhost. Dafür braucht er einen eigenen Nutzer
ohne Shell-Rechte, einen `authorized_keys`-Eintrag und eine sudoers-Zeile nur für diesen einen Befehl
(Pfad der Binärdatei je Distribution anpassen, `which nft`):

```
# ~homeatlas/.ssh/authorized_keys
restrict,from="<HomeAtlas-IP>",command="sudo /usr/sbin/nft -j list ruleset" ssh-ed25519 AAAA… homeatlas
# /etc/sudoers.d/homeatlas-nft
homeatlas ALL=(root) NOPASSWD: /usr/sbin/nft -j list ruleset
```

Die Firewall des Zielhosts lässt SSH nur von der HomeAtlas-IP zu (bei `policy drop` auf `input` eine
Regel dafür ergänzen). Gespeichert werden nur Hook, Priorität, Policy und je Regel Quell-/Ziel-IP, Port,
Verbindungsstatus, Schnittstelle und Urteil (accept/drop/reject), nie Kommentare oder die Rohausgabe.
Alles, was HomeAtlas nicht sicher beurteilen kann (`jump`/`goto`, NAT, Raten-Begrenzung, Negation), wird
als „nicht auswertbar“ vermerkt. Ist ein Host nicht lesbar (sudo verweigert, Zeitüberschreitung, Ausgabe über
512 KiB), bleiben die alten Regeln als veraltet markiert. Docker-eigene Regeln und IPv6 werden in v1 nicht
ausgewertet.

**Cloudflare und öffentliches DNS (Erreichbarkeit, Kontakt nach außen).** Beides ist standardmäßig
**aus** (`scanEnableCloudflare`, `scanEnablePublicDns`), weil es das einzige ist, was HomeAtlas außerhalb
des LANs erreicht; ohne sie bleibt der Pfadstatus „unklar“. Cloudflare: ein eigener API-Token, nur GET,
auf die Zone beschränkt, mit den Rechten Zone DNS:Read, Zone WAF:Read und Account Cloudflare
Tunnel:Read. Der Zugang (Kategorie „Cloudflare API“) trägt die Zone-ID im Feld Adresse, die Account-ID
im Feld Benutzername und den Token als Geheimnis. Das Tunnel-Token wird nie abgerufen, von den
WAF-Regeln wird nur gelesen, ob sie ein Client-Zertifikat verlangen. Das öffentliche DNS nutzt einen
festen DoH-Resolver (`cloudflare-dns.com`, nur GET); er erfährt dabei die öffentlichen Hostnamen des
Haushalts (höchstens 200 Abfragen je Scan, keine Wildcards). DynDNS-Container (ddclient,
cloudflare-ddns, ddns-updater, inadyn, ddnss) erkennt HomeAtlas am Image; aus ihrer Umgebung werden nur
Hostnamen und die IPv4/IPv6-Schalter übernommen, nie Tokens oder Passwörter.

**cloudflared, Caddy und ddclient lesen (Erreichbarkeit).** HomeAtlas liest diese Konfigurationsdateien
per SSH, ohne auf dem Zielsystem etwas ausführen zu können, was nicht vorgesehen ist: Auf dem Zielsystem
gibt es einen eigenen Nutzer ohne Shell-Rechte, dessen Schlüssel in `authorized_keys` so steht (je
Datei ein Schlüssel):

```
restrict,from="<HomeAtlas-IP>",command="cat /etc/caddy/Caddyfile" ssh-ed25519 AAAA… homeatlas
```

HomeAtlas sendet je Quelltyp einen im Code festen Befehl (`cat`, ohne Pfad); welche Datei geliefert wird,
bestimmt allein dieser Eintrag. Die Firewall des Zielsystems lässt SSH nur von der HomeAtlas-IP zu. Der
Zugang (Kategorien „cloudflared-/Caddyfile-/ddclient-Konfiguration lesen“; Zielsystem, Benutzername, Port,
privater Schlüssel) braucht „Zum Auslesen verwenden“; die Quelle ist in den Einstellungen abschaltbar
(`scanEnableExposureFiles`). Gespeichert werden nur Hostnamen, Ziele, Anbieter und „Client-Zertifikat ja/nein“,
nie Passwörter, Tokens, Tunnel-Zugangsdaten oder die Datei selbst. Die cloudflared-Datei kann den Tunnel-Token
enthalten; er liegt kurz im Speicher und wird verworfen. Der SSH-Hostschlüssel wird wie bei den übrigen
Zugängen nicht geprüft.

**Passwörter verlassen den Server einzeln.** API-Schlüssel kommen maskiert zurück, ein
gespeichertes Passwort nur über `GET /api/accounts/{id}/secret` — genau eines, nur für
Administratoren. Es gibt keine Route, die den Zugangsspeicher im Klartext ausgibt.

**Diagnose-Werkzeuge ohne Shell.** Alles, was der Assistent ausführen kann, ist lesend (einzige
bewusste Ausnahme: Shelly-Relais und Home-Assistant-Lichter/-Schalter ein- und ausschalten sowie Rollos hoch/runter/stoppen; Garagen- und Hoftore, Türen und Entities ohne Rollo-`device_class` sind gesperrt), hat ein
Timeout und läuft über `create_subprocess_exec` mit Argumentliste. Ein Hostname mit `;` oder
Backticks ist ein Hostname, kein Befehl — und wird vorher gegen ein striktes Muster geprüft.
Port- und Webseiten-Prüfungen lehnen Ziele auf dem HomeAtlas-Server selbst (Loopback) und
Link-Local-Adressen ab, auch nach einer Weiterleitung; Geräte im Heimnetz bleiben prüfbar. Ohne
eingerichteten KI-Zugang schickt der Scan keine Gerätedaten an einen Anbieter.

**Anmelden ja, verändern nie.** Ist für ein Gerät ein Zugang hinterlegt *und* ausdrücklich zum
Auslesen freigegeben, meldet sich HomeAtlas an und liest Eckdaten. Dass dabei nichts verändert
wird, ist eine Eigenschaft des Codes, keine Zusicherung im Text:

- Die SSH-Befehle stehen als **Konstante** in `probe_auth._SSH_COMMANDS`. Es gibt keine
  Einstellung, keinen API-Parameter und kein KI-Werkzeug, das etwas hinzufügen könnte — sonst wäre
  daraus eine Fernsteuerung mit hübscher Oberfläche geworden.
- Jeder Befehl ist lesend und nicht-interaktiv: kein Paketmanager, keine Dienststeuerung, keine
  Umleitung, kein `sudo`. Fehlschläge werden geschluckt, damit ein fehlendes Programm nie in einen
  Zweitversuch mit gröberen Mitteln mündet.
- HTTP wird ausschließlich mit **GET** aufgerufen; bei TR-064 werden nur `GetInfo`-Aktionen
  gebaut — die `Set*`-Hälfte dieser Schnittstelle kommt im Quelltext nicht vor.
- **Opt-in pro Zugang.** Ohne den Haken „Zum Auslesen verwenden“ passiert nichts, und das
  Auslesen einzelner Geräte lässt sich unter *Einstellungen → Netzwerk-Scan* mit einem Schalter
  abschalten. Die Abfragen der Controller (UniFi, Omada, Proxmox, AdGuard) und weiterer Quellen haben
  jeweils eigene Schalter und melden sich mit ihrem Zugang an, solange diese aktiv sind.

Bewusste Abwägung: SSH-Hostschlüssel werden **nicht** geprüft. HomeAtlas hat keinen Vertrauensspeicher,
und die Alternative — die Verbindung zu jedem Gerät beim ersten Kontakt zu verweigern — würde die
Funktion in genau dem Netz unbrauchbar machen, das sie dokumentieren soll.

**SSH-Schlüssel und Passphrasen** liegen im selben verschlüsselten Feld wie Passwörter und
unterliegen denselben Regeln: nie in der Doku, nie beim KI-Anbieter, nur einzeln über die
Admin-Route abrufbar.

**Der Docker-Socket ist root-äquivalent.** Die Erkennung ruft ausschließlich GET-Endpunkte auf.
Schreibend nutzt ihn nur die Container-Steuerung für Administratoren (Starten, Stoppen, Neustarten,
Konsole). Das `:ro` in `docker-compose.yml` schützt nur die Socket-Datei, nicht die API dahinter:
Wer den Socket erreicht, kann auf dem Host viel. Wem das zu weit geht, entfernt die Zeile in
`docker-compose.yml`; alles außer Container-Erkennung und -Steuerung funktioniert weiter.

**Anmeldeschutz.** Nach wiederholten Fehlversuchen (Passwort oder Code) sperrt HomeAtlas weitere
Anmeldeversuche für bis zu 15 Minuten: von derselben Adresse für denselben Namen nach 5, für
beliebige Namen nach 20 Versuchen. Ein Code aus der Authenticator-App gilt nur einmal. Passwörter
müssen mindestens 10 Zeichen haben und entweder drei der vier
Zeichenarten enthalten oder ab 20 Zeichen als Wortfolge durchgehen — lange Passphrasen sind
stärker *und* merkbarer als kurze Sonderzeichen-Akrobatik. Die Zwei-Faktor-Anmeldung per
Authenticator-App (TOTP nach RFC 6238, ohne externen Dienst) ist für **jedes Konto Pflicht**:
Nach der ersten Anmeldung muss zuerst eine Authenticator-App eingerichtet werden, vorher
verweigert die API alles außer der Einrichtung selbst und der Abmeldung. Der zweite Faktor wird
erst scharf, nachdem ein funktionierender Code eingegeben wurde — eine abgebrochene Einrichtung
kann also niemanden aussperren. Selbst abschalten lässt er sich nicht; geht das Telefon verloren,
setzt ein Administrator den zweiten Faktor des Kontos zurück, und beim nächsten Anmelden wird er
neu eingerichtet.

**Zugriffsprotokoll.** Anmeldungen, Fehlversuche, Benutzeränderungen und *jedes Anzeigen eines
gespeicherten Passworts* landen im Protokoll. Gerade Letzteres ist für einen Zugangsspeicher der
Eintrag, den man später wirklich sucht.

**HomeAtlas ist kein Passwort-Manager.** Hier gehören Zugänge zur *Technik* hinein: Router,
NAS, Kundennummer beim Anbieter — damit man im Störungsfall drankommt. Für persönliche Passwörter
und Bankzugänge gehört ein echter Safe her: [Bitwarden](https://bitwarden.com/) (auch selbst
gehostet als [Vaultwarden](https://github.com/dani-garcia/vaultwarden)),
[KeePassXC](https://keepassxc.org/) oder [1Password](https://1password.com/). Die bieten
Browser-Integration, Freigaben und Notfallzugriff — Dinge, die diese App bewusst nicht macht.

**Kein HTTPS out of the box.** HomeAtlas ist für den Betrieb im eigenen LAN gedacht. Wer es von
außen erreichbar macht, gehört hinter einen Reverse Proxy mit TLS — und sollte sich vorher
überlegen, ob das wirklich sein muss.

---

## Wie die Erkennung funktioniert

| Quelle | Was sie beiträgt |
|---|---|
| **Ping + ARP** | Findet als Einzige Geräte, die sonst nichts beantworten. Selbst ein Host, der ICMP ignoriert, taucht in der Neighbour-Tabelle auf — die ARP-Auflösung passiert *vor* dem Ping |
| **Portscan** | Sagt, was ein Gerät *tut* — und über `ports.DEVICE_HINTS` oft, was es *ist* (9100 → Drucker, 8123 → Home Assistant, 1400 → Sonos) |
| **Reverse-DNS** | Der Router kennt meist die DHCP-Namen |
| **mDNS + SSDP/UPnP** | Die mit Abstand beste Quelle für Consumer-Technik: Drucker, Fernseher, Lautsprecher und Smart-Home-Zentralen nennen ihren eigenen Namen, Hersteller und Modell |
| **Docker-API** | Image, Compose-Projekt, Volumes, Port-Weiterleitungen, Neustart-Verhalten — genau die Fakten, die man ein halbes Jahr später sucht |

Die Namensgebung folgt einer festen Rangfolge: ein manuell in HomeAtlas gepflegter Name vor einem
in UniFi vergebenen Namen vor Selbstauskunft (UPnP `friendlyName`, dann mDNS-Name), DNS-Hostname,
Webseiten-Titel und „Hersteller + letztes IP-Oktett". Die KI-Einordnung läuft erst danach, nur für
Geräte, die dabei erstmals im Inventar auftauchen, und nur wenn die Regeln sie nicht sicher zuordnen konnten — ein eindeutig erkannter FRITZ!Box kostet
keine Tokens; bekannte Geräte werden bei späteren Scans nicht erneut gefragt (das Ergebnis bleibt erhalten). Bestehende Geräte werden nach dem Update nicht nachgezogen, und ein neues Gerät, das beim ersten Scan nicht eingeordnet werden konnte (kein KI-Zugang, Fehler, niedrige Konfidenz), wird nicht automatisch nachgeholt: dafür gibt es am Gerät (nur Admin) den Menüpunkt „KI-Einordnung wiederholen“ im „⋯“-Menü. Antworten mit niedriger Konfidenz werden verworfen: die regelbasierte Vermutung ist
besser als ein Schulterzucken. Selbst gemeldete Namen (UPnP, mDNS, Shelly-App-Name) benennt die KI nie um; den Gerätetyp darf sie weiterhin ergänzen.

### Geräte zusammenführen

Ein Gerät mit mehreren Interfaces (z. B. ein Gateway, das pro Subnetz einzeln gefunden wird) steht
zunächst mehrfach in der Liste. Als Admin führst du die Einträge zusammen: in der Detailansicht über
**„Zusammenführen…"** (dieses Gerät bleibt erhalten, du wählst das Duplikat und bestätigst) oder im
Inventar über die Auswahl mehrerer Geräte. Konten, Verlauf und Monitoring wandern zum behaltenen Gerät.

- **Dauerhaft:** Discovery-Schlüssel, IPs und MACs des entfernten Eintrags merkt sich das behaltene
  Gerät als Aliase. Spätere Scans ordnen diese Funde dem behaltenen Gerät zu, statt ein neues
  anzulegen. Die zusätzlichen Adressen zeigt die Detailansicht als „Weitere IPs".
- **Infos werden ergänzt:** Bei Konflikten gewinnt das behaltene Gerät. Leere Felder, Geräteinfos
  (UniFi, mDNS/UPnP, Prüfergebnisse) sowie offene Ports und Dienste des entfernten Eintrags kommen
  hinzu. Ports und Dienste merkt sich HomeAtlas je Adresse: Ein Scan einer Schnittstelle aktualisiert
  nur deren Ports, die der anderen bleiben erhalten. Die Dienste-Tabelle zeigt dann, unter welcher
  Adresse ein Port offen ist.
- **Hinweise „Doppelt?":** Bei gleichem Hostnamen oder gleichem selbstgemeldetem Namen (UPnP/mDNS)
  schlägt HomeAtlas im Inventar und in der Detailansicht ein Zusammenführen vor. Gleicher Hersteller
  und gleiches Modell sind kein Hinweis – zwei baugleiche Geräte sind normal. Teilen mehr als drei
  Geräte denselben Namen (z. B. ein Werks-Hostname wie „espressif"), gilt er als generisch und
  löst keinen Hinweis aus.
- **„Kein Duplikat"** blendet einen Hinweis dauerhaft aus, auch nach neuen Scans.
- **Ausnahme Controller-Funde:** Ein nur per IP gefundenes (geroutetes) Gerät wird automatisch mit
  dem UniFi-/Omada-Eintrag zusammengeführt, wenn genau ein Eintrag diese IP hat und die MACs nicht
  widersprechen (siehe [docs/multi-vlan.md](docs/multi-vlan.md)).
- Sonst wird **nie automatisch** zusammengeführt, nur nach Klick und Bestätigung. Ein
  manuelles Zusammenführen lässt sich nicht rückgängig machen.

---

## Konfiguration

| Umgebungsvariable | Standard | Bedeutung |
|---|---|---|
| `HOMEATLAS_PORT` | `8280` | Port, auf dem die Oberfläche lauscht |
| `HOMEATLAS_API_PORT` | `8281` | Port des Backends. Weil beide Container im **Host-Netz** laufen, sind das Ports des Docker-Hosts — sie kollidieren mit allem, was dort schon lauscht. Belegt? `ss -tlnp \| grep :8281` und einen freien wählen |
| `HOMEATLAS_DB_PATH` | `/data/homeatlas.db` | SQLite-Datenbank |
| `HOMEATLAS_KEY_PATH` | `/data/secret.key` | Verschlüsselungsschlüssel (wird automatisch erzeugt) |
| `HOMEATLAS_OUI_PATH` | `/data/oui.json` | Zwischenspeicher der IEEE-Herstellerdatenbank |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | — | Erstes Konto vorgeben statt generieren lassen |
| `TZ` | `Europe/Berlin` | Zeitzone für Anzeigen und Protokolle |

Scan-Verhalten (Bereiche, Ausnahmen, Timeouts, welche Quellen aktiv sind, ob die KI mitarbeitet)
wird in der Oberfläche unter *Einstellungen → Netzwerk-Scan* gepflegt.

**Zu scannende Netze:** Ist ein UniFi-Controller synchronisiert, listet *Einstellungen →
Netzwerk-Scan* dessen aktive Netze (Name, VLAN, CIDR) als Checkboxen. Der Scan nutzt die angehakten
Netze plus die Einträge im Freitextfeld „Weitere Netzwerk-Bereiche“ (ohne Duplikate). Ist nichts
angehakt und der Freitext leer, werden wie bisher die Netze der Host-Interfaces automatisch
ermittelt. Neu synchronisierte Netze sind nicht angehakt und mit „neu“ markiert. Geroutete Netze
(nicht am Host angeschlossen) werden gepingt, liefern aber weder ARP/MAC noch mDNS/SSDP; pro Netz
werden höchstens 1024 Adressen geprüft. Ungültige, abgeschnittene und ergebnislose Netze erscheinen
als Warnung im Scan-Log.

---

## Entwicklung

```bash
# Backend
cd backend
pip install -r requirements.txt
HOMEATLAS_DB_PATH=./dev.db HOMEATLAS_KEY_PATH=./dev.key ADMIN_PASSWORD=devpass123 \
  uvicorn app.main:app --reload --port 8000

# Frontend (proxyt /api automatisch auf :8000)
cd frontend
npm install
npm run dev
```

Tests und Lint fürs Backend: `pip install -r requirements-dev.txt`, dann `ruff check .` und
`python -m pytest -q` (läuft auch in der CI). Fürs Frontend startet die CI zusätzlich die gebauten
Images und klickt sich mit Playwright durch Login, MFA, Einrichtung und die wichtigsten Seiten
(`frontend/e2e/`). Architekturentscheidungen stehen in
[`docs/adr/`](docs/adr/README.md), die Spezifikation des heutigen Verhaltens (je Funktion, mit
Funktionsübersicht) in [`docs/specs/`](docs/specs/README.md).

**Mitwirken / Issues.** Fehler, Wünsche und Ideen bitte über die Issue-Formulare melden.
Bewertung, Planung und Umsetzung laufen teilweise über einen KI-Agenten mit menschlicher Freigabe –
der Ablauf ist in [`docs/ai-workflow/`](docs/ai-workflow/README.md) beschrieben.

Unter Windows fehlen `ip`, `ping` und `traceroute` in der Container-Form — Discovery und Diagnose
sind dort eingeschränkt, die Oberfläche und alles andere funktionieren.

---

## Bekannte Grenzen

- **Nur IPv4.** IPv6-Adressen, die sich per mDNS/SSDP melden, werden verworfen und nicht
  aktiv gescannt.
- **Netzbereiche bis /22.** Ein größerer Bereich wird auf die ersten 1024 Adressen begrenzt —
  ein versehentliches /16 wären 65.000 Hosts und ein praktisch endloser Scan.
- **Mehrere VLANs.** Netze, die nur über das Gateway erreichbar sind, liefern keine MAC/Hersteller
  und kein mDNS/SSDP; HomeAtlas warnt dafür bei jedem Scan. Details und Gateway-Einstellungen:
  [docs/multi-vlan.md](docs/multi-vlan.md).
- **Zufällige MAC-Adressen.** Moderne Telefone wechseln ihre Netzwerkkennung regelmäßig und
  können deshalb mehrfach im Inventar erscheinen. Solche Geräte sind intern als
  `randomizedMac` markiert.
- **Hersteller-Datenbank.** Ohne die IEEE-Liste (wird beim ersten Scan automatisch geladen, sonst
  manuell in den Einstellungen) ist die Herstellererkennung auf eine kleine, handgepflegte Liste
  beschränkt.

---

## Lizenz

Privates Projekt.
