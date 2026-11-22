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
| 4 | **Behoben (fix/diagnostics-and-defaults) für `http_check`/`check_port`; Linkprüfung der Klassifikation und frei eingebbare LLM-Adresse offen, siehe #114.** **`http_check` als SSRF-Fläche.** MEMBER, Assistent und MCP-Clients können serverseitig beliebige URLs abrufen, auch `127.0.0.1` und interne Dienste. Das Gleiche gilt für die Linkprüfung der Klassifikation und für „Testen“/„Modelle laden“ mit frei eingebbarer Adresse. | diagnose, klassifikation-llm, einstellungen-und-llm-provider | #44 |
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

- Farbe ist im Netzplan-Kasten das einzige Statussignal (topologie) → #143.
- README: IPv6-Geräte über mDNS/SSDP. Der Code verwirft sie (discovery-und-scan) → #136.
- Netzwerkressourcen kommen nur von UniFi, nicht von Omada (netzwerkressourcen-vlans).
- Passwortrichtlinie 10 Zeichen; die UsersPage zeigt „mindestens 8“, `ADMIN_PASSWORD` und der
  CLI-Reset umgehen die Richtlinie (auth-und-rollen) → #117.

<!-- Ab hier erzeugt von trace_specs.py -->

## Alle Punkte je Fähigkeit (136)

### [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md) (6)

1. `list_switches` nutzt jeden HA-Zugang unabhängig vom Opt-in „Zum Auslesen verwenden“ und fragt bei jedem Aufruf live alle HA-Instanzen ab. → #121
2. Scheitert eine Runde (502), bleibt die Benutzernachricht gespeichert; die UI legt sie zurück ins Eingabefeld → beim erneuten Senden doppelt im Verlauf. Umbenennung passiert auch bei gescheiterter Runde. → #150
3. Keine Gesamtzeitgrenze je Runde: bis zu 8 LLM-Aufrufe à 120 s plus Werkzeuge. → #120
4. `systemPromptOverride` ist nur per API setzbar (keine UI) und ersetzt den Prompt ohne Platzhalter-Ersetzung (`{home_name}` bliebe wörtlich). → #150
5. Kein Rate-Limit auf `/api/mcp`; `lastUsedAt` wird bei jeder Anfrage geschrieben. → #120
6. Eine Nachricht nur aus Leerzeichen erfüllt die Mindestlänge 1 und wird gesendet; als erste Nachricht ergibt sie einen leeren Chat-Titel. → #150

### [auth-und-rollen](capabilities/auth-und-rollen/spec.md) (16)

1. `DELETE /api/users/{id}` schreibt keinen Protokolleintrag, obwohl die AccessLogPage ein Label `user.delete` kennt und README „Benutzeränderungen“ als protokolliert nennt (wirkt wie Bug). → #122
2. `DELETE /api/users/{id}` antwortet für unbekannte IDs mit `{ok: true}` statt 404 (PATCH/mfa-reset liefern 404). → #123
3. PATCH `/api/users/{id}` ist nicht atomar: Anzeigename/Rolle werden gespeichert, bevor ein zu schwaches `newPassword` mit 400 abgelehnt wird. → #123
4. POST `/api/users` mappt unbekannte Rollen still auf MEMBER, PATCH antwortet 400 – uneinheitlich. → #123
5. Eigener Passwortwechsel beendet keine anderen Sessions (Admin-Reset schon) – gewollt? → #116
6. Admin-MFA-Reset beendet keine Sessions, die CLI-Variante schon; eine offene Session des Ziels kann den Faktor danach selbst neu einrichten (nur Passwort-Besitz war nötig für die Session, ist aber u. U. ein Angreifer). → #116
7. Ein Konto ohne aktiven Faktor (neu angelegt oder nach Reset) kann von jedem mit dem Passwort eingerichtet werden – bewusste Abwägung laut `reset_password.py`-Docstring, aber ohne Ablaufzeit. → #116
8. Initial-Admin via `ADMIN_PASSWORD` und CLI-Passwortreset umgehen die Richtlinie (CLI prüft nur ≥ 8 Zeichen; README-Beispiel `devpass123` erfüllt sie nicht). → #117
9. UsersPage zeigt „Mindestens 8 Zeichen“ und aktiviert „Anlegen“ ab 8 Zeichen, Richtlinie verlangt 10. → #117
10. AccessLogPage kennt Label `mfa.disable` (nie geschrieben). (`mfa.reset` hat seit PR 6 ein Label und gilt als sicherheitsrelevant.) → #122
11. Session-Cookie ohne `Secure`-Flag, auch hinter TLS-Proxy. → #115
12. `X-Real-IP` wird ungeprüft übernommen; sicher nur, solange das Backend ausschließlich über nginx erreichbar ist (ADR-0003). → #115
13. Benutzernamen sind case-sensitiv und werden weder getrimmt noch validiert (außer ≥ 1 Zeichen). → #123
14. Selbst-Herabstufung eines ADMIN ist erlaubt, solange ein weiterer ADMIN existiert; die eigene UI-Ansicht bleibt bis zum Reload Admin. → #123
15. WebSocket-Check akzeptiert fehlenden `Origin`-Header; Docstring nennt die Bedingung „same bar as current_user“, prüft aber zusätzlich ADMIN. → #115
16. `GET /api/health` ist unauthentifiziert und verrät `userCount`; das Frontend nutzt das Feld nicht. → #115

### [credentialed-probing](capabilities/credentialed-probing/spec.md) (11)

1. In `probe_system` ist `elif "ssh" not in results` (analog `snmp`, `ha`) immer wahr, weil Schlüssel `ssh:<label>` heißen – fehlgeschlagene Ergebnisse werden stets gespeichert, auch wenn ein anderer Zugang derselben Art erfolgreich war (`backend/app/probe_auth.py:1397`). Absicht unklar. → #133
2. HTTP- und TR-064-Fehlschläge werden nicht als Ergebnis gespeichert, nur Erfolge – daher kein Fehlerereignis für abgelehnte Web-Logins. → #133
3. `login`-Zugänge mit Port ≠ 0/22 werden nie per SSH versucht (`sshkey` mit beliebigem Port schon) (`backend/app/probe_auth.py:1389`). → #133
4. TR-064 wählt den ersten Zugang der Kategorie `login` oder `router`; `router` existiert in der UI nicht. Bei einem Nicht-FRITZ-Router mit `kind = router` wird dessen Login-Passwort per Digest an Port 49000 geschickt. → #134
5. TP-Link-Pager-Abschaltung nutzt `configure` / `no clipaging` – ein Konfigurationsmodus-Befehl, entgegen „kein Config-Mode“. Ob die Einstellung persistent in der Running-Config landet, ist ungeprüft.
6. Manuelles Auslesen behandelt `omada`/`proxmox`/`adguard`-Zugänge nicht (sie gehen an `probe_auth.probe_system`, das sie ignoriert) → bei solchen Geräten `ran = false` ohne Grund. Ebenso ignoriert es `scanUseCredentials`/`scanEnable*`, den Standard-Zugang, ARP-Lernen, Druckerzuordnung, `os`/`model`-Füllung und Fehlerereignisse. → #135
7. Im Vollscan nutzen Controller-Probes alle freigegebenen Zugänge der Kategorie, beim manuellen Auslesen nur die dem Gerät (direkt/per Zuordnung) zugeordneten – uneinheitlich. → #135
8. `omada_backup` läuft auf jedem Linux-Host und wird Base64-kodiert als Fakt gespeichert; ein Restore ist bewusst nicht vorgesehen, Nutzen der Speicherung ist unklar.
9. Omada liest nur Seite 1 (Geräte 100, Clients 500); größere Sites werden still abgeschnitten. Ein `errorCode` bei Geräten überspringt auch die Clients der Site.
10. README „Sicherheit“ sagt, das Verfahren lasse sich unter *Einstellungen → Netzwerk-Scan* „komplett abschalten“. Trifft nur teilweise zu: `scanUseCredentials = false` stoppt nur das Auslesen je Gerät; UniFi/Omada/Proxmox/AdGuard melden sich weiter mit Zugangsdaten an, solange ihr `scanEnable*` an ist (`backend/app/pipeline.py:387`–`:455` vs. `:521`). Doku oder Verhalten anpassen? → #136
11. Klassisches Aruba braucht ein Konto, das direkt mit Manager-Rechten anmeldet; die UI weist darauf nicht hin. → #134

### [dashboard](capabilities/dashboard/spec.md) (4)

1. `lastScan` liefert die komplette Scan-Zeile inkl. vollständigem `log` und `summary` an MEMBER (`backend/app/main.py:1633`); die UI braucht nur `startedAt`/`status`. Unnötige Datenmenge und Offenlegung von Scan-Details. → #119
2. Kritische Geräte ohne IP und Hostname werden nie überwacht (`backend/app/db.py:1900`) und stehen dauerhaft als „wird geprüft…" auf dem Dashboard – irreführend. → #131
3. Bei mehr als 10 kritischen Geräten werden still nur die ersten 10 (alphabetisch) gezeigt; die Kachel nennt die volle Zahl, ein Hinweis auf weitere fehlt. → #131
4. Status `unknown` und jeder andere Wert erscheinen gleichermaßen als „wird geprüft…", auch wenn die Überwachung abgeschaltet ist (dann wird nichts geprüft). → #131

### [diagnose](capabilities/diagnose/spec.md) (3)

1. Keine Ratenbegrenzung/Parallelitätssperre: jeder MEMBER kann Speedtests (35 MB Verkehr) und lange Traceroutes beliebig oft parallel auslösen. → #120
2. Die Latenz des Speedtests ist die erste Anfrage auf einer neuen Verbindung und enthält TCP- und TLS-Aufbau – systematisch zu hoch. → #151
3. REST-Tool-Namen weichen von den LLM-Werkzeugnamen ab (`ping` vs. `ping_host`); Alternative vereinheitlichen? → #151

### [discovery-und-scan](capabilities/discovery-und-scan/spec.md) (10)

1. Fortschritt springt rückwärts (94 % „Inventar aktualisieren“, dann 93 % Zugangs-Abfrage, `pipeline.py:480`/`:522`). → #138
2. Einzelziele umfassen IPs *aller* Inventar-Geräte außerhalb der Bereiche (auch entdeckte Controller-Clients/Proxmox-Gäste), nicht nur „von Hand eingetragene“ wie der Docstring sagt (`pipeline.py:42`). Kann viele geroutete Ziele erzeugen. → #138
3. Ungültiger Freitext-Bereich (z. B. „bad“) plus ein mDNS/SSDP-Fund außerhalb von `alive` führt in `discovery.py:859` zu `ValueError` aus `ip_network` und lässt den ganzen Scan scheitern. → #137
4. README behauptet, IPv6-Geräte erscheinen per mDNS/SSDP; der Code nimmt nur IPs in IPv4-Scan-Bereichen auf (`discovery.py:859`), IPv6-Funde werden verworfen. → #136
5. Port 81 steht in der Banner-Portliste, aber nicht im Port-Katalog, wird also nie als offen erkannt (`discovery.py:341`, `ports.py:12`). → #138
6. Ohne geladenes OUI-Register versucht jeder Scan erneut den Download (bis 120 s), auch offline. → #138
7. MEMBER darf `GET /api/scans*` inkl. Protokoll lesen (Gerätenamen, Fehlertexte der Zugangs-Abfrage), obwohl die Scan-Seite admin-only ist. Absicht? → #119
8. Start-Prüfung „läuft schon ein Scan“ und Anlegen sind nicht atomar (Rennen Zeitplan/manuell theoretisch möglich). → #129
9. Namensvergabe für Nicht-Container ohne IP bei Duplikaten: kein Suffix, Duplikat bleibt. → #138
10. Abgeschaltete Quelle (`scanEnableDocker=false`, Controller aus) setzt alle bisher aus dieser Quelle entdeckten Geräte beim nächsten Scan auf `offline`. → #139

### [dokumentation](capabilities/dokumentation/spec.md) (10)

1. Reset eines Kapitels erzeugt alle 13 Kapitel neu (Laufzeit/KI-Kosten, neue Versionen auf anderen Seiten). Absicht oder sollte nur das eine Kapitel neu entstehen? → #141
2. `POST /api/docs/{slug}/reset` mit unbekanntem Slug liefert 200 mit `page: null` statt 404. → #140
3. `GET /api/docs/{slug}/versions` mit unbekanntem Slug liefert leere Liste statt 404. → #140
4. `PUT /api/docs/{slug}` ohne Feld `bodyMd` speichert leeren Text (keine Validierung). → #140
5. Wiederherstellen überschreibt auch die eigenen Notizen mit dem alten Stand — gewollt, obwohl Notizen „nie angefasst“ werden sollen (gilt laut Code nur für die Automatik)? → #141
6. Kapitel, deren Slug nicht mehr definiert ist, werden nie gelöscht (`db.delete_doc_page` ungenutzt). → #140
7. Benutzernamen und URLs von Zugängen sind über die Doku für MEMBER sichtbar, obwohl die Zugangs-API admin-only ist. Ebenso Gerätenotizen und ausgelesene Gerätewerte — falls dort Geheimnisse stehen, landen sie in der Doku. → entschieden in #48: in Ordnung, solange keine Secrets
8. Keine Sperre gegen gleichzeitige Generierungen (Scan + manueller Lauf) — mögliche doppelte Versionen/Race. → #129
9. Bei mehreren Routern nimmt die Notfall-Seite den ersten aus der Inventarreihenfolge. → #141
10. `useLlm: true` im Request wird ignoriert, wenn `scanUseLlm` aus ist (die Einleitung prüft die Einstellung erneut). → #141

### [einstellungen-und-llm-provider](capabilities/einstellungen-und-llm-provider/spec.md) (9)

1. Ein leer gesendeter API-Schlüssel löscht ihn, ein leer gesendetes Standard-Zugang-Geheimnis bleibt erhalten — uneinheitliche Semantik. → #124
2. `PATCH /api/settings` akzeptiert beliebige Schlüssel und Typen, auch `setupCompleted` oder ein rohes `defaultCredentialSecretEnc`. → #124
3. UI-Fehler: Nach „Modelle laden“ wird nur `data`, nicht `form` aktualisiert; die neue Liste erscheint erst nach Neuladen, und ein anschließendes „Speichern“ schreibt den alten `providerModelCache` zurück. → #125
4. Die Live-Liste wird nach ID sortiert gespeichert; der Fallback „erster/letzter Eintrag“ in `resolve` wählt dadurch alphabetisch, nicht nach Anbieter-Reihenfolge (Docstring geht von Anbieterreihenfolge aus). → #125
5. `providerModelCache` wird bei Wechsel von Schlüssel oder Server-Adresse nicht verworfen. → #125
6. Claude-Modellabruf holt höchstens 100 Modelle, ohne Paginierung. → #125
7. Ollama-, `deepseekBaseUrl`-Schlüssel fehlen in den Defaults (funktional egal, aber unvollständig dokumentiert). → #124
8. Test/Modelle-Laden schicken Anfragen an eine frei eingebbare Server-Adresse (Admin-only, aber serverseitige Anfrage an beliebige URL). → #114
9. Gemini-Schlüssel steht als Query-Parameter in der URL (kann in Proxy-Logs landen). → #125

### [firewall](capabilities/firewall/spec.md) (1)

1. nftables der Hosts (Forced-Command `nft -j list ruleset`), Pfadbewertung (`firewall_eval.py`), Werkzeuge `check_firewall_path`/`list_firewall_rules`, Kapitel „Wer darf mit wem sprechen“ und die Verknüpfung mit den Erreichbarkeits-Ketten (Issue #106, Teile B–D).

### [inventar](capabilities/inventar/spec.md) (9)

1. `GET /api/systems/{id}` liefert MEMBER die Zugangs-Metadaten (Label, Benutzername, URL, Notizen) des Geräts; nur die UI blendet sie aus. Gewollt? → entschieden in #48: in Ordnung, solange keine Secrets
2. PATCH validiert nichts: `kind`/`importance` beliebig, `status`, `discoveryKey`, `discovered`, `extra`, `openPorts`, `lastSeen` frei schreibbar. Ein `discoveryKey`, den schon ein anderes Gerät hat, verletzt den Unique-Index → vermutlich HTTP 500. → #126
3. Da die UI das komplette Gerät zurückschickt, überschreibt Speichern zwischenzeitliche Änderungen von Scan/Überwachung (`status`, `extra`, `openPorts`, `lastSeen`) mit dem alten Stand (Lost Update). → #126
4. POST übernimmt eine vom Client mitgeschickte `id` (`backend/app/db.py:643`); mit vorhandener ID vermutlich 500. → #126
5. DELETE lässt `deviceConfigVersions`, `deviceErrorEvents` und `monitorEvents` des Geräts verwaist zurück (`backend/app/db.py:692`), obwohl Merge sie bewusst umhängt; antwortet `ok` auch für unbekannte IDs. → #127
6. Ist das behaltene Gerät Kind des entfernten, setzt Merge `parentId` des behaltenen auf sich selbst (`backend/app/db.py:884`). → #127
7. Ein kritisches Gerät lässt sich nicht aus der Überwachung nehmen (`monitored=0` wird in der nächsten Runde wieder 1); wird „kritisch" entfernt, bleibt die Überwachung an. Gewollt? → #131
8. `monitorPorts` wird serverseitig nicht auf 3 Einträge/gültige Ports begrenzt; nur die UI und `effective_ports` kürzen. → #126
9. Der Fehler-Badge verschwindet nie, weil Fehlerereignisse nicht quittiert oder gelöscht werden können (nur Kappung bei 100). → #132

### [klassifikation-llm](capabilities/klassifikation-llm/spec.md) (6)

1. Weil `importance` nach Normalisierung nie leer ist, überschreibt die KI-Wichtigkeit immer die regelbasierte – auch beim Gateway (`critical`), sobald es Kandidat ist (z. B. kein kuratierter Doku-Link bei Nicht-AVM-Routern). Ebenso überschreibt eine ungültige KI-`kind` (→ `other`) eine korrekte Regel-Art wie `router`. → #142
2. Ein sicher erkanntes Gerät wird schon Kandidat, wenn nur der Doku-Link fehlt. → #142
3. Nur exakt `"low"` wird verworfen; „LOW“, „niedrig“ o. Ä. gelten als akzeptiert. → #142
4. Die Link-Prüfung führt GET auf beliebige vom Modell gelieferte URLs vom Server aus, auch auf LAN-Adressen (SSRF-artig); kein Ausschluss privater Ziele. → #114
5. Gleiche IP in mehreren Funden (Netzwerk-Fund plus UniFi/Omada/Proxmox/AdGuard) – mehrere Belegsätze pro IP im selben Stapel möglich, der letzte gewinnt, und das Ergebnis wird auf alle Funde dieser IP angewandt. → #142
6. Der Prompt verlangt dieselbe Reihenfolge wie die Eingabe; der Code ordnet ausschließlich per IP zu (Reihenfolge irrelevant) – unschädlich, aber Anforderung an Modell überflüssig. → #142

### [monitoring](capabilities/monitoring/spec.md) (7)

1. Kritische Geräte werden vor jeder Runde zwangsweise wieder auf „überwacht“ gesetzt – ein Admin kann die Überwachung eines kritischen Geräts nicht abschalten; das Abwählen wird stillschweigend rückgängig gemacht. Absicht? (`backend/app/db.py:1890`) → #131
2. `unknown` (z. B. Ping-Aufruf wirft) setzt den Fehlerzähler zurück und wird sofort übernommen; ein Gerät kann so `offline → unknown → offline` flattern und jeweils Ereignisse erzeugen. → #130
3. Manuelle Runde und Hintergrundschleife teilen sich den Fehlerzähler und können parallel laufen; ein Klick auf „Jetzt prüfen“ kann einen Ausfall daher schneller „bestätigen“ als zwei Intervalle. → #129
4. `monitorEvents` hat keine Aufbewahrungsgrenze (im Gegensatz zu `deviceErrorEvents`/`accessLog`); wächst bei flatternden Geräten unbegrenzt. → #130
5. Rückkehr auf `online` nach Ausfall erzeugt kein Fehler-/Info-Ereignis am Gerät, nur ein `monitorEvents`-Eintrag – gewollt? → #130
6. `intervalSeconds` in `GET /api/monitor` ist der ungeklemmte Einstellungswert, nicht das tatsächlich verwendete Intervall; `monitorTimeoutMs` hat serverseitig keine Obergrenze. → #130
7. Für Docker-Container (Art `container`, teilen die Host-IP) gibt es keine typischen Ports; ohne offene Ports prüft der Monitor per Ping effektiv nur den Host. → #130

### [netzwerkressourcen-vlans](capabilities/netzwerkressourcen-vlans/spec.md) (6)

1. Seite „Netze & WLAN“ zeigt bei WLAN `facts.networkName` und bei WAN `facts.type`/`facts.ip`; der Abgleich liefert diese Felder nie (WLAN hat nur `networkExternalId`, WAN `{}`). WAN-Details sind daher immer „-“, das zugehörige Netz eines WLANs wird nie angezeigt (`frontend/src/pages/geraete/NetworksPage.tsx`). Dasselbe gilt für die WAN-Tabelle der Dokumentation (`backend/app/docs.py:380`). → #145
2. Fähigkeitsbeschreibung nennt Omada und Discovery-Subnetze als Quelle; im Code liefert nur UniFi Netzwerkressourcen. Soll eine Alternative Omada-Netze übernehmen?
3. Feld heißt `manualMd`, wird aber weder auf der Seite noch sonst als Markdown gerendert; Eingabe ist einzeilig. → #145
4. Inaktive Ressourcen sind in der UI nirgends sichtbar (nur über die API), ihre Notizen also faktisch versteckt; gewollt? → #145
5. Ein vollständig gelesener Bereich mit 0 Einträgen deaktiviert alle Ressourcen dieses Bereichs; bei einer kurzzeitig leeren Controller-Antwort gehen sie (reversibel) aus Scan-Auswahl, Doku und Layer-3-Plan verloren. → #139
6. Notiz-Änderung erzeugt keinen Eintrag im Zugriffsprotokoll und hat keine Längenbegrenzung. → #122, #145

### [remote-admin](capabilities/remote-admin/spec.md) (10)

1. Prompt-Injection-Risiko: Inhalte aus Inventar/Doku könnten das Modell zu `set_switch` ohne Rückfrage verleiten. → entschieden in #43
2. Assistent schaltet bei Shelly immer Kanal 0; REST-Route akzeptiert beliebige `channel`-Ganzzahl ohne Bereichsprüfung. → #147
3. Proxmox-Steuerung fällt bei *jedem* API-Fehler auf SSH zurück – auch bei fachlichen Fehlern der API (z. B. Gast bereits gestoppt); mögliche Doppelausführung/irreführende Meldung. (`backend/app/main.py:1061`) → #146
4. Reboot meldet evtl. Fehler, obwohl der Neustart ausgelöst wurde (SSH-Verbindung bricht beim Reboot ab, bevor ein Exit-Status kommt). Nicht durch Tests abgedeckt. → #146
5. Kategorie `router` wird im Reboot-Pfad akzeptiert, existiert aber in der UI-Kategorieliste nicht (`frontend/src/pages/zugaenge/AccountFormPage.tsx`) – toter Zweig oder Altbestand? → #134
6. SSH-Befehle (`connection.run`) haben kein Gesamt-Timeout; ein hängender Befehl blockiert die Anfrage unbegrenzt. → #146
7. Nicht-numerische `cols`/`rows` in einer Resize-Nachricht lösen eine Ausnahme aus und beenden die Sitzung statt ignoriert zu werden. (`backend/app/main.py:864`) → #146
8. `Terminal.tsx` erwartet laut Kommentar eine Server-Nachricht `{"type":"exit"}`, die das Backend nie sendet. → #147
9. Frontend kodiert `containerId` in der URL der Remote-Docker-Konsole nicht (`frontend/src/lib/api.ts:528`), anders als bei Aktion/Logs. → #147
10. Keine Tests für die drei WebSocket-Konsolen, lokale Container-Aktionen, Shelly/HA-Schalten und die Origin-Prüfung. → #148

### [setup-wizard](capabilities/setup-wizard/spec.md) (7)

1. `POST /api/setup` prüft nicht, ob das Setup schon abgeschlossen ist; erneuter Aufruf legt Geräte/Konten doppelt an und überschreibt `homeName`/`scanSubnets`. → #149
2. Antwortfeld `accounts` zählt Gerätezugänge nicht mit – gewollt oder Ungenauigkeit? → #149
3. Keine Validierung der `scanSubnets`-Einträge; ungültiger Freitext landet in den Einstellungen (Verhalten im Scan siehe [discovery-und-scan](../discovery-und-scan/spec.md)). → #137
4. Leerer `homeName` wird gespeichert; Doku/Topologie/Assistent fallen dann teils auf Ersatztexte zurück. → #149
5. `GET /api/health` ist ohne Login erreichbar und verrät `userCount`; das Frontend nutzt das Feld nicht. → #115
6. Art→Wichtigkeit (`router/server/nas/heating` → kritisch) ist hart verdrahtet; `network` (Switch/AP) wird nicht kritisch – Absicht? → #149
7. Kein Duplikatabgleich mit bereits gescannten Geräten gleicher IP; ein späterer Scan muss das zusammenführen (siehe [inventar](../inventar/spec.md)). → #149

### [topologie](capabilities/topologie/spec.md) (12)

1. ADR-0008 und CLAUDE.md beschreiben die Ebenen „Server → Endgeräte“ und „Container innerhalb ihres Hosts“; das Bild zeichnet aber nur „Wichtige Geräte“, Server/Endgeräte stehen als HTML-Listen darunter, Container nur als Zähler bei kritischen Hosts. Spec folgt dem Code; ADR-0009 hält diesen Stand fest. → kein Issue, ADR-0009 hält den Stand fest
2. Farbe ist im Kasten das einzige Statussignal (kein Wort wie „nicht erreichbar“), entgegen ADR-0008 und Modul-Docstring; der Layer-3-Plan hat zudem keine Legende. → #143
3. Router über 6, Verteiler über 10 und kritische Geräte über 10 verschwinden ersatzlos – die Listen unter dem Plan enthalten weder Router/Verteiler noch kritische Geräte. → #143
4. Ein kritischer Router oder Verteiler erscheint doppelt (Backbone-Ebene und „Wichtige Geräte“). → #143
5. Layer-3-Subnetzkästen tragen `data-system-id="subnet:<cidr>"`; ein Klick navigiert zu `/geraete/subnet:<cidr>` (enthält „/“), also zu keiner gültigen Geräteseite (`backend/app/topology.py:741`). → #143
6. Reihenfolge der Subnetzkästen kommt aus einer Mengen-Iteration (hash-abhängig, kann zwischen Prozessstarts wechseln); `_subnet_sort_key` ist definiert, aber unbenutzt (`backend/app/topology.py:481`, `backend/app/topology.py:725`). → #143
7. Router-Geräte ohne IP-Endung .1/.254 fehlen im Layer-3-Plan komplett (weder als Router noch im Gerätezähler). → #144
8. Layer-3-Gerätezahlen enthalten Container (gleiche IP wie Host) und lange offline Geräte. → #144
9. Omada-/UniFi-Verknüpfung überschreibt ein vorhandenes Elterngerät, auch ein manuell per API gesetztes; Docker-Verknüpfung dagegen nie. Proxmox-Elterngerät wird nur bei Neuanlage gesetzt, eine migrierte VM wandert nicht mit. → #144
10. Erweiterbar-Markierung nur für Hosts der Art server/nas; ein Docker-Host der Art `pc` bekommt Container zugeordnet, aber keinen Zähler. → #144
11. Kommentar an `_MAX_CRITICAL_BOXES` nennt eine „readability floor“ der Kastenbreite; `_row` hat keine Untergrenze, bei vielen Layer-3-Knoten werden Kästen beliebig schmal. → #143
12. Mischt ein Router /24-Näherungen aus Probe-Fakten mit exakten Controller-CIDRs (z. B. /26), können beide als getrennte Subnetze in die Ketteninferenz eingehen. → #144

### [zugangsdaten](capabilities/zugangsdaten/spec.md) (9)

1. Ein nicht entschlüsselbares Secret wird als leerer String ausgeliefert und als erfolgreicher Abruf (`ok=1`) protokolliert; Admin und Protokoll sehen nicht, dass der Schlüssel fehlt (`backend/app/crypto.py:49`). → #118
2. Kategorie wird serverseitig nicht validiert; beliebige Werte werden gespeichert. → #128
3. Secret und Passphrase lassen sich über die API nicht mehr leeren (leer = unverändert). → #128
4. Ausrollen akzeptiert jede Kategorie als Login-Zugang (z. B. `snmp`, `wifi`); das Secret wird dann als SSH-Passwort benutzt. → #128
5. `systemId` wird beim Anlegen/Ändern nicht auf Existenz geprüft. → #128
6. Löschen eines unbekannten Zugangs liefert `{ok: true}` statt 404. → #128
7. Anlegen, Ändern und Löschen von Zugängen werden nicht im Zugriffsprotokoll erfasst, nur Abruf, Erzeugung und Ausrollen. → #122
8. MEMBER sehen über Geräteansicht und Doku Benutzernamen, URLs und Notizen aller Zugänge; ob Notizen sensibel sein dürfen, ist nicht geregelt. → entschieden in #48: in Ordnung, solange keine Secrets
9. Löschen eines Geräts löscht dessen Zugänge unwiderruflich mit, ohne Rückfrage auf API-Ebene. → #127
