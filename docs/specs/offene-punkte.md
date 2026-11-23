# Offene Punkte

Alle `OFFEN`-Markierungen der Capability-Specs: Unklarheiten, Widersprüche zwischen Code und
Doku, Verhalten, das eher nach Bug als nach Absicht aussieht. Vor dem Bau einer Alternative
entscheiden: **übernehmen**, **ändern** (in der Spec festhalten) oder **weglassen**. Viele Punkte
betreffen auch HomeAtlas selbst und eignen sich als Issues.

Jeder Punkt der Liste unten trägt am Ende `→ #N`, das GitHub-Issue, in dem er bearbeitet wird
(mehrere zusammengehörige Punkte teilen sich ein Issue), oder die Entscheidung, die ihn erledigt hat.
Ohne Verweis sind nur die Punkte zu Omada und TP-Link, für sie gibt es noch kein Issue.

## Zuerst ansehen

Sicherheitsrelevant. Die ersten beiden sind am Code nachgeprüft (Commit 0159807). Jeder Punkt ist
ein GitHub-Issue.

| # | Punkt | Specs | Issue |
|---|---|---|---|
| 1 | **Behoben (fix/secrets-at-rest).** **Konfigurationsexporte im Klartext für MEMBER und LLM** (nachgeprüft). Ausgelesene Gerätekonfigurationen (`config_export`, `omada_backup`) liegen verschlüsselt in den Konfigurationsversionen, zusätzlich aber unverschlüsselt in `systems.extra.probe` (`backend/app/pipeline.py:115`, `backend/app/main.py:1391`). Von dort gehen sie über `GET /api/systems*` an MEMBER und landen in der generierten Doku (`backend/app/docs.py:283`), die das LLM per `get_documentation` liest. Zusätzlich gibt `GET …/config-versions/{id}` den entschlüsselten Inhalt an MEMBER (`backend/app/main.py:1413`). Exporte können SNMP-Communities, RADIUS-Secrets und WLAN-Schlüssel enthalten. Verstößt gegen Constitution R1, K2, Z4. | credentialed-probing, inventar, dokumentation | #41 |
| 2 | **Behoben (fix/secrets-at-rest).** **LLM-API-Schlüssel im Klartext gespeichert** (nachgeprüft). `claudeApiKey` usw. liegen unverschlüsselt im Settings-JSON (`backend/app/db.py:474`); der Kommentar in `backend/app/db.py:447` behauptet das Gegenteil. Die API maskiert sie korrekt. Verstößt gegen Z1. | einstellungen-und-llm-provider | #42 |
| 3 | **Entschieden: bleibt für alle Rollen; Shelly-Prüfung und Auslöser im Protokoll umgesetzt (feat/chat-owner-and-switch-audit).** **`set_switch` ohne Rolle und Bestätigung.** Jede Rolle und jeder MCP-Token kann Shelly-Relais und HA-`switch`/`light` schalten (ADR-0002/0004 erlauben das ausdrücklich). Offen sind: keine Prüfung, ob das Ziel wirklich ein Shelly ist; kein Benutzer oder Token im Protokoll; Prompt-Injection kann einen Schaltvorgang auslösen; README und MCP-Tab sagen „nur lesend“. | assistent-chat-und-mcp, remote-admin | #43 |
| 4 | **Behoben:** `http_check`/`check_port` (fix/diagnostics-and-defaults), Linkprüfung der Klassifikation und frei eingebbare LLM-Adresse (#114, gemeinsame Prüfung in `netguard`). **`http_check` als SSRF-Fläche.** MEMBER, Assistent und MCP-Clients können serverseitig beliebige URLs abrufen, auch `127.0.0.1` und interne Dienste. Das Gleiche gilt für die Linkprüfung der Klassifikation und für „Testen“/„Modelle laden“ mit frei eingebbarer Adresse. | diagnose, klassifikation-llm, einstellungen-und-llm-provider | #44 |
| 5 | **Behoben (fix/login-hardening).** **Kein Brute-Force-Schutz, keine TOTP-Replay-Sperre.** Weder Rate-Limit noch Kontosperre; ein TOTP-Code ist im ~90-s-Fenster mehrfach gültig. | auth-und-rollen | #45 |
| 6 | **Behoben (fix/diagnostics-and-defaults).** **Standard: KI-Einordnung an, Anbieter DeepSeek.** Jeder Scan schickt Geräteangaben an DeepSeek, auch ohne API-Schlüssel (dann 401). Netzwerkfehler des Anbieters lassen den ganzen Scan scheitern. | klassifikation-llm, discovery-und-scan | #46 |
| 7 | **Behoben (fix/diagnostics-and-defaults).** **`PATCH /api/accounts/{id}` setzt bei Teil-Body Felder zurück**, auch das Opt-in `allowProbe`. Beim Ausrollen eines SSH-Schlüssels wird der editierbare Notizinhalt nach `authorized_keys` geschrieben. | zugangsdaten | #47 |
| 8 | **Entschieden: in Ordnung, solange keine Secrets (geschlossen).** **MEMBER sieht Zugangs-Metadaten** (Benutzername, URL, Notizen) über `GET /api/systems/{id}`, die Doku und `list_accounts`, obwohl die Zugangs-API admin-only ist. | inventar, dokumentation, assistent-chat-und-mcp, zugangsdaten | #48 |
| 9 | **Behoben (feat/chat-owner-and-switch-audit).** **Chats ohne Besitzer.** Jeder Benutzer sieht und löscht alle Chats. | assistent-chat-und-mcp | #49 |
| 10 | **Behoben (#40).** **README-Aussage zum Docker-Socket stimmt nicht.** Die README sagt „nur GET“; `docker_admin` sendet POST (Container steuern). | remote-admin | #50 |

## Widersprüche zwischen Doku und Code

Bereinigt in #50: README (Docker-Socket, Ausnahme `set_switch`), `CLAUDE.md` (Scan-Reihenfolge,
Netzplan-Ebenen, `set_switch`), ADR-0009 für die Netzplan-Ebenen. Behoben in #39 (PR #61): Der
KI-Name überschreibt keine Selbstauskunft-Namen (UPnP/mDNS) mehr. Offen bleiben:

- Netzwerkressourcen kommen nur von UniFi, nicht von Omada (netzwerkressourcen-vlans).

<!-- Ab hier erzeugt von trace_specs.py -->

## Alle Punkte je Fähigkeit (60)

### [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md) (1)

1. `list_switches` fragt bei jedem Aufruf live alle freigegebenen HA-Instanzen ab (kein Cache). → #121

### [auth-und-rollen](capabilities/auth-und-rollen/spec.md) (11)

1. `DELETE /api/users/{id}` schreibt keinen Protokolleintrag, obwohl die AccessLogPage ein Label `user.delete` kennt und README „Benutzeränderungen“ als protokolliert nennt (wirkt wie Bug). → #122
2. `DELETE /api/users/{id}` antwortet für unbekannte IDs mit `{ok: true}` statt 404 (PATCH/mfa-reset liefern 404). → #123
3. PATCH `/api/users/{id}` ist nicht atomar: Anzeigename/Rolle werden gespeichert, bevor ein zu schwaches `newPassword` mit 400 abgelehnt wird. → #123
4. POST `/api/users` mappt unbekannte Rollen still auf MEMBER, PATCH antwortet 400 – uneinheitlich. → #123
5. AccessLogPage kennt Label `mfa.disable` (nie geschrieben). (`mfa.reset` hat seit PR 6 ein Label und gilt als sicherheitsrelevant.) → #122
6. Session-Cookie ohne `Secure`-Flag, auch hinter TLS-Proxy. → #115
7. `X-Real-IP` wird ungeprüft übernommen; sicher nur, solange das Backend ausschließlich über nginx erreichbar ist (ADR-0003). → #115
8. Benutzernamen sind case-sensitiv und werden weder getrimmt noch validiert (außer ≥ 1 Zeichen). → #123
9. Selbst-Herabstufung eines ADMIN ist erlaubt, solange ein weiterer ADMIN existiert; die eigene UI-Ansicht bleibt bis zum Reload Admin. → #123
10. WebSocket-Check akzeptiert fehlenden `Origin`-Header; Docstring nennt die Bedingung „same bar as current_user“, prüft aber zusätzlich ADMIN. → #115
11. `GET /api/health` ist unauthentifiziert und verrät `userCount`; das Frontend nutzt das Feld nicht. → #115

### [credentialed-probing](capabilities/credentialed-probing/spec.md) (5)

1. TP-Link-Pager-Abschaltung nutzt `configure` / `no clipaging` – ein Konfigurationsmodus-Befehl, entgegen „kein Config-Mode“. Ob die Einstellung persistent in der Running-Config landet, ist ungeprüft.
2. Manuelles Auslesen behandelt `omada`/`proxmox`/`adguard`-Zugänge nicht (sie gehen an `probe_auth.probe_system`, das sie ignoriert) → bei solchen Geräten `ran = false` ohne Grund. Ebenso ignoriert es `scanUseCredentials`/`scanEnable*`, den Standard-Zugang, ARP-Lernen, Druckerzuordnung, `os`/`model`-Füllung und Fehlerereignisse. → #135
3. Im Vollscan nutzen Controller-Probes alle freigegebenen Zugänge der Kategorie, beim manuellen Auslesen nur die dem Gerät (direkt/per Zuordnung) zugeordneten – uneinheitlich. → #135
4. `omada_backup` läuft auf jedem Linux-Host und wird Base64-kodiert als Fakt gespeichert; ein Restore ist bewusst nicht vorgesehen, Nutzen der Speicherung ist unklar.
5. Omada liest nur Seite 1 (Geräte 100, Clients 500); größere Sites werden still abgeschnitten. Ein `errorCode` bei Geräten überspringt auch die Clients der Site.

### [dashboard](capabilities/dashboard/spec.md) (0)


### [diagnose](capabilities/diagnose/spec.md) (0)


### [discovery-und-scan](capabilities/discovery-und-scan/spec.md) (1)

1. Ungültiger Freitext-Bereich (z. B. „bad“) plus ein mDNS/SSDP-Fund außerhalb von `alive` führt in `discovery.py:859` zu `ValueError` aus `ip_network` und lässt den ganzen Scan scheitern. → #137

### [dokumentation](capabilities/dokumentation/spec.md) (5)

1. `POST /api/docs/{slug}/reset` mit unbekanntem Slug liefert 200 mit `page: null` statt 404. → #140
2. `GET /api/docs/{slug}/versions` mit unbekanntem Slug liefert leere Liste statt 404. → #140
3. `PUT /api/docs/{slug}` ohne Feld `bodyMd` speichert leeren Text (keine Validierung). → #140
4. Kapitel, deren Slug nicht mehr definiert ist, werden nie gelöscht (`db.delete_doc_page` ungenutzt). → #140
5. Benutzernamen und URLs von Zugängen sind über die Doku für MEMBER sichtbar, obwohl die Zugangs-API admin-only ist. Ebenso Gerätenotizen und ausgelesene Gerätewerte — falls dort Geheimnisse stehen, landen sie in der Doku. → entschieden in #48: in Ordnung, solange keine Secrets

### [einstellungen-und-llm-provider](capabilities/einstellungen-und-llm-provider/spec.md) (0)


### [inventar](capabilities/inventar/spec.md) (1)

1. `GET /api/systems/{id}` liefert MEMBER die Zugangs-Metadaten (Label, Benutzername, URL, Notizen) des Geräts; nur die UI blendet sie aus. Gewollt? → entschieden in #48: in Ordnung, solange keine Secrets

### [klassifikation-llm](capabilities/klassifikation-llm/spec.md) (5)

1. Weil `importance` nach Normalisierung nie leer ist, überschreibt die KI-Wichtigkeit immer die regelbasierte – auch beim Gateway (`critical`), sobald es Kandidat ist (z. B. kein kuratierter Doku-Link bei Nicht-AVM-Routern). Ebenso überschreibt eine ungültige KI-`kind` (→ `other`) eine korrekte Regel-Art wie `router`. → #142
2. Ein sicher erkanntes Gerät wird schon Kandidat, wenn nur der Doku-Link fehlt. → #142
3. Nur exakt `"low"` wird verworfen; „LOW“, „niedrig“ o. Ä. gelten als akzeptiert. → #142
4. Gleiche IP in mehreren Funden (Netzwerk-Fund plus UniFi/Omada/Proxmox/AdGuard) – mehrere Belegsätze pro IP im selben Stapel möglich, der letzte gewinnt, und das Ergebnis wird auf alle Funde dieser IP angewandt. → #142
5. Der Prompt verlangt dieselbe Reihenfolge wie die Eingabe; der Code ordnet ausschließlich per IP zu (Reihenfolge irrelevant) – unschädlich, aber Anforderung an Modell überflüssig. → #142

### [monitoring](capabilities/monitoring/spec.md) (5)

1. `unknown` (z. B. Ping-Aufruf wirft) setzt den Fehlerzähler zurück und wird sofort übernommen; ein Gerät kann so `offline → unknown → offline` flattern und jeweils Ereignisse erzeugen. → #130
2. `monitorEvents` hat keine Aufbewahrungsgrenze (im Gegensatz zu `deviceErrorEvents`/`accessLog`); wächst bei flatternden Geräten unbegrenzt. → #130
3. Rückkehr auf `online` nach Ausfall erzeugt kein Fehler-/Info-Ereignis am Gerät, nur ein `monitorEvents`-Eintrag – gewollt? → #130
4. `intervalSeconds` in `GET /api/monitor` ist der ungeklemmte Einstellungswert, nicht das tatsächlich verwendete Intervall; `monitorTimeoutMs` hat serverseitig keine Obergrenze. → #130
5. Für Docker-Container (Art `container`, teilen die Host-IP) gibt es keine typischen Ports; ohne offene Ports prüft der Monitor per Ping effektiv nur den Host. → #130

### [netzwerkressourcen-vlans](capabilities/netzwerkressourcen-vlans/spec.md) (3)

1. Fähigkeitsbeschreibung nennt Omada und Discovery-Subnetze als Quelle; im Code liefert nur UniFi Netzwerkressourcen. Soll eine Alternative Omada-Netze übernehmen?
2. Notiz-Änderung erzeugt keinen Eintrag im Zugriffsprotokoll. → #122
3. Der manuelle Abgleich beim Verbindungstest (`backend/app/routes/systems.py:262`) nutzt dieselbe `sync_network_resources` und zählt `emptyScans` mit; zwei Klicks bei leer gemeldetem Bereich deaktivieren dessen Ressourcen also ebenso wie zwei Scans. Gewollt?

### [remote-admin](capabilities/remote-admin/spec.md) (3)

1. Prompt-Injection-Risiko: Inhalte aus Inventar/Doku könnten das Modell zu `set_switch` ohne Rückfrage verleiten. → entschieden in #43
2. Assistent schaltet bei Shelly immer Kanal 0 (bewusst; ein Kanalparameter für `set_switch` erweitert die ADR-Ausnahme). Bereichsprüfung der REST-Route behoben (#147).
3. Keine Tests für die drei WebSocket-Konsolen, lokale Container-Aktionen, Shelly/HA-Schalten und die Origin-Prüfung. → #148

### [setup-wizard](capabilities/setup-wizard/spec.md) (7)

1. `POST /api/setup` prüft nicht, ob das Setup schon abgeschlossen ist; erneuter Aufruf legt Geräte/Konten doppelt an und überschreibt `homeName`/`scanSubnets`. → #149
2. Antwortfeld `accounts` zählt Gerätezugänge nicht mit – gewollt oder Ungenauigkeit? → #149
3. Keine Validierung der `scanSubnets`-Einträge; ungültiger Freitext landet in den Einstellungen (Verhalten im Scan siehe [discovery-und-scan](../discovery-und-scan/spec.md)). → #137
4. Leerer `homeName` wird gespeichert; Doku/Topologie/Assistent fallen dann teils auf Ersatztexte zurück. → #149
5. `GET /api/health` ist ohne Login erreichbar und verrät `userCount`; das Frontend nutzt das Feld nicht. → #115
6. Art→Wichtigkeit (`router/server/nas/heating` → kritisch) ist hart verdrahtet; `network` (Switch/AP) wird nicht kritisch – Absicht? → #149
7. Kein Duplikatabgleich mit bereits gescannten Geräten gleicher IP; ein späterer Scan muss das zusammenführen (siehe [inventar](../inventar/spec.md)). → #149

### [topologie](capabilities/topologie/spec.md) (6)

1. ADR-0008 und CLAUDE.md beschreiben die Ebenen „Server → Endgeräte“ und „Container innerhalb ihres Hosts“; das Bild zeichnet aber nur „Wichtige Geräte“, Server/Endgeräte stehen als HTML-Listen darunter, Container nur als Zähler bei kritischen Hosts. Spec folgt dem Code; ADR-0009 hält diesen Stand fest. → kein Issue, ADR-0009 hält den Stand fest
2. Router-Geräte ohne IP-Endung .1/.254 fehlen im Layer-3-Plan komplett (weder als Router noch im Gerätezähler). → #144
3. Layer-3-Gerätezahlen enthalten Container (gleiche IP wie Host) und lange offline Geräte. → #144
4. Omada-/UniFi-Verknüpfung überschreibt ein vorhandenes Elterngerät, auch ein manuell per API gesetztes; Docker-Verknüpfung dagegen nie. Proxmox-Elterngerät wird nur bei Neuanlage gesetzt, eine migrierte VM wandert nicht mit. → #144
5. Erweiterbar-Markierung nur für Hosts der Art server/nas; ein Docker-Host der Art `pc` bekommt Container zugeordnet, aber keinen Zähler. → #144
6. Mischt ein Router /24-Näherungen aus Probe-Fakten mit exakten Controller-CIDRs (z. B. /26), können beide als getrennte Subnetze in die Ketteninferenz eingehen. → #144

### [zugangsdaten](capabilities/zugangsdaten/spec.md) (7)

1. Kategorie wird serverseitig nicht validiert; beliebige Werte werden gespeichert. → #128
2. Secret und Passphrase lassen sich über die API nicht mehr leeren (leer = unverändert). → #128
3. Ausrollen akzeptiert jede Kategorie als Login-Zugang (z. B. `snmp`, `wifi`); das Secret wird dann als SSH-Passwort benutzt. → #128
4. `systemId` wird beim Anlegen/Ändern nicht auf Existenz geprüft. → #128
5. Löschen eines unbekannten Zugangs liefert `{ok: true}` statt 404. → #128
6. Anlegen, Ändern und Löschen von Zugängen werden nicht im Zugriffsprotokoll erfasst, nur Abruf, Erzeugung und Ausrollen. → #122
7. MEMBER sehen über Geräteansicht und Doku Benutzernamen, URLs und Notizen aller Zugänge; ob Notizen sensibel sein dürfen, ist nicht geregelt. → entschieden in #48: in Ordnung, solange keine Secrets
