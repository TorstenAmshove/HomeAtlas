# Constitution: übergreifende Prinzipien

> Stand: Commit 0159807. Quellen: `docs/adr/`, README „Sicherheit“, `CLAUDE.md`.
> Jede Regel ist markiert:
> **[Muss]**: fachlich oder sicherheitsrelevant. Eine Alternative soll sie erfüllen, egal mit welcher Technik.
> **[Impl]**: Technikwahl der heutigen Umsetzung. Eine Alternative darf sie ersetzen, solange die
> zugehörigen [Muss]-Regeln weiter gelten.
>
> Wer eine [Muss]-Regel für die Alternative ändern will, ändert sie hier und markiert die Änderung,
> statt sie in einer Capability-Spec still zu umgehen.

## 1. Produkt

- **P1 [Muss]** Selbst gehostet, eine Instanz pro Haushalt, Betrieb im eigenen LAN. Kein Cloud-Zwang;
  der einzige optionale Außenkontakt ist der gewählte LLM-Anbieter (mit Ollama: keiner).
- **P2 [Muss]** Zielgruppe der Ausgaben (Doku, Netzplan, Assistent) sind **technische Laien** im
  Haushalt. Sprache der Oberfläche und der Doku: Deutsch, verständlich, ohne Fachjargon wo vermeidbar.
- **P3 [Muss]** Die App dokumentiert das Netz; sie ist **kein Passwort-Manager** für persönliche
  Zugänge und **kein** Netzwerk-Management-System. Schreibende Gerätefunktionen sind Ausnahmen für
  Administratoren (siehe 3).
- **P4 [Muss]** Erkennung aus **mehreren unabhängigen Quellen**, weil keine allein alles sieht
  (Ping/ARP, Portscan, Reverse-DNS, mDNS, SSDP/UPnP, HTTP-Banner, Docker, Controller-APIs).
- **P5 [Muss]** Was ein Mensch von Hand gepflegt hat, überschreibt keine Automatik
  (Namen, Art, Bedeutung, Notizen, manuelle Doku-Notizen).

## 2. Rollen und Anmeldung

- **R1 [Muss]** Zwei Rollen: **ADMIN** (alles, inkl. Secrets und schreibender Gerätezugriff) und
  **MEMBER** (Doku, Inventar lesen, Assistent; nie ein Klartext-Secret).
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
- **R6 [Muss]** Zugriffsprotokoll für Anmeldungen, Fehlversuche, Benutzeränderungen und **jedes
  Anzeigen eines gespeicherten Passworts**, mit Zeit, Benutzer, IP, User-Agent und Erfolg.
- **R7 [Muss]** Erst-Admin: Gibt es noch keinen Benutzer, wird einer angelegt (Name/Passwort aus
  der Konfiguration oder generiert und **einmalig** im Log ausgegeben).
- **R8 [Muss]** WebSocket-Verbindungen (Konsolen) prüfen Sitzung, Rolle und Herkunft (Origin) wie
  normale Anfragen.

## 3. Lesen vs. Schreiben an Geräten

- **L1 [Muss]** Lesender und schreibender Gerätezugriff sind getrennte Pfade. Kein lesender Pfad
  kann über eine Einstellung, einen Parameter oder ein KI-Werkzeug schreibend werden.
  ([ADR 0002](../adr/0002-lese-schreib-trennung.md))
- **L2 [Muss]** Credentialed Probing ist **streng lesend**: SSH nur aus einer festen, im Code
  stehenden Befehlsliste (nicht erweiterbar, nicht interaktiv, kein `sudo`, kein Paketmanager, keine
  Dienststeuerung, keine schreibende Umleitung in Dateien; Pipes zu Lesewerkzeugen wie `base64` und
  `2>/dev/null` sind erlaubt);
  HTTP nur GET; TR-064 nur `Get*`-Aktionen; Docker-API nur GET.
- **L3 [Muss]** Ein Zugang wird nur benutzt, wenn er **ausdrücklich zum Auslesen freigegeben**
  ist (Opt-in je Zugang, Default aus). Das Auslesen pro Gerät lässt sich global abschalten
  (`scanUseCredentials`); Controller-Abfragen (UniFi, Omada, Proxmox, AdGuard) haben eigene Schalter.
  > OFFEN: Die README verspricht „komplett abschaltbar“; heute schaltet `scanUseCredentials` die
  > Controller-Abfragen nicht mit ab.
- **L3a [Muss]** Manche Plattformen brauchen zum Lesen einen Befehl, der formal in einen
  Konfigurationsmodus wechselt (TP-Link `configure` / `no clipaging` gegen Seitenumbruch). Erlaubt
  ist das nur, um die Ausgabe lesbar zu machen, nie, um etwas zu ändern.
- **L4 [Muss]** Schreibende Funktionen (Container steuern, Reboot, SSH-Konsole, Schlüssel ausrollen,
  Proxmox-Aktionen) sind nur für ADMIN und nur über die Oberfläche/API erreichbar, nie über
  Scan-Pipeline, Probes oder KI-Werkzeuge.
- **L5 [Muss]** Einzige Ausnahme: Ein/Aus-Schalten von Shelly-Relais und Home-Assistant
  `switch`/`light` per KI-Werkzeug `set_switch`, für alle Rollen. Erweiterungen brauchen eine
  bewusste Entscheidung. > OFFEN: für die Alternative übernehmen?
- **L6 [Impl]** Lese- und Schreibseite sind getrennte Module, die einander nicht importieren;
  gemeinsamer Code wird eher dupliziert als geteilt.
- **L7 [Muss, bewusste Abwägung]** SSH-Hostschlüssel werden nicht geprüft (kein Vertrauensspeicher;
  sonst wäre die Funktion im Zielnetz unbrauchbar). Eine Alternative darf das verbessern
  (z. B. Trust-on-first-use), muss es aber nicht.

## 4. KI-Assistent

- **K1 [Muss]** Die Werkzeugliste ist die **vollständige** Fähigkeitsgrenze des Modells: lesend
  plus begrenzte Live-Diagnosen plus die eine Ausnahme `set_switch` (L5). ([ADR 0004](../adr/0004-llm-faehigkeitsgrenze.md),
  [llm-tools](contracts/llm-tools.md))
- **K2 [Muss]** Gespeicherte Secrets erreichen **nie** ein Modell, einen Prompt, Anbieter-Logs oder
  den Chatverlauf. Werkzeuge, die ein Secret brauchen, nutzen es serverseitig.
- **K3 [Muss]** Live-Diagnosen laufen ohne Shell (Argumentliste), mit Timeout und mit strikt
  validierten Zielen (Hostname/IP/URL nach Muster).
- **K4 [Muss]** Werkzeugergebnisse sind in der Größe begrenzt; eine Kürzung wird dem Modell
  mitgeteilt. Die Zahl der LLM-Aufrufe pro Antwort ist begrenzt.
- **K5 [Muss]** Anbieter frei wählbar: Anthropic Claude, OpenAI, Google Gemini, DeepSeek, lokales
  Ollama. ([ADR 0006](../adr/0006-providerneutraler-llm-client.md))
- **K6 [Impl]** Eigener HTTP-Client statt Vendor-SDKs; Struktur parallel zum Schwesterprojekt
  GlucoSphere-Web.
- **K7 [Muss, solange Claude unterstützt wird]** An Anthropic keine Sampling-Parameter
  (`temperature`, `top_p`, `top_k`) und kein explizites `thinking` senden (HTTP 400 auf aktuellen
  Modellen). Signierte Thinking-Blöcke werden im nächsten Zug unverändert zurückgespielt.
- **K8 [Muss]** Dieselben Werkzeuge stehen über einen externen MCP-Endpunkt bereit, abgesichert
  über Tokens, die ein ADMIN anlegt und widerruft; der Tokenwert wird nur einmal angezeigt.
- **K9 [Muss]** Ein LLM klassifiziert nur, was die Regeln nicht sicher einordnen können; Antworten
  mit geringer Konfidenz werden verworfen; von Quellen gelieferte Namen/Arten werden nie
  überschrieben. Ohne konfigurierten Anbieter funktioniert alles außer Assistent und Klassifikation.

## 5. Zugangsdaten

- **Z1 [Muss]** Secrets (Passwörter, private Schlüssel, Passphrasen, Tokens, TOTP-Geheimnisse) sind
  at rest verschlüsselt.
  > OFFEN: Heute gilt das nicht für LLM-API-Schlüssel (Klartext im Settings-JSON), MCP-Tokens und
  > Session-Tokens (Klartext in ihren Tabellen) und nicht für die Kopie ausgelesener
  > Konfigurationsexporte in `systems.extra.probe`. Siehe [offene-punkte](offene-punkte.md) 1 und 2. Schutzziel: eine abhandengekommene **Datenbankkopie**, ausdrücklich nicht
  root auf dem Host. ([ADR 0007](../adr/0007-credentials-fernet-schluessel-im-volume.md))
- **Z2 [Muss]** Der Dienst startet nach einem Neustart **unbeaufsichtigt** (keine Passphrase beim Start).
- **Z3 [Muss]** Ein Secret verlässt den Server nur **einzeln**, nur für ADMIN, und jedes Anzeigen
  wird protokolliert. Keine Route gibt Secrets gesammelt oder im Klartext aus; API-Schlüssel in den
  Einstellungen kommen maskiert.
- **Z4 [Muss]** Secrets stehen nie in der generierten Dokumentation.
- **Z5 [Impl]** Fernet mit Schlüsseldatei neben der Datenbank im selben Volume; Backups müssen
  beides gemeinsam sichern.

## 6. Betrieb und Netzwerk

- **B1 [Muss]** Die Erkennung braucht direkten Zugang zum LAN des Hosts (ARP-Tabelle,
  mDNS/SSDP-Multicast). ([ADR 0003](../adr/0003-host-netzwerk-und-loopback-backend.md))
- **B2 [Muss]** Die API ist nur über das Frontend bzw. einen davor liegenden Proxy erreichbar,
  nicht direkt auf allen Schnittstellen des Hosts.
- **B3 [Impl]** Zwei Container mit `network_mode: host`; Backend bindet an `127.0.0.1:8281`, nginx
  im Frontend-Container auf `:8280` leitet `/api/*` weiter.
- **B4 [Muss]** Kein HTTPS eingebaut; Zugriff von außen nur hinter einem Reverse Proxy mit TLS.
- **B5 [Muss]** Der Docker-Socket ist optional. Erkennung und Probing lesen nur (GET); schreibend
  nutzt ihn nur die Container-Steuerung für ADMIN (siehe L4). Ohne Socket funktioniert alles außer
  Container-Erkennung und lokaler Container-Steuerung.
  > OFFEN: README „Sicherheit“ sagt „ausschließlich GET-Endpunkte“; das gilt nur für die Leseseite.
- **B6 [Muss]** Die Erkennung arbeitet unter Windows/Docker Desktop nur eingeschränkt (keine
  `ip`/`ping`/`traceroute`); das ist eine bekannte Grenze, kein Fehler.

## 7. Datenhaltung und Darstellung

- **D1 [Muss]** Eine Instanz, wenige tausend Datensätze; die Datenhaltung muss parallele Scans
  (Hintergrund-Threads) und Webanfragen vertragen.
- **D2 [Impl]** SQLite (WAL) über ein flaches Modul ohne ORM, camelCase-Spalten, JSON-Spalten.
  ([ADR 0005](../adr/0005-sqlite-ohne-orm.md), [data-model](contracts/data-model.md))
- **D3 [Muss]** Dokumentation ist versioniert; jeder frühere Stand jeder Seite bleibt abrufbar und
  wiederherstellbar. Manuelle Notizen werden von der Generierung nie verändert.
- **D4 [Muss]** Der Netzplan ist ein für Laien lesbares Bild mit fester Schichtenfolge von oben
  nach unten. Heute: Internet → Router → Verteilung → Wichtige Geräte; alle übrigen Geräte stehen
  gruppiert als Liste unter dem Bild ([topologie](capabilities/topologie/spec.md)).
  > OFFEN: ADR-0008 beschreibt „Server → Endgeräte“ als Ebenen und „Farbe nie einziges Signal“;
  > der Code weicht ab (im Kasten ist Farbe das einzige Statussignal). Für die Alternative festlegen.
- **D5 [Impl]** Netzplan wird serverseitig als SVG erzeugt, ohne Graph-Bibliothek im Browser,
  ohne Zoomen/Ziehen. ([ADR 0008](../adr/0008-topologie-als-server-svg.md))
- **D6 [Impl]** Frontend: React + react-router ohne State-Bibliothek, ein zentraler typisierter
  API-Client. Backend: Python/FastAPI.

## 8. Qualität

- **Q1 [Muss]** Jede Fähigkeit hat automatisierte Tests für ihre Akzeptanzszenarien.
- **Q2 [Muss]** Ein Browser-Smoke-Test läuft gegen die gebauten Images: Login → MFA-Einrichtung →
  Einrichtungsassistent → Übersicht → Doku-Seite → weitere Seiten; jeder Konsolenfehler lässt ihn
  scheitern (`frontend/e2e/smoke.spec.ts`).
