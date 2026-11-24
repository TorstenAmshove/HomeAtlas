# Offene Punkte

Alle `OFFEN`-Markierungen der Capability-Specs: Unklarheiten, Widersprüche zwischen Code und
Doku, Verhalten, das eher nach Bug als nach Absicht aussieht. Vor dem Bau einer Alternative
entscheiden: **übernehmen**, **ändern** (in der Spec festhalten) oder **weglassen**. Viele Punkte
betreffen auch HomeAtlas selbst und eignen sich als Issues.

Jeder Punkt der Liste unten trägt am Ende `→ #N`, das GitHub-Issue, in dem er bearbeitet wird
(mehrere zusammengehörige Punkte teilen sich ein Issue), oder die Entscheidung, die ihn erledigt hat.
Ohne Verweis sind nur die Punkte zu TP-Link und `omada_backup`, für sie gibt es noch kein Issue.

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


<!-- Ab hier erzeugt von trace_specs.py -->

## Alle Punkte je Fähigkeit (8)

### [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md) (1)

1. `list_switches` fragt bei jedem Aufruf live alle freigegebenen HA-Instanzen ab (kein Cache). → #121

### [auth-und-rollen](capabilities/auth-und-rollen/spec.md) (0)


### [credentialed-probing](capabilities/credentialed-probing/spec.md) (2)

1. TP-Link-Pager-Abschaltung nutzt `configure` / `no clipaging` – ein Konfigurationsmodus-Befehl, entgegen „kein Config-Mode“. Ob die Einstellung persistent in der Running-Config landet, ist ungeprüft.
2. `omada_backup` läuft auf jedem Linux-Host und wird Base64-kodiert als Fakt gespeichert; ein Restore ist bewusst nicht vorgesehen, Nutzen der Speicherung ist unklar.

### [dashboard](capabilities/dashboard/spec.md) (0)


### [diagnose](capabilities/diagnose/spec.md) (0)


### [dokumentation](capabilities/dokumentation/spec.md) (1)

1. Benutzernamen und URLs von Zugängen sind über die Doku für MEMBER sichtbar, obwohl die Zugangs-API admin-only ist. Ebenso Gerätenotizen und ausgelesene Gerätewerte — falls dort Geheimnisse stehen, landen sie in der Doku. → entschieden in #48: in Ordnung, solange keine Secrets

### [einstellungen-und-llm-provider](capabilities/einstellungen-und-llm-provider/spec.md) (0)


### [inventar](capabilities/inventar/spec.md) (1)

1. `GET /api/systems/{id}` liefert MEMBER die Zugangs-Metadaten (Label, Benutzername, URL, Notizen) des Geräts; nur die UI blendet sie aus. Gewollt? → entschieden in #48: in Ordnung, solange keine Secrets

### [netzwerkressourcen-vlans](capabilities/netzwerkressourcen-vlans/spec.md) (1)

1. Der manuelle Abgleich beim Verbindungstest (`backend/app/routes/systems.py:262`) nutzt dieselbe `sync_network_resources` und zählt `emptyScans` mit; zwei Klicks bei leer gemeldetem Bereich deaktivieren dessen Ressourcen also ebenso wie zwei Scans. Gewollt?

### [topologie](capabilities/topologie/spec.md) (1)

1. ADR-0008 und CLAUDE.md beschreiben die Ebenen „Server → Endgeräte“ und „Container innerhalb ihres Hosts“; das Bild zeichnet aber nur „Wichtige Geräte“, Server/Endgeräte stehen als HTML-Listen darunter, Container nur als Zähler bei kritischen Hosts. Spec folgt dem Code; ADR-0009 hält diesen Stand fest. → kein Issue, ADR-0009 hält den Stand fest

### [zugangsdaten](capabilities/zugangsdaten/spec.md) (1)

1. MEMBER sehen über Geräteansicht und Doku Benutzernamen, URLs und Notizen aller Zugänge; ob Notizen sensibel sein dürfen, ist nicht geregelt. → entschieden in #48: in Ordnung, solange keine Secrets
