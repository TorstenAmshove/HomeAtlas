# Constitution: übergreifende Prinzipien

> Stand: Commit 0159807. Quellen: `docs/adr/`, README „Sicherheit“, `CLAUDE.md`.
> Jede Regel ist markiert:
> **[Muss]**: fachlich oder sicherheitsrelevant. Eine Alternative soll sie erfüllen, egal mit welcher Technik.
> **[Impl]**: Technikwahl der heutigen Umsetzung. Eine Alternative darf sie ersetzen, solange die
> zugehörigen [Muss]-Regeln weiter gelten.
>
> Woher eine Regel kommt und wie sie sich ändert:
> - **Mit ADR-Verweis**: Die Regel fasst eine Architekturentscheidung aus `docs/adr/` zusammen. Die
>   Begründung und die verworfenen Alternativen stehen nur im ADR, hier steht nur die Regel. In
>   HomeAtlas selbst ändert sich eine solche Regel nur über ein neues ADR, das das alte ersetzt;
>   danach wird sie hier nachgezogen und auf das neue ADR verlinkt.
> - **Ohne ADR-Verweis**: Die Regel wird hier gepflegt. Wer sie ändern will, ändert sie hier und
>   markiert die Änderung, statt sie in einer Capability-Spec still zu umgehen.
> - Eine Alternative (ein anderes Produkt aus diesen Specs) ist an die ADRs nicht gebunden: [Impl]-Regeln
>   darf sie ersetzen, eine [Muss]-Regel ändert sie hier und markiert die Änderung.
>
> `python docs/specs/trace_specs.py --check` scheitert, wenn eine Regel auf ein ersetztes oder
> fehlendes ADR verweist oder ein akzeptiertes ADR hier nicht vorkommt.

## 1. Produkt

- **P1 [Muss]** Selbst gehostet, eine Instanz pro Haushalt, Betrieb im eigenen LAN. Kein Cloud-Zwang;
  optionale Außenkontakte sind der gewählte LLM-Anbieter (mit Ollama: keiner) sowie, je einzeln
  abschaltbar und standardmäßig aus, die Cloudflare-API und die öffentliche DNS-Auflösung für die
  Erreichbarkeits-Ketten (nur lesend). ([ADR-0023](../adr/0023-keine-fernwartung.md))
- **P2 [Muss]** Zielgruppe der Ausgaben (Doku, Netzplan, Assistent) sind **technische Laien** im
  Haushalt. Sprache der Oberfläche und der Doku: Deutsch, verständlich, ohne Fachjargon wo vermeidbar.
- **P3 [Muss]** Die App dokumentiert das Netz; sie ist **kein Passwort-Manager** für persönliche
  Zugänge und **kein** Netzwerk-Management-System. Die einzige Steuerung ist das Schalten über
  Home Assistant (siehe 3); es gibt keine Fernwartung.
- **P4 [Muss]** Erkennung aus **mehreren unabhängigen Quellen**, weil keine allein alles sieht
  (Ping/ARP, Portscan, Reverse-DNS, mDNS, SSDP/UPnP, HTTP-Banner, Docker, Controller-APIs).
- **P5 [Muss]** Was ein Mensch von Hand gepflegt hat, überschreibt keine Automatik
  (Namen, Art, Bedeutung, Notizen, manuelle Doku-Notizen).

## 2. Rollen und Anmeldung

- **R1 [Muss]** Zwei Rollen: **ADMIN** (alles, inkl. Secrets) und
  **MEMBER** (Doku, Inventar lesen, Assistent; nie ein Klartext-Secret). Benutzernamen, URLs und
  Notizen von Zugängen dürfen MEMBER und das LLM sehen (#48). Unterhaltungen mit dem Assistenten
  sind je Benutzer getrennt, ADMIN sieht alle (#49).
- **R2 [Muss]** Rechte werden **serverseitig** durchgesetzt. Die Oberfläche blendet nur aus; eine
  reine UI-Änderung darf nie ändern, was die API erlaubt. Admin-Seiten sind auf beiden Seiten gesperrt.
- **R3 [Muss]** Zwei-Faktor-Anmeldung (TOTP, RFC 6238, ohne externen Dienst) ist für **jedes**
  Konto Pflicht. Bis zur Einrichtung verweigert die API alles außer Einrichtung und Abmeldung.
  Der zweite Faktor wird erst aktiv, wenn ein gültiger Code bestätigt wurde. Selbst abschalten
  ist nicht möglich; ein ADMIN kann ihn für ein Konto zurücksetzen.
- **R4 [Muss]** Reihenfolge nach dem Login: Anmeldung → MFA-Einrichtung → Einrichtungsassistent
  (nur beim ersten Mal) → App. Der Server erzwingt Anmeldung und MFA; den Einrichtungsassistenten
  sperrt heute nur die Oberfläche (`setupCompleted` wird serverseitig nicht geprüft).
  > OFFEN: Soll eine Alternative auch den Setup-Schritt serverseitig erzwingen?
- **R5 [Muss]** Passwortrichtlinie: mindestens 10 Zeichen und entweder drei der vier Zeichenarten
  oder ab 20 Zeichen als Passphrase.
- **R5a [Muss]** Anmeldeversuche werden gedrosselt (Sperre nach wiederholten Fehlversuchen je
  Name+Quelle, Quelle und Name); ein TOTP-Code ist nur einmal gültig.
- **R6 [Muss]** Zugriffsprotokoll für Anmeldungen, Fehlversuche, Benutzeränderungen und **jedes
  Anzeigen eines gespeicherten Passworts**, mit Zeit, Benutzer, IP, User-Agent und Erfolg.
- **R7 [Muss]** Erst-Admin: Gibt es noch keinen Benutzer, wird einer angelegt (Name/Passwort aus
  der Konfiguration, sofern es R5 erfüllt, sonst generiert und **einmalig** im Log ausgegeben).

## 3. Lesen vs. Schreiben an Geräten

- **L1 [Muss]** Lesender und schreibender Gerätezugriff sind getrennte Pfade. Kein lesender Pfad
  kann über eine Einstellung, einen Parameter oder ein KI-Werkzeug schreibend werden.
  ([ADR-0023](../adr/0023-keine-fernwartung.md))
- **L2 [Muss]** Credentialed Probing ist **streng lesend**: SSH nur aus einer festen, im Code
  stehenden Befehlsliste (nicht erweiterbar, nicht interaktiv, kein `sudo` (einzige Ausnahme: der feste Befehl `nft -j list ruleset` der Firewall-Quelle, per `authorized_keys` und sudoers nur dafür freigegeben), kein Paketmanager, keine
  Dienststeuerung, keine schreibende Umleitung in Dateien; Pipes zu Lesewerkzeugen wie `base64` und
  `2>/dev/null` sind erlaubt);
  Ausnahme: Dateilesen per SSH-Forced-Command aus festen Befehlskonstanten je Quelltyp (kein Pfad,
  kein Parameter; Erreichbarkeits- und Firewall-Quellen); HTTP nur GET (Ausnahme: im Live-Zugriff `unifi_live.py` höchstens ein lesender POST für Events, L8; Proxmox-Live, L9, nur GET); TR-064/IGD nur `Get*`-Aktionen (die öffentliche Adresse der FRITZ!Box ohne Zugangsdaten); Docker-API nur GET; Home-Assistant-WebSocket nur
  `trace/list`, `trace/get` und `system_log/list`.
  ([ADR-0023](../adr/0023-keine-fernwartung.md))
- **L3 [Muss]** Ein Zugang wird nur benutzt, wenn er **ausdrücklich zum Auslesen freigegeben**
  ist (Opt-in je Zugang, Default aus). Das Auslesen pro Gerät lässt sich global abschalten
  (`scanUseCredentials`); Controller-Abfragen (UniFi, Omada, Proxmox, AdGuard) haben eigene Schalter.
  Das gilt auch für die Werkzeuge des Assistenten (`list_switches`, `set_switch` für Home Assistant,
  `get_ha_*`, `get_unifi_*`, `get_proxmox_*`).
- **L3a [Muss]** Manche Plattformen brauchen zum Lesen einen Befehl, der formal in einen
  Konfigurationsmodus wechselt (TP-Link `configure` / `no clipaging` gegen Seitenumbruch). Erlaubt
  ist das nur, um die Ausgabe lesbar zu machen, nie, um etwas zu ändern.
- **L4 [Muss]** HomeAtlas hat keine Fernwartung: kein Befehl auf Geräten, keine Konsole, keine
  Container-/Proxmox-Steuerung, kein Neustart, kein Erzeugen oder Verteilen von SSH-Schlüsseln.
  Verwaltung erfolgt über externe Werkzeuge. ([ADR-0023](../adr/0023-keine-fernwartung.md))
- **L5 [Muss]** Einzige Schreibfähigkeit: Ein/Aus-Schalten von Home-Assistant `switch`/`light` sowie
  Auf/Zu/Stopp (keine Position) von Home-Assistant-Rollos (`cover` mit `device_class`
  blind/shade/shutter/curtain/awning; Garagen-/Hoftore, Türen, Fenster und Entities ohne
  `device_class` gesperrt) per KI-Werkzeug `set_switch`, für alle Rollen und MCP-Clients, ohne
  Rückfrage (bestätigt in #43, #99). Kein direktes Schalten von Shelly-Geräten; jeder Vorgang wird mit
  Auslöser protokolliert. Weitere Aktionen nur nativ in `switch_admin.py`, nur über `tools.py`, je Aktion
  mit eigenem ADR und fester Allowlist. ([ADR-0023](../adr/0023-keine-fernwartung.md))
- **L6 [Impl]** Lese- und Schreibseite (`switch_admin.py`) sind getrennte Module, die einander nicht importieren;
  gemeinsamer Code wird eher dupliziert als geteilt. ([ADR-0023](../adr/0023-keine-fernwartung.md))
- **L8 [Muss]** Live-Zugriff auf die klassische UniFi-API (`unifi_live.py`) ist nur lesend: Auth
  allein per `X-API-Key`, feste Endpunkt-Allowlist (GET plus genau ein lesender POST für Events, `get_unifi_events`), Feld-Positivliste,
  höchstens 7 Tage, begrenzte Menge, nichts wird gespeichert. Importiert kein `*_admin`-Modul und
  wird nicht von Scan-Modulen importiert. ([ADR-0023](../adr/0023-keine-fernwartung.md))
- **L9 [Muss]** Live-Zugriff auf die Proxmox-API (`proxmox_live.py`) ist nur lesend: nur GET auf eine feste
  Pfad-Allowlist, Auth allein mit dem API-Token des Zugangs der Kategorie `proxmox` (mit Opt-in), Feld-Positivliste,
  kein Freitext des Gasts, kein Aufgaben-Log-Text, begrenzte Menge, nichts wird gespeichert. Importiert kein
  `*_admin`- und kein Scan-Modul; höchstens `tools.py` importiert es. ([ADR-0023](../adr/0023-keine-fernwartung.md))
- **L7 [Muss, bewusste Abwägung]** SSH-Hostschlüssel werden nicht geprüft (kein Vertrauensspeicher;
  sonst wäre die Funktion im Zielnetz unbrauchbar). Eine Alternative darf das verbessern
  (z. B. Trust-on-first-use), muss es aber nicht.

## 4. KI-Assistent

- **K1 [Muss]** Die Werkzeugliste ist die **vollständige** Fähigkeitsgrenze des Modells: lesend
  plus begrenzte Live-Diagnosen plus die eine Ausnahme `set_switch` (L5) die lesenden UniFi-Live-Abfragen (L8) und die lesenden Proxmox-Live-Abfragen (L9) und den lesenden Live-Status lokaler Container (`get_container_status`, nur `GET /containers/json`, kein Inspect). ([ADR-0023](../adr/0023-keine-fernwartung.md),
  [llm-tools](contracts/llm-tools.md))
- **K2 [Muss]** Gespeicherte Secrets erreichen **nie** ein Modell, einen Prompt, Anbieter-Logs oder
  den Chatverlauf. Werkzeuge, die ein Secret brauchen, nutzen es serverseitig. ([ADR-0023](../adr/0023-keine-fernwartung.md))
- **K3 [Muss]** Live-Diagnosen laufen ohne Shell (Argumentliste), mit Timeout und mit strikt
  validierten Zielen (Hostname/IP/URL nach Muster). ([ADR-0023](../adr/0023-keine-fernwartung.md))
- **K4 [Muss]** Werkzeugergebnisse sind in der Größe begrenzt; eine Kürzung wird dem Modell
  mitgeteilt. Die Zahl der LLM-Aufrufe pro Antwort ist begrenzt.
- **K5 [Muss]** Anbieter frei wählbar: Anthropic Claude, OpenAI, Google Gemini, DeepSeek, lokales
  Ollama. ([ADR-0020](../adr/0020-llm-client-ohne-schwesterprojekt.md))
- **K6 [Impl]** Eigener HTTP-Client statt Vendor-SDKs. ([ADR-0020](../adr/0020-llm-client-ohne-schwesterprojekt.md))
- **K7 [Muss, solange Claude unterstützt wird]** An Anthropic keine Sampling-Parameter
  (`temperature`, `top_p`, `top_k`) und kein explizites `thinking` senden. Signierte Thinking-Blöcke
  werden im nächsten Zug unverändert zurückgespielt. ([ADR-0020](../adr/0020-llm-client-ohne-schwesterprojekt.md))
- **K8 [Muss]** Dieselben Werkzeuge stehen über einen externen MCP-Endpunkt bereit, abgesichert
  über Tokens, die ein ADMIN anlegt und widerruft; der Tokenwert wird nur einmal angezeigt.
- **K9 [Muss]** Ein LLM klassifiziert nur, was die Regeln nicht sicher einordnen können; Antworten
  mit geringer Konfidenz werden verworfen; von Quellen gelieferte Namen/Arten werden nie
  überschrieben. Ohne konfigurierten Anbieter funktioniert alles außer Assistent und Klassifikation.

## 5. Zugangsdaten

- **Z1 [Muss]** Secrets (Passwörter, private Schlüssel, Passphrasen, Tokens, TOTP-Geheimnisse) sind
  at rest verschlüsselt; das gilt auch für LLM-API-Schlüssel und ausgelesene Konfigurationsexporte
  (keine Klartext-Kopie beim Gerät). Schutzziel: eine abhandengekommene **Datenbankkopie**,
  ausdrücklich nicht root auf dem Host. ([ADR-0007](../adr/0007-credentials-fernet-schluessel-im-volume.md))
  > OFFEN: MCP-Tokens und Session-Tokens liegen im Klartext in ihren Tabellen (Hashing erwägen).
- **Z2 [Muss]** Der Dienst startet nach einem Neustart **unbeaufsichtigt** (keine Passphrase beim Start).
  ([ADR-0007](../adr/0007-credentials-fernet-schluessel-im-volume.md))
- **Z3 [Muss]** Ein Secret verlässt den Server nur **einzeln**, nur für ADMIN, und jedes Anzeigen
  wird protokolliert. Keine Route gibt Secrets gesammelt oder im Klartext aus; API-Schlüssel in den
  Einstellungen kommen maskiert. ([ADR-0007](../adr/0007-credentials-fernet-schluessel-im-volume.md))
- **Z4 [Muss]** Secrets stehen nie in der generierten Dokumentation.
- **Z5 [Impl]** Fernet mit Schlüsseldatei neben der Datenbank im selben Volume; Backups müssen
  beides gemeinsam sichern. ([ADR-0007](../adr/0007-credentials-fernet-schluessel-im-volume.md))

## 6. Betrieb und Netzwerk

- **B1 [Muss]** Die Erkennung braucht direkten Zugang zum LAN des Hosts (ARP-Tabelle,
  mDNS/SSDP-Multicast). ([ADR-0003](../adr/0003-host-netzwerk-und-loopback-backend.md))
- **B2 [Muss]** Die API ist nur über das Frontend bzw. einen davor liegenden Proxy erreichbar,
  nicht direkt auf allen Schnittstellen des Hosts. ([ADR-0003](../adr/0003-host-netzwerk-und-loopback-backend.md))
- **B3 [Impl]** Zwei Container mit `network_mode: host`; Backend bindet an `127.0.0.1:8281`, nginx
  im Frontend-Container auf `:8280` leitet `/api/*` weiter. ([ADR-0003](../adr/0003-host-netzwerk-und-loopback-backend.md))
- **B4 [Muss]** Kein HTTPS eingebaut; Zugriff von außen nur hinter einem Reverse Proxy mit TLS.
- **B5 [Muss]** Der Docker-Socket ist optional und wird nur gelesen (GET). Ohne Socket funktioniert alles außer
  Container-Erkennung und dem Live-Container-Status. Ein Socket-Proxy steht aus (#101).
- **B6 [Muss]** Die Erkennung arbeitet unter Windows/Docker Desktop nur eingeschränkt (keine
  `ip`/`ping`/`traceroute`); das ist eine bekannte Grenze, kein Fehler. ([ADR-0003](../adr/0003-host-netzwerk-und-loopback-backend.md))

## 7. Datenhaltung und Darstellung

- **D1 [Muss]** Eine Instanz, wenige tausend Datensätze; die Datenhaltung muss parallele Scans
  (Hintergrund-Threads) und Webanfragen vertragen. ([ADR-0010](../adr/0010-db-als-paket.md))
- **D2 [Impl]** SQLite (WAL) ohne ORM; SQL nur im Paket `backend/app/db/` (ein Modul je Entität),
  camelCase-Spalten, JSON-Spalten. ([ADR-0010](../adr/0010-db-als-paket.md), [data-model](contracts/data-model.md))
- **D3 [Muss]** Dokumentation ist versioniert; jeder frühere Stand jeder Seite bleibt abrufbar und
  wiederherstellbar. Manuelle Notizen werden von der Generierung nie verändert.
- **D4 [Muss]** Der Netzplan ist ein für Laien lesbares Bild mit fester Schichtenfolge von oben
  nach unten. Heute: Internet → Router → Verteilung → Wichtige Geräte; alle übrigen Geräte stehen
  gruppiert als Liste unter dem Bild ([topologie](capabilities/topologie/spec.md)).
  ([ADR-0009](../adr/0009-netzplan-ebenen-ist-stand.md), ersetzt ADR-0008.)
- **D5 [Impl]** Netzplan wird serverseitig als SVG erzeugt, ohne Graph-Bibliothek im Browser,
  ohne Zoomen/Ziehen. ([ADR-0009](../adr/0009-netzplan-ebenen-ist-stand.md))
- **D6 [Impl]** Frontend: React + react-router ohne State-Bibliothek, ein zentraler typisierter
  API-Client. Backend: Python/FastAPI, Routen in einem Modul je Fähigkeitsgruppe
  (`backend/app/routes/`), gemeinsame Rollenprüfung in `backend/app/deps.py`.

## 8. Qualität

- **Q1 [Muss]** Jede Fähigkeit hat automatisierte Tests für ihre Akzeptanzszenarien.
- **Q2 [Muss]** Ein Browser-Smoke-Test läuft gegen die gebauten Images: Login → MFA-Einrichtung →
  Einrichtungsassistent → Übersicht → Doku-Seite → weitere Seiten; jeder Konsolenfehler lässt ihn
  scheitern (`frontend/e2e/smoke.spec.ts`).
