# Assistent: Chat und MCP

> Status: Ist-Verhalten, aus dem Code zurückgewonnen (Stand 0159807). Quellen als `datei:zeile`.

## Zweck

Haushaltsmitglieder beschreiben in eigenen Worten, was nicht funktioniert; ein KI-Assistent löst
umgangssprachliche Namen („der Drucker“) über das Inventar auf, misst live nach (Ping, Port, DNS,
Internet) und führt Schritt für Schritt durch die Fehlersuche — ohne je ein gespeichertes Passwort zu
sehen. Dieselben Werkzeuge stehen externen KI-Programmen (z. B. Claude Desktop) über einen
MCP-Endpunkt zur Verfügung, abgesichert mit vom Admin erzeugten Tokens.

## Rollen und Rechte

| Aktion | ADMIN | MEMBER | MCP-Token |
|---|---|---|---|
| Unterhaltungen auflisten, anlegen, lesen, löschen | ja | ja | – |
| Nachricht an den Assistenten senden (inkl. aller Tools, auch `set_switch`) | ja | ja | – |
| Tools über `/api/mcp` aufrufen (inkl. `set_switch`) | – | – | ja |
| MCP-Tokens auflisten, erzeugen, widerrufen | ja | nein | nein |

Unterhaltungen gehören dem Benutzer, der sie angelegt hat: Jeder sieht, liest, setzt fort und
löscht nur die eigenen; ADMIN sieht alle (Entscheidung zu #49).

## Anforderungen

### Requirement: Unterhaltungen verwalten
Das System MUSS Unterhaltungen anlegen (Titel „Neue Unterhaltung“, Besitzer = anlegender Benutzer),
neueste Aktivität zuerst auflisten und löschen können; Löschen entfernt alle Nachrichten der
Unterhaltung. **[Muss]**

### Requirement: Unterhaltungen je Benutzer
Ein Benutzer DARF nur eigene Unterhaltungen sehen, lesen, fortsetzen und löschen; ADMIN darf alle.
Unterhaltungen ohne Besitzer (angelegt vor dieser Regel) sind nur für ADMIN sichtbar. Eine fremde
oder unbekannte Unterhaltung beantwortet das System mit 404, ohne ihre Existenz zu verraten.
**[Muss]**

#### Szenario: Fremde Unterhaltung
- **WENN** Bert die Unterhaltung von Anna abrufen, fortsetzen oder löschen will
- **DANN** antwortet das System mit 404, Annas Unterhaltung bleibt unverändert

Quelle: `backend/app/routes/chat.py` (`_visible_chat`), `backend/app/db.py` (`chats.userId`), Tests:
`backend/tests/test_chat_owner_and_switch.py::test_member_sees_only_own_chats`, `::test_admin_sees_all_including_ownerless`

#### Szenario: Neue Unterhaltung
- **WENN** ein Benutzer „Neue Unterhaltung“ anlegt (API)
- **DANN** erscheint sie mit Titel „Neue Unterhaltung“ oben in der Liste

Die neue Oberfläche legt nichts an, solange keine Frage gestellt wird (siehe „Unterhaltung in der URL …“).

#### Szenario: Automatischer Titel
- **WENN** die erste Nachricht in einer Unterhaltung mit Titel „Neue Unterhaltung“ gesendet wird
- **DANN** wird die Unterhaltung auf die ersten 60 Zeichen der (getrimmten) Nachricht umbenannt

Quelle: `backend/app/main.py:1496`, `backend/app/main.py:1528`, `backend/app/db.py:1946`, `backend/app/db.py:1954`, `backend/app/db.py:1969`

### Requirement: Verlauf anzeigen
Das System MUSS den Verlauf einer Unterhaltung chronologisch liefern und dabei nur Benutzer- und
Assistentennachrichten mit Inhalt zeigen; Tool-Aufrufe und Tool-Ergebnisse werden gespeichert, aber
nicht ausgeliefert. Unbekannte Unterhaltung → 404 „Unterhaltung nicht gefunden.“ **[Muss]**

#### Szenario: Tool-Verkehr verborgen
- **WENN** der Assistent für eine Antwort `ping_host` benutzt hat
- **DANN** enthält der Verlauf die Frage und die Antwort, aber nicht das Ping-Rohergebnis

Quelle: `backend/app/main.py:1501`, `backend/app/db.py:1992`

### Requirement: Unterhaltung in der URL und Entwurf je Unterhaltung (UI)
Die Oberfläche MUSS die unversandte Eingabe je Unterhaltung im `sessionStorage` des Browser-Tabs
halten, damit sie einen Seitenwechsel und Neuladen übersteht; Senden leert sie, ein gescheitertes
Senden legt den Text in den Entwurf der Unterhaltung zurück, an die er ging, und ins Eingabefeld nur,
wenn diese Unterhaltung noch offen ist. Dazu
MUSS die geöffnete Unterhaltung in der URL stehen (`/assistent/:chatId`): Wählen oder Anlegen einer
Unterhaltung navigiert dorthin, Zurück und Neuladen landen in derselben. `/assistent` öffnet die
neueste Unterhaltung; eine unbekannte oder fremde ID fällt ohne Fehlermeldung auf die neueste (bzw.
den leeren Zustand) zurück. „Neue Unterhaltung“ öffnet `/assistent/neu`, einen
lokalen leeren Zustand: Das System legt erst mit der ersten gesendeten Frage eine Unterhaltung an (die URL
wechselt dann per `replace` auf deren ID), ohne Frage bleibt auf dem Server nichts zurück. Ist kein KI-Anbieter eingerichtet (`llmConfigured` aus `/api/dashboard`),
sagt die Seite das vor der ersten Frage. **[Muss]**

#### Szenario: Neuladen
- **WENN** ein Benutzer in der neuen Oberfläche eine ältere Unterhaltung wählt und die Seite neu lädt
- **DANN** ist dieselbe Unterhaltung geöffnet

#### Szenario: Neu ohne Frage
- **WENN** jemand in der neuen Oberfläche „Neue Unterhaltung“ wählt und keine Frage sendet
- **DANN** enthält `GET /api/chats` keine zusätzliche Unterhaltung

#### Szenario: Seitenwechsel mit halber Frage
- **WENN** jemand eine Frage tippt, zur Dokumentation wechselt und zurückkommt
- **DANN** steht der getippte Text noch im Eingabefeld

Quelle: `frontend/src/pages/ChatPage.tsx`, `frontend/src/lib/drafts.ts`

### Requirement: Unterhaltung löschen (UI)
Die neue Oberfläche MUSS die geöffnete Unterhaltung über „⋯ → Unterhaltung löschen …“ löschen lassen, erst
nach einem Prüfdialog, der Titel und das Löschen aller Nachrichten nennt und sagt, dass es sich nicht
rückgängig machen lässt. Während eine Antwort läuft, ist Löschen gesperrt. Die Rechte erzwingt das Backend
(Mitglied nur eigene, ADMIN alle); sie ist keine Fähigkeit des Assistenten (kein LLM-Werkzeug). **[Muss]**

#### Szenario: Löschen mit Prüfdialog
- **WENN** jemand „Unterhaltung löschen …“ wählt und „Abbrechen“ klickt
- **DANN** bleibt die Unterhaltung bestehen; bei Bestätigung ist sie weg

#### Szenario: Nach dem Löschen
- **WENN** eine Unterhaltung gelöscht wurde
- **DANN** öffnet die Seite die neueste verbleibende (sonst den leeren Zustand), entfernt deren Eingabe-Entwurf und zeigt „Unterhaltung gelöscht“; Zurück/Neuladen auf die gelöschte ID fällt ohne Fehler zurück

#### Szenario: Fremde Unterhaltung als ADMIN
- **WENN** ADMIN eine Unterhaltung eines anderen Benutzers löscht
- **DANN** nennt der Dialog zusätzlich „Sie gehört <Benutzer>.“

Quelle: `frontend/src/pages/ChatPage.tsx`

### Requirement: Nachricht senden — Vorbedingungen und Fehler
Das System MUSS eine nicht-leere Nachricht verlangen (sonst Validierungsfehler 422), bei unbekannter
Unterhaltung 404 liefern und, wenn der gewählte Anbieter nicht Ollama ist und kein API-Schlüssel
hinterlegt ist, mit 400 und einem Hinweis auf „Einstellungen -> KI-Assistent“ ablehnen, bevor ein
Anbieter kontaktiert wird. Ein Fehler des Anbieters MUSS als 502 „Der KI-Anbieter meldet: …“
zurückkommen. **[Muss]**

#### Szenario: Kein Schlüssel
- **WENN** Anbieter DEEPSEEK gewählt und kein `deepseekApiKey` gespeichert ist
- **DANN** antwortet das System mit 400 „Es ist noch kein KI-Zugang eingerichtet. …“

Quelle: `backend/app/main.py:1511`, `backend/app/main.py:1514`, `backend/app/main.py:1523`, `backend/app/main.py:1532`

### Requirement: Agentenschleife mit Werkzeugen
Das System MUSS je Benutzernachricht das LLM wiederholt aufrufen, angeforderte Werkzeuge ausführen,
deren Ergebnisse zurückgeben und enden, sobald das LLM eine Antwort ohne Werkzeugaufruf liefert.
Nach höchstens 8 LLM-Aufrufen MUSS die Schleife enden und eine feste Antwort speichern, die um
Eingrenzung der Frage bittet. **[Muss]** (Grenze 8 ist **[Impl]**.)

Die Antwort MUSS enthalten: gespeicherte Assistentennachricht (inkl. Gesamtdauer der Runde in ms),
verwendetes Modell (leer beim Abbruch), Liste der benutzten Werkzeugnamen in Aufrufreihenfolge und
summierte Token-Zahlen (`promptTokens`, `completionTokens`). Modellwahl mit Zweck `CHAT`.

#### Szenario: Werkzeugkette
- **WENN** der Benutzer „Der Drucker druckt nicht“ schreibt und das LLM erst `list_systems`, dann `ping_host` anfordert
- **DANN** enthält `toolsUsed` `["list_systems", "ping_host"]` und die Antwort basiert auf beiden Ergebnissen

#### Szenario: Iterationsgrenze
- **WENN** das LLM bei allen 8 LLM-Aufrufen einer Antwort Werkzeuge anfordert
- **DANN** speichert das System „Ich habe mehrere Prüfungen hintereinander durchgeführt … Magst du die Frage etwas eingrenzen …“ und `model` ist leer

Quelle: `backend/app/tools.py:35`, `backend/app/tools.py:448`, `backend/app/tools.py:462`, `backend/app/tools.py:483`

### Requirement: Jeder Zwischenschritt wird gespeichert
Das System MUSS die Benutzernachricht vor dem ersten LLM-Aufruf speichern und jeden Assistentenschritt
mit Werkzeugaufrufen sowie jedes Werkzeugergebnis sofort speichern, sodass ein Abbruch einen lesbaren,
wieder abspielbaren Verlauf hinterlässt. Der vollständige gespeicherte Verlauf (inkl. Tool-Verkehr)
wird bei jeder Runde als Kontext an das LLM gegeben. **[Muss]**

Anbieter-Rohdaten eines Assistentenschritts (Claude-Thinking-Blöcke mit Signatur, Gemini
`thoughtSignature`) MÜSSEN unverändert zurückgespielt werden **[Impl]**.

#### Szenario: Abbruch während Werkzeug
- **WENN** der Anbieter nach dem ersten Werkzeugaufruf mit HTTP 500 antwortet
- **DANN** enthält der gespeicherte Verlauf Benutzernachricht, Werkzeugaufruf und -ergebnis, und die API antwortet 502

Quelle: `backend/app/tools.py:452`, `backend/app/tools.py:476`, `backend/app/tools.py:434`, `backend/app/llm_providers.py:124`

### Requirement: Werkzeugfehler und Ergebnisgröße
Das System MUSS jeden Werkzeugfehler (auch unbekannte Werkzeuge und ungültige Argumente) als
Ergebnis `{"error": "…"}` an das LLM zurückgeben statt die Runde abzubrechen, und Ergebnisse als JSON
auf 6000 Zeichen kürzen, mit dem Zusatz „Ergebnis gekürzt -- bitte gezielter nachfragen …“. **[Muss]**
(6000 ist **[Impl]**.)

#### Szenario: Unbekanntes Werkzeug
- **WENN** das LLM `reboot_router` anfordert
- **DANN** erhält es `{"error": "Unbekanntes Werkzeug 'reboot_router'."}`

Quelle: `backend/app/tools.py:34`, `backend/app/tools.py:233`, `backend/app/tools.py:403`

### Requirement: Systemprompt mit aktuellem Stand
Das System MUSS als Systemprompt einen festen deutschen Text verwenden (Du-Form, Fachbegriffe
erklären, erst messen dann fragen, von unten nach oben prüfen, nichts erfinden, keine Zugangsdaten
erfragen, Messung schlägt Doku), in dem der Name des Zuhauses eingesetzt ist (Fallback „diesem
Haushalt“). Ist `systemPromptOverride` nicht leer, ersetzt er diesen Text vollständig. In jedem Fall
MUSS ein je Runde neu erzeugter Zustandsblock angehängt werden: Zeitstempel (UTC), Anzahl Geräte und
davon erreichbar, ausgewählte Netzwerk-Bereiche (oder „automatisch erkannt“), Gateway-IP (oder „nicht
ermittelt“), letzter Scan mit Status (oder „noch keiner“). Der Zustandsblock DARF keine Prozesse
starten (keine Host-Interface-Erkennung). **[Muss]**

#### Szenario: Netze im Zustandsblock
- **WENN** ein Controller-Netz 192.168.20.0/24 ausgewählt und 10.0.0.0/24 als Freitext eingetragen ist
- **DANN** enthält der Zustandsblock „192.168.20.0/24, 10.0.0.0/24“; ohne Auswahl „automatisch erkannt“

Quelle: `backend/app/tools.py:415`, `backend/app/tools.py:428`, `backend/app/prompts.py:10`, `backend/app/prompts.py:55`, Test: `backend/tests/test_tools_network_overview.py::test_state_block`

### Requirement: Fähigkeitsgrenze des Assistenten
Das System MUSS die Fähigkeiten des LLM auf eine feste Werkzeugliste begrenzen, die für In-App-Chat
und MCP identisch ist: lesender Zugriff auf Inventar, Dokumentation, Zugangs-Metadaten und Container,
begrenzte Live-Diagnosen sowie als einzige verändernde Fähigkeit `set_switch`. Kein Werkzeug DARF
Inventar, Dokumentation, Zugänge, Einstellungen, Container oder Hosts verändern. Eine neue
verändernde Fähigkeit erfordert eine neue Architekturentscheidung (ADR 0004). **[Muss]**

Werkzeuggruppen (Details, Schemas und Grenzen: [llm-tools](../../contracts/llm-tools.md)):
- Inventar: `list_systems` (Filter `kind`, `query`, `onlyOnline`), `get_system`, `network_overview`, `list_containers`
- Dokumentation: `list_documentation`, `get_documentation`
- Zugänge: `list_accounts` (ohne Passwörter)
- Schalten: `list_switches`, `set_switch`
- Diagnose: `internet_check`, `ping_host` (1–10 Versuche, Standard 3), `check_port`, `dns_lookup`, `reverse_dns`, `http_check`, `traceroute` (1–30 Hops, Standard 15); Ausführung siehe [diagnose](../diagnose/spec.md)

#### Szenario: Kein Schreibwerkzeug
- **WENN** der Benutzer den Assistenten bittet, ein Gerät umzubenennen oder einen Container neu zu starten
- **DANN** steht dem LLM kein Werkzeug dafür zur Verfügung

Quelle: `backend/app/tools.py:1`, `backend/app/tools.py:38`, `backend/app/mcp_server.py:39`

### Requirement: Geheimnisse erreichen nie das LLM
Das System DARF gespeicherte Passwörter, Schlüssel, Passphrasen oder Tokens nie in einen Prompt, ein
Werkzeugergebnis oder den Chatverlauf geben. `list_accounts` liefert nur ID, Bezeichnung, Kategorie,
Benutzername, URL, Notiz, Geräte-ID und `hasSecret` (bool) samt Hinweis „Passwörter werden hier
bewusst nicht ausgegeben.“ Werkzeuge, die ein Geheimnis brauchen (`list_switches`, `set_switch` für
Home Assistant), MÜSSEN es serverseitig entschlüsseln und verwenden. **[Muss]**

#### Szenario: Zugang nachfragen
- **WENN** der Benutzer nach dem Router-Passwort fragt
- **DANN** kann der Assistent nur sagen, dass und wo ein Zugang hinterlegt ist (`hasSecret: true`)

Quelle: `backend/app/tools.py:316`, `backend/app/tools.py:379`

### Requirement: Eigene Notizen gelten als verlässlicher
Das System MUSS beim Lesen eines Doku-Kapitels die eigenen Notizen der Bewohner getrennt vom
erzeugten Text liefern und als verlässlicher kennzeichnen; die Kapitelliste MUSS zeigen, ob ein
Kapitel eigene Notizen hat. Unbekannter Slug → Ergebnis mit `error`. **[Muss]**

#### Szenario: Kapitel mit Notiz
- **WENN** `get_documentation` für ein Kapitel mit Notiz aufgerufen wird
- **DANN** enthält das Ergebnis `eigeneNotizen` und den Hinweis, dass dieser Teil verlässlicher ist

Quelle: `backend/app/tools.py:296`, `backend/app/tools.py:303`. Doku-Inhalte: [dokumentation](../dokumentation/spec.md)

### Requirement: Netzwerk-Überblick für das LLM
Das System MUSS mit `network_overview` den Namen des Zuhauses, die ausgewählten Scan-Netze
(`configuredSubnets` als CIDR-Liste oder „automatisch erkannt“), deren Herkunft (`subnetSources`
nur mit den Schlüsseln `cidr`, `source` [`controller`|`freitext`], `name`, `vlan`), Geräteanzahl,
erreichbare Geräte, Anzahl je Kategorie und den letzten Scan liefern. Controller-Netze kommen zuerst;
veraltete IDs und inaktive Netze zählen nicht. Es DARF dabei kein Prozess gestartet werden. **[Muss]**

#### Szenario: Nur Controller-Netz
- **WENN** nur das Controller-Netz „IoT“ (VLAN 20) ausgewählt ist
- **DANN** ist `subnetSources` = `[{"cidr": "192.168.20.0/24", "source": "controller", "name": "IoT", "vlan": 20}]`

#### Szenario: Inaktives Netz
- **WENN** das ausgewählte Netz beim letzten Controller-Abgleich fehlte
- **DANN** ist `configuredSubnets` = „automatisch erkannt“

Quelle: `backend/app/tools.py:278`, `backend/app/tools.py:410`, Tests: `backend/tests/test_tools_network_overview.py::test_overview_controller_only`, `::test_overview_free_text_only`, `::test_overview_empty_is_automatic`, `::test_overview_mixed_and_keys`, `::test_overview_stale_id_is_automatic`, `::test_overview_inactive_network_is_automatic`

### Requirement: Schalten von Lampen und Steckdosen (`set_switch`)
Das System MUSS dem Assistenten (jede Rolle, jeder MCP-Client) erlauben, ohne Rückfrage ein Shelly-
Relais (Kanal 0) oder eine Home-Assistant-Entity ein- oder auszuschalten. Ziele MÜSSEN serverseitig
aus der Datenbank aufgelöst werden (Shelly: `systemId` eines Inventargeräts → dessen IP/Hostname;
HA: `accountId` eines Zugangs der Kategorie `homeassistant` → dessen URL/Token), nie aus vom LLM
gelieferten Adressen. Bei Home Assistant MÜSSEN nur die Domänen `switch` und `light` geschaltet
werden; Shelly-Befehle gehen nur an Geräte, deren Hersteller oder Modell „Shelly“ enthält (dieselbe
Prüfung wie `list_switches` und die Oberfläche). Jeder Schaltversuch MUSS mit Aktion
`switch.assistant`, Ziel, Ergebnis und Auslöser (angemeldeter Benutzer im Chat bzw. „MCP: <Token-
Bezeichnung>“) ins Zugriffsprotokoll. `list_switches` liefert die Shelly-Geräte und höchstens 200
HA-Entities der Domänen switch/light. **[Muss]** (Produktentscheidung, ADR 0011/0004, bestätigt in #43.)

#### Szenario: Kein Shelly
- **WENN** `set_switch` mit `kind=shelly` und der `systemId` eines NAS aufgerufen wird
- **DANN** wird kein Befehl gesendet und das Ergebnis ist „Kein Shelly-Gerät mit dieser systemId gefunden …“

#### Szenario: Schloss verweigert
- **WENN** das LLM `set_switch` mit `kind=ha`, `entityId=lock.haustuer` aufruft
- **DANN** wird keine Anfrage an Home Assistant gesendet und das Ergebnis ist ein Fehler „… geschaltet werden dürfen hier nur switch/light-Entities …“

#### Szenario: Unbekannte Geräte-ID
- **WENN** `set_switch` mit `kind=shelly` und unbekannter `systemId` aufgerufen wird
- **DANN** lautet das Ergebnis „Kein Shelly-Gerät mit dieser systemId gefunden -- vorher list_switches aufrufen.“

Quelle: `backend/app/tools.py:335`, `backend/app/tools.py:352`, `backend/app/switch_admin.py:24`, `backend/app/switch_admin.py:27`, `backend/app/switch_admin.py:53`,
`switch_admin.is_shelly`, `tools.current_actor`, Tests: `backend/tests/test_chat_owner_and_switch.py`

### Requirement: Externer MCP-Endpunkt
Das System MUSS unter `/api/mcp` einen MCP-Server (Streamable HTTP, zustandslos, JSON-Antworten)
anbieten, der exakt die Werkzeugliste und -ausführung des In-App-Assistenten bereitstellt (Name,
Beschreibung, Eingabeschema; Ergebnis als ein Textblock mit demselben JSON). Jede HTTP-Anfrage MUSS
ein gültiges `Authorization: Bearer <token>` tragen; sonst 401 mit
`{"error": "Kein gültiges MCP-Token. Siehe Einstellungen -> MCP-Server."}` und Header
`WWW-Authenticate: Bearer realm="homeatlas-mcp"`. Bei gültigem Token MUSS „zuletzt benutzt“ des
Tokens aktualisiert werden. Sitzungscookie und Zwei-Faktor-Anmeldung gelten hier nicht. **[Muss]**

#### Szenario: Ohne Token
- **WENN** ein Client `/api/mcp` ohne Authorization-Header aufruft
- **DANN** antwortet das System mit 401, ohne die Anfrage an den MCP-Server weiterzureichen

#### Szenario: Tool-Aufruf über MCP
- **WENN** ein Client mit gültigem Token `tools/call` für `network_overview` sendet
- **DANN** erhält er denselben JSON-Text wie der In-App-Assistent, und `lastUsedAt` des Tokens ist jetzt

Quelle: `backend/app/main.py:70`, `backend/app/main.py:61`, `backend/app/mcp_server.py:39`, `backend/app/mcp_server.py:47`, `backend/app/mcp_server.py:55`, `backend/app/mcp_server.py:58`, `backend/app/db.py:601`

### Requirement: MCP-Tokens verwalten
Das System MUSS Admins erlauben, MCP-Tokens mit Bezeichnung zu erzeugen, aufzulisten und zu
widerrufen. Eine leere/nur aus Leerzeichen bestehende Bezeichnung MUSS mit 400 „Bitte eine
Bezeichnung angeben.“ abgelehnt werden (Bezeichnung wird getrimmt). Der Tokenwert (hohe Entropie,
heute 32 Byte URL-sicher) MUSS genau einmal, in der Antwort auf das Erzeugen, ausgegeben werden; die
Liste enthält nur ID, Bezeichnung, Erstellt- und Zuletzt-benutzt-Zeitpunkt, neueste zuerst. Ein
widerrufenes Token MUSS sofort ungültig sein; Widerruf einer unbekannten ID ist kein Fehler.
**[Muss]**

#### Szenario: Einmalige Anzeige
- **WENN** ein Admin ein Token „Claude Desktop“ erzeugt und danach die Liste lädt
- **DANN** enthält nur die Erzeugungsantwort das Feld `token`, die Liste nicht

#### Szenario: Widerruf
- **WENN** ein Admin ein Token widerruft
- **DANN** erhält der nächste MCP-Aufruf mit diesem Token 401

Quelle: `backend/app/main.py:450`, `backend/app/main.py:455`, `backend/app/main.py:462`, `backend/app/db.py:575`, `backend/app/db.py:589`

## Daten

Siehe [data-model](../../contracts/data-model.md).

- Schreibt `chats` (`id`, `title`, `createdAt`, `updatedAt`) und `chatMessages` (`chatId`, `role` user|assistant|tool, `content`, `toolCalls`, `providerRaw`, `toolCallId`, `name`, `createdAt`, `durationMs`).
- Schreibt `apiTokens` (`id`, `label`, `token` im Klartext, `createdAt`, `lastUsedAt`).
- Schreibt `accessLog` (Aktion `switch.assistant`).
- Liest `systems`, `accounts` (ohne Geheimnis; HA-Token nur serverseitig), `docPages`, `scans`, `networkResources`, `settings` (`llmProvider`, Schlüssel/Modelle/Base-URLs des Anbieters, `providerModelCache`, `homeName`, `systemPromptOverride`, `scanSubnets`, `scanControllerNetworkIds`).

## Schnittstellen

| Methode | Pfad | Rolle | Zweck |
|---|---|---|---|
| GET | /api/chats | MEMBER | Alle Unterhaltungen, neueste Aktivität zuerst |
| POST | /api/chats | MEMBER | Unterhaltung anlegen |
| DELETE | /api/chats/{chat_id} | MEMBER | Unterhaltung samt Nachrichten löschen |
| GET | /api/chats/{chat_id}/messages | MEMBER | Verlauf (nur user/assistant mit Inhalt) |
| POST | /api/chats/{chat_id}/messages | MEMBER | Nachricht `{message}` senden → `{message, model, toolsUsed, usage}` |
| GET | /api/settings/mcp-tokens | ADMIN | Tokenliste ohne Tokenwert |
| POST | /api/settings/mcp-tokens | ADMIN | Token `{label}` erzeugen; Antwort `{token: {id, label, token, createdAt, lastUsedAt}}`, der Wert `token.token` nur hier einmalig (`backend/app/main.py:455`) |
| DELETE | /api/settings/mcp-tokens/{token_id} | ADMIN | Token widerrufen |
| MOUNT | /api/mcp | MCP-Token (Bearer) | MCP Streamable HTTP, Werkzeuge des Assistenten |

„MEMBER“ heißt: jede angemeldete Rolle mit Zwei-Faktor-Anmeldung. Anbieter-/Schlüssel-Konfiguration:
[einstellungen-und-llm-provider](../einstellungen-und-llm-provider/spec.md). Direkte Schalt-Routen
(`/shelly-switch`, `/ha-switch`, admin-only) gehören nicht zu dieser Fähigkeit.

UI-Seite(n): `frontend/src/pages/ChatPage.tsx` (Routen `/assistent`, `/assistent/:chatId`); MCP-Tokens im Tab „MCP-Server“ von
`frontend/src/pages/SettingsPage.tsx` (Route `/einstellungen`, nur Admin).

## Nicht-Ziele und Grenzen

- Kein Streaming der Antwort; die Antwort kommt nach Abschluss der ganzen Runde.
- Keine privaten Unterhaltungen je Benutzer, keine Freigabe, kein Export.
- Keine Bestätigungsstufe vor `set_switch`.
- Kein MCP-Ressourcen-/Prompt-Angebot, nur Werkzeuge; keine OAuth-Anmeldung, kein Token-Scope.
- Sprach-Eingabe (Browser-Spracherkennung, `de-DE`) ist reine UI-Funktion.

## Ist-Implementierung (nur Referenz, [Impl])

- Werkzeugdefinitionen sind ein internes Schema (`name`, `description`, `inputSchema`) und werden je Anbieter übersetzt (Anthropic `input_schema`, Gemini mit Schema-Allowlist, OpenAI `function`).
- Gemini liefert keine Aufruf-IDs; als ID dient der Funktionsname.
- MCP über das Python-SDK (`StreamableHTTPSessionManager`, `stateless=True`, `json_response=True`), eigene ASGI-Bearer-Prüfung statt SDK-OAuth.
- Tokens liegen im Klartext in der DB (wie Sitzungstokens); Begründung im Schema-Kommentar.
- Home-Assistant-Aufrufe ohne TLS-Prüfung (`verify=False`); Shelly-Generation wird je Schaltvorgang über `GET /shelly` ermittelt (Gen1 `/relay/0?turn=`, Gen2+ `/rpc/Switch.Set`), Timeout 8 s (Verbindung 3 s).
- UI zeigt unter der Antwort „Dafür geprüft: …“ (deduplizierte `toolsUsed`) und die Dauer.

## OFFEN

- > OFFEN: `list_switches` nutzt jeden HA-Zugang unabhängig vom Opt-in „Zum Auslesen verwenden“ und fragt bei jedem Aufruf live alle HA-Instanzen ab.
- > OFFEN: Scheitert eine Runde (502), bleibt die Benutzernachricht gespeichert; die UI legt sie zurück ins Eingabefeld → beim erneuten Senden doppelt im Verlauf. Umbenennung passiert auch bei gescheiterter Runde.
- > OFFEN: Keine Gesamtzeitgrenze je Runde: bis zu 8 LLM-Aufrufe à 120 s plus Werkzeuge.
- > OFFEN: `systemPromptOverride` ist nur per API setzbar (keine UI) und ersetzt den Prompt ohne Platzhalter-Ersetzung (`{home_name}` bliebe wörtlich).
- > OFFEN: Kein Rate-Limit auf `/api/mcp`; `lastUsedAt` wird bei jeder Anfrage geschrieben.
- > OFFEN: Eine Nachricht nur aus Leerzeichen erfüllt die Mindestlänge 1 und wird gesendet; als erste Nachricht ergibt sie einen leeren Chat-Titel.
