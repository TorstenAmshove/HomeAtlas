# Werkzeuge des KI-Assistenten (In-App-Chat und MCP)

> Stand: Commit 0159807. Übersicht zu `backend/app/tools.py:TOOL_DEFINITIONS`. Die vollständigen
> Definitionen (Beschreibungstexte im Wortlaut, Parameter mit Typen, Enums, Defaults) stehen
> maschinell erzeugt in [llm-tools.json](llm-tools.json). Derselbe Satz gilt
> für den In-App-Chat und den externen MCP-Endpunkt `/api/mcp` (`backend/app/mcp_server.py:3`).
> Verhalten und Ablauf: [assistent-chat-und-mcp](../capabilities/assistent-chat-und-mcp/spec.md).
> Grenze: [ADR 0004](../../adr/0004-llm-faehigkeitsgrenze.md).

## Grenze (verbindlich)

- **[Muss]** Die Werkzeuge lesen nur oder messen live mit begrenztem Umfang. Sie ändern weder
  Inventar noch Dokumentation noch Geräte. Es gibt **genau eine bewusste Ausnahme**: `set_switch`
  (siehe unten).
- **[Muss]** Gespeicherte Secrets erreichen nie das Modell. `list_accounts` liefert keine Passwörter.
  `set_switch` entschlüsselt einen Home-Assistant-Token serverseitig und gibt ihn nie an das Modell.
- **[Muss]** Schreibende Admin-Funktionen (Container, Reboot, SSH-Konsole, Schlüssel ausrollen) sind
  über keine Werkzeuge erreichbar (`docs/adr/0002-lese-schreib-trennung.md`).
- **[Impl]** Jedes Ergebnis wird auf 6000 Zeichen gekürzt; die Kürzung steht im Ergebnis, damit
  das Modell gezielter nachfragt (`backend/app/tools.py:34`). Höchstens 8 LLM-Aufrufe pro
  Antwort (`backend/app/tools.py:35`).
- **[Muss]** Fehler eines Werkzeugs kommen als `{"error": …}` zurück, statt den Lauf abzubrechen
  (`backend/app/mcp_server.py:49`).
- Alle Werkzeuge stehen **jeder Rolle** (ADMIN und MEMBER) und jedem MCP-Client zur Verfügung,
  auch `set_switch` (`backend/app/tools.py:10`).

## Werkzeuge

| Name | Parameter (Pflicht fett) | Zweck |
|---|---|---|
| `list_systems` | `kind`, `query`, `onlyOnline` | dokumentierte Geräte auflisten, umgangssprachliche Namen („der Drucker“) zu Gerät + IP auflösen |
| `get_system` | **`idOrName`** | alle Details eines Geräts: Ports, Dienste, Beschreibung, Standort, Zweck |
| `network_overview` | – | Adressbereiche und Zusammenfassung des letzten Scans; Router/Gateway und DNS nur, soweit sie in dieser Zusammenfassung stehen |
| `list_documentation` | – | Doku-Kapitel mit Titel und Kurzbeschreibung |
| `get_documentation` | **`slug`** | vollständiger Text eines Kapitels |
| `list_accounts` | `systemId` | Zugänge **ohne Passwörter**: Bezeichnung, Benutzername, Adresse, Notiz |
| `list_containers` | – | Docker-Container des Servers: Image, Status, Ports, Volumes |
| `list_switches` | – | schaltbare Shelly-Geräte und Home-Assistant-Entities (nur `switch`/`light`) mit IDs für `set_switch` |
| `set_switch` | **`kind`** (`shelly`\|`ha`), `systemId`, `accountId`, `entityId`, **`on`** | Ein/Aus schalten, sofort und ohne Rückfrage. **Einzige schreibende Aktion.** Nicht für Schlösser, Rollläden, Heizung, Alarmanlage |
| `internet_check` | – | Internet in drei Schichten prüfen: Erreichbarkeit, Namensauflösung, Webseiten |
| `ping_host` | **`host`**, `count` | Erreichbarkeit und Stabilität |
| `check_port` | **`host`**, **`port`** | ist ein Dienst-Port erreichbar |
| `dns_lookup` | **`name`** | Name → IP |
| `reverse_dns` | **`ip`** | IP → Name |
| `http_check` | **`url`** | Statuscode, Seitentitel, Antwortzeit |
| `traceroute` | **`host`**, `maxHops` | Weg zum Ziel, Heimnetz vs. Anbieter unterscheiden |

Die Beschreibungstexte, die das Modell sieht, stehen auf Deutsch in `backend/app/tools.py` und sind
Teil des Verhaltens: Sie sagen dem Modell, welches Werkzeug es zuerst nehmen soll (z. B.
`internet_check` bei „Internet geht nicht“, `list_switches` vor `set_switch`).

`set_switch` ist die in ADR 0002 und ADR 0004 dokumentierte einzige Ausnahme von der Lese-Regel:
für alle Rollen und alle MCP-Clients, ohne Bestätigung (bestätigt in #43). Es erreicht nur Geräte,
die als Shelly erkannt sind, und protokolliert den Auslöser (Benutzer bzw. MCP-Token).
