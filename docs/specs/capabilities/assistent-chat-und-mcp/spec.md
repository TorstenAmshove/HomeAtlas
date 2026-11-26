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

Die Oberfläche legt nichts an, solange keine Frage gestellt wird (siehe „Unterhaltung in der URL …“).

#### Szenario: Automatischer Titel
- **WENN** die erste Nachricht in einer Unterhaltung mit Titel „Neue Unterhaltung“ gesendet wird
- **DANN** und die Runde erfolgreich war, wird die Unterhaltung auf die ersten 60 Zeichen der (getrimmten) Nachricht umbenannt; scheitert die Runde, bleibt der Titel „Neue Unterhaltung“

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
- **WENN** ein Benutzer eine ältere Unterhaltung wählt und die Seite neu lädt
- **DANN** ist dieselbe Unterhaltung geöffnet

#### Szenario: Neu ohne Frage
- **WENN** jemand „Neue Unterhaltung“ wählt und keine Frage sendet
- **DANN** enthält `GET /api/chats` keine zusätzliche Unterhaltung

#### Szenario: Seitenwechsel mit halber Frage
- **WENN** jemand eine Frage tippt, zur Dokumentation wechselt und zurückkommt
- **DANN** steht der getippte Text noch im Eingabefeld

Quelle: `frontend/src/pages/ChatPage.tsx`, `frontend/src/lib/drafts.ts`

### Requirement: Unterhaltung löschen (UI)
Die Oberfläche MUSS die geöffnete Unterhaltung über „⋯ → Unterhaltung löschen …“ löschen lassen, erst
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
Das System MUSS die Nachricht trimmen und eine nicht-leere (auch nicht nur aus Leerzeichen bestehende) verlangen (sonst Validierungsfehler 422, nichts wird gespeichert), bei unbekannter
Unterhaltung 404 liefern und, wenn der gewählte Anbieter nicht Ollama ist und kein API-Schlüssel
hinterlegt ist, mit 400 und einem Hinweis auf „Einstellungen -> KI-Assistent“ ablehnen, bevor ein
Anbieter kontaktiert wird. Ein gespeicherter, aber nicht lesbarer Schlüssel (Schlüsseldatei geändert)
zählt dabei als nicht hinterlegt und wird nie leer an den Anbieter geschickt. Ein Fehler des Anbieters MUSS als 502 „Der KI-Anbieter meldet: …“
zurückkommen; der Verlauf bleibt dabei unverändert. **[Muss]**

#### Szenario: Nur Leerzeichen
- **WENN** die Nachricht nur aus Leerzeichen besteht
- **DANN** antwortet das System mit 422 und legt keine Nachricht an

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

### Requirement: Gesamtzeitgrenze je Runde
Das System MUSS eine Chat-Runde (alle LLM-Aufrufe und Werkzeuge zusammen) nach spätestens 240 Sekunden beenden (unter dem 300-s-Proxy-Timeout von nginx für `/api/`). Dabei MUSS jeder noch unbeantwortete Werkzeugaufruf eine Werkzeugnachricht „Abgebrochen: Zeitgrenze der Runde erreicht.“ erhalten, damit der Verlauf gültig bleibt, und das System speichert eine Assistentennachricht, die den Abbruch nach 4 Minuten erklärt; `model` ist leer. Folgerunden funktionieren normal. **[Muss]** (240 s **[Impl]**)

#### Szenario: Hängender Werkzeugaufruf
- **WENN** ein Werkzeug die Zeitgrenze überschreitet
- **DANN** endet die Runde mit der Abbruchmeldung und `duration_ms` gesetzt

Quelle: `backend/app/tools.py` (`_TURN_DEADLINE_S`)

### Requirement: Jeder Zwischenschritt wird gespeichert
Das System MUSS die Benutzernachricht vor dem ersten LLM-Aufruf speichern und jeden Assistentenschritt
mit Werkzeugaufrufen sowie jedes Werkzeugergebnis sofort speichern. Scheitert die Runde (502 oder
unerwarteter Fehler), nimmt das System sie vollständig zurück: Benutzernachricht und Zwischenschritte
dieser Runde werden gelöscht, frühere Nachrichten bleiben, denn die Oberfläche legt den Text zurück
ins Eingabefeld und ein Rest im Verlauf würde beim erneuten Senden doppelt erscheinen. Der vollständige gespeicherte Verlauf (inkl. Tool-Verkehr)
wird bei jeder Runde als Kontext an das LLM gegeben. **[Muss]**

Anbieter-Rohdaten eines Assistentenschritts (Claude-Thinking-Blöcke mit Signatur, Gemini
`thoughtSignature`) MÜSSEN unverändert zurückgespielt werden **[Impl]**.

#### Szenario: Abbruch während Werkzeug
- **WENN** der Anbieter nach dem ersten Werkzeugaufruf mit HTTP 500 antwortet
- **DANN** antwortet die API 502 und der Verlauf enthält nichts von dieser Runde (Benutzernachricht, Werkzeugaufruf und -ergebnis sind zurückgenommen)

Tests: `backend/tests/test_chat_send_errors.py`

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
Haushalt“). Ist `systemPromptOverride` nicht leer, ersetzt er diesen Text vollständig; darin wird `{home_name}` durch den Namen des Zuhauses ersetzt (Fallback wie oben), andere geschweifte Klammern bleiben wörtlich. Admins pflegen ihn unter Einstellungen → KI-Assistent. In jedem Fall
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
begrenzte Live-Diagnosen, lesende Live-Abfragen an Home Assistant und den lokalen Docker-Host (siehe unten) sowie als einzige
verändernde Fähigkeit `set_switch`. Kein Werkzeug DARF
Inventar, Dokumentation, Zugänge, Einstellungen, Container oder Hosts verändern. Eine neue
verändernde Fähigkeit erfordert eine neue Architekturentscheidung (ADR 0004). **[Muss]**

Werkzeuggruppen (Details, Schemas und Grenzen: [llm-tools](../../contracts/llm-tools.md)):
- Inventar: `list_systems` (Filter `kind`, `query`, `onlyOnline`), `get_system`, `network_overview`, `list_containers` (Stand des letzten Scans, inkl. `dockerSocket` für Container mit gemountetem `docker.sock`)
- Dokumentation: `list_documentation`, `get_documentation`
- Zugänge: `list_accounts` (ohne Passwörter)
- Erreichbarkeit: `list_exposure` (nur aus der Datenbank, begrenzt auf 15 Zeilen je Liste mit Kürzungshinweis, Filter `host`, ohne Geheimnisse und ohne Quell-Zugangs-IDs, kein Live-DNS)
- Firewall: `check_firewall_path` (Pfadbewertung je Station aus gespeicherten Fakten, von HomeAtlas ausgewertet) und `list_firewall_rules` (höchstens 15 Regeln, Regelnamen bereinigt, kein Live-Zugriff), siehe [firewall](../firewall/spec.md)
- Schalten: `list_switches`, `set_switch`
- Home Assistant live (nur lesend): `get_ha_state`, `get_ha_history`, `get_ha_logbook`, `get_ha_error_log`, `list_ha_traces`, `get_ha_trace`
- UniFi live (nur lesend): `get_unifi_client`, `get_unifi_device`, `get_unifi_network`, `get_unifi_events`
- Proxmox live (nur lesend): `get_proxmox_guest`, `get_proxmox_node`
- Docker live (nur lesend, nur lokaler Host): `get_container_status`
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
Das System MUSS dem Assistenten (jede Rolle, jeder MCP-Client) erlauben, ohne Rückfrage eine Home-Assistant-Entity ein- oder auszuschalten. Ziele MÜSSEN serverseitig
aus der Datenbank aufgelöst werden (`accountId` eines Zugangs der Kategorie `homeassistant` → dessen URL/Token), nie aus vom LLM
gelieferten Adressen. Bei Home Assistant MÜSSEN nur die Domänen `switch` und `light` geschaltet
werden, dazu `cover`-Entities mit `device_class` blind/shade/shutter/curtain/awning per `action` open/close/stop (keine Position; `device_class` wird live vor dem POST gelesen; garage/gate/door und fehlende `device_class` gesperrt; `on` nur für switch/light, `action` nur für cover). Shelly-Relais werden nicht mehr direkt geschaltet (ADR-0023): `kind=shelly` wird abgewiesen. Jeder Schaltversuch MUSS mit Aktion
`switch.assistant`, Ziel, Ergebnis und Auslöser (angemeldeter Benutzer im Chat bzw. „MCP: <Token-
Bezeichnung>“) ins Zugriffsprotokoll. `list_switches` liefert höchstens 200
HA-Entities der Domänen switch/light und erlaubte Rollos. Home-Assistant-Zugänge MÜSSEN das Opt-in „Zum Auslesen verwenden“ (`allowProbe`) haben, sonst werden sie bei `list_switches` übersprungen (nicht kontaktiert; ohne freigegebenen Zugang steht `haHinweis` in der Antwort) und `set_switch` MUSS vor Entschlüsselung, Senden und Protokollieren mit einem Fehler abweisen. **[Muss]** (Produktentscheidung, ADR-0013, ADR-0023, bestätigt in #43, #99; Opt-in #121.)

`list_switches` MUSS bei jedem Aufruf je freigegebenem HA-Zugang den aktuellen Zustand live lesen (ein
`GET /api/states`, kein Cache); die Antwort enthält den aktuellen `state`. `set_switch` löst Zugang und
Opt-in je Aufruf frisch aus der Datenbank auf und verlässt sich nicht auf Daten aus `list_switches`.
Begründung: Der Assistent soll nie einen veralteten Zustand melden („Licht ist an“, obwohl es gerade
ausgeschaltet wurde), ein Cache brächte zusätzlichen Zustand samt Invalidierung (Opt-in entzogen, Token
geändert) in die Fähigkeitsgrenze von `tools.py`, und ein `GET /api/states` ist im Heimnetz günstig.
**[Muss]** (Entscheidung #246.)

#### Szenario: Zustand immer live
- **WENN** `list_switches` zweimal nacheinander aufgerufen wird und sich der Zustand einer Entity in Home Assistant dazwischen ändert
- **DANN** kontaktiert der zweite Aufruf Home Assistant erneut und liefert den neuen `state`

#### Szenario: Zugang ohne Opt-in
- **WENN** `set_switch` mit `kind=ha` und der `accountId` eines Zugangs ohne „Zum Auslesen verwenden“ aufgerufen wird
- **DANN** kommt `{"error": …}` mit Hinweis auf den Haken, nichts wird gesendet oder protokolliert

#### Szenario: Shelly wird nicht mehr direkt geschaltet
- **WENN** `set_switch` mit `kind=shelly` aufgerufen wird, auch mit der `systemId` eines Shelly-Geräts
- **DANN** wird kein Befehl gesendet und das Ergebnis ist „Unbekannte Art 'shelly', erwartet 'ha'.“

#### Szenario: Schloss verweigert
- **WENN** das LLM `set_switch` mit `kind=ha`, `entityId=lock.haustuer` aufruft
- **DANN** wird keine Anfrage an Home Assistant gesendet und das Ergebnis ist ein Fehler „… geschaltet werden dürfen hier nur switch/light-Entities …“

#### Szenario: Garagentor verweigert
- **WENN** das LLM `set_switch` mit `kind=ha`, `entityId=cover.garage` (`device_class` garage) und `action=open` aufruft
- **DANN** wird kein POST gesendet und das Ergebnis ist ein Fehler „… ist kein Rollo …“

#### Szenario: Rollo fährt
- **WENN** `set_switch` mit `entityId=cover.buero` (`device_class` shutter) und `action=close` aufgerufen wird
- **DANN** ruft das System `cover/close_cover` auf und protokolliert `switch.assistant`

#### Szenario: Unbekannter Zugang
- **WENN** `set_switch` mit `kind=ha` und unbekannter `accountId` aufgerufen wird
- **DANN** lautet das Ergebnis „Kein Home-Assistant-Zugang mit dieser accountId gefunden -- vorher list_switches aufrufen.“

Quelle: `backend/app/tools.py:335`, `backend/app/tools.py:352`, `backend/app/switch_admin.py:24`, `backend/app/switch_admin.py:27`, `tools.current_actor`, Tests: `backend/tests/test_chat_owner_and_switch.py`

### Requirement: Live-Lesen von UniFi-Clients
Das System MUSS dem Assistenten (jede Rolle, jeder MCP-Client) mit `get_unifi_client` die Live-Werte
eines aktuell verbundenen Clients aus der klassischen UniFi-API anbieten (Signal, Rauschen, Kanal,
Datenrate, Retries, `roam_count`, Access Point, Uptime, Zufriedenheit). Der Client wird per MAC (jede
Schreibweise), IP oder Name (auch Inventarname) angegeben; mehrere Treffer ergeben eine Kandidatenliste,
nie eine Vermutung. Es DARF nur der feste GET-Pfad `stat/sta` mit `X-API-Key` des Zugangs der Kategorie
`unifi` abgerufen werden ([ADR-0016](../../../adr/0016-unifi-scan-nur-mit-api-key.md));
Antworten MÜSSEN eine Feld-Positivliste durchlaufen, der Key DARF nie in Ergebnis, Fehlertext oder Log
erscheinen, nichts wird gespeichert. Fehlt Zugang, URL oder Key oder ist der Controller nicht
erreichbar, MUSS eine feste, verständliche Meldung statt eines Fehlers kommen.

Nur Zugänge mit Opt-in „Zum Auslesen verwenden“ werden benutzt; ohne Haken kommt ein Fehler mit Hinweis.

Weitere UniFi-Live-Werkzeuge mit denselben Regeln (Positivliste, Key nur als `X-API-Key`, feste
Meldungen, nichts gespeichert; nur `site` ist als validierter Pfadteil frei):
`get_unifi_device` (GET `stat/device`; ein Gerät per MAC/IP/Name mit Status, Last, Uplink, reduzierter
Port-Tabelle und Funkauslastung, ohne Angabe eine Übersicht von höchstens 50 Geräten; Geräte-Geheimnisse
wie `x_authkey` oder `guest_token` erscheinen nie), `get_unifi_network` (GET `stat/health` sowie v2
`firewall-policies`/`firewall/zone`; Zustand von WAN/LAN/WLAN/VPN ohne WAN-IP, Nameserver und Gateways,
Firewall nur als Zähler je Aktion plus die 50 Regeln mit den meisten Treffern, ohne Adress- und
Portlisten) und `get_unifi_events` (der **eine** lesende POST `v2/…/system-log/all` mit einem Body aus
intern berechneten Ganzzahlen; Fenster 1–168 Stunden, Standard 24; bis zu 5 Seiten à 50, neueste zuerst;
Filter `client` und `severity`, Admin-Aktivität ausgeblendet; je Parameter nur der Name, nie die IP; das
Ergebnis nennt, wie viele Ereignisse durchsucht wurden, und dass „kein Treffer“ nicht „keine Probleme“
heißt; der Ereignisschlüssel erscheint als `kennung`).

Ist bei `get_unifi_events` ein `client` angegeben, MUSS das System vor den Ereignisseiten einmal den
GET-Pfad `stat/sta` lesen (kein neuer Pfad, ADR-0017 unverändert) und die Kennungen aus Anfrage und
Inventar mit den aktuellen Werten des Clients ergänzen: Gesucht wird über MAC oder Name (nur wenn keins
von beiden bekannt ist, über die IP). Passt genau ein verbundener Client, kommt dessen aktuelle MAC zu den
bekannten hinzu und dessen aktuelle IP ersetzt die bekannten IPs, weil eine veraltete Inventar-IP nach
einem DHCP-Wechsel schon einem anderen Gerät gehören kann. Schlägt `stat/sta` fehl, ist der Client nicht
verbunden oder passen mehrere, wird wie bisher mit den Inventarwerten gefiltert, und der `hinweis` nennt
mit festem Text, dass die Live-Ergänzung nicht möglich war (nie ein harter Fehler, nie der Fehlertext des
Controllers). Nichts aus `stat/sta` erscheint im Ergebnis, nichts wird gespeichert; ohne `client` gibt es
keinen Zusatzaufruf. **[Muss]** (Entscheidung #248.)

Quelle: `backend/app/tools.py` (`_dispatch_unifi_live`, `_pick_unifi_account`, `_client_identifiers`), `backend/app/unifi_live.py` (`_request`, `client_status`, `_live_client_identifiers`, `events`, `CLIENT_FIELDS`, `redact`, `_bounded`), Tests: `backend/tests/test_unifi_live.py`, `backend/tests/test_tools_unifi_live.py`

#### Szenario: Verbundener WLAN-Client
- **WENN** der Assistent `get_unifi_client` mit der MAC eines WLAN-Clients aufruft
- **DANN** enthält das Ergebnis Signal, Retries und Roaming-Zähler, aber keine Geheimnisse

#### Szenario: Kein UniFi-Zugang
- **WENN** kein Zugang der Kategorie `unifi` existiert
- **DANN** nennt die Antwort das und verweist auf das Inventar des letzten Scans

#### Szenario: Gerät ohne Geheimnisse
- **WENN** der Assistent `get_unifi_device` für einen Access Point aufruft
- **DANN** enthält das Ergebnis Status, Uplink, Port-Fehler und Funk-Retries, aber weder `x_authkey` noch andere nicht freigegebene Felder

#### Szenario: Ereignisse eines Clients
- **WENN** der Assistent `get_unifi_events` mit `client` und `hours` 500 aufruft
- **DANN** wird das Fenster auf 168 Stunden begrenzt und das Ergebnis nennt die Zahl der durchsuchten Ereignisse

#### Szenario: Client mit neuer IP
- **WENN** der Assistent `get_unifi_events` für einen Client aufruft, dessen IP im Inventar veraltet ist, und `stat/sta` ihn eindeutig mit neuer IP zeigt
- **DANN** werden seine Ereignisse über die neue IP und MAC gefunden, Ereignisse des Geräts mit der alten IP nicht

#### Szenario: Live-Ergänzung nicht möglich
- **WENN** `stat/sta` fehlschlägt, den Client nicht zeigt oder mehrere Clients passen
- **DANN** wird mit den Inventarwerten gefiltert und der `hinweis` nennt, dass die Live-Ergänzung nicht möglich war

### Requirement: Live-Lesen von Proxmox-Gästen und -Hosts
Das System MUSS dem Assistenten (jede Rolle, jeder MCP-Client) mit `get_proxmox_guest` den Live-Zustand einer
VM oder eines LXC-Containers und mit `get_proxmox_node` den eines Proxmox-Hosts anbieten
([ADR-0021](../../../adr/0021-proxmox-live-lesepfade.md)). Ein Gast wird per VMID (nur Ziffern) oder Name
angegeben; mehrere Treffer ergeben eine Kandidatenliste, Templates werden übersprungen. Das Ergebnis enthält
Status (läuft/gestoppt, Uptime, Sperre, HA), aktuelle Last (CPU, RAM, Disk, Netzwerk, Disk-IO), einen
verdichteten Verlauf (`timeframe` `hour` oder `day`: Durchschnitt, Maximum, höchstens 12 Stützpunkte) und die
letzten 10 Aufgaben (Typ, Status, Start, Ende, Benutzer). Es DÜRFEN nur GET-Aufrufe auf die feste Pfad-Allowlist
von `proxmox_live.py` gehen; Antworten MÜSSEN eine Feld-Positivliste durchlaufen. Freitext des Gasts (Notizen,
Tags), Aufgaben-Log-Text, UPIDs und das Token-Secret DÜRFEN nie im Ergebnis, Fehlertext oder Log erscheinen;
nichts wird gespeichert. Der Zugang ist der Scan-Token (Kategorie `proxmox`) und braucht „Zum Auslesen
verwenden“; fehlen Zugang, Opt-in, Token-ID oder Secret, oder ist der Host nicht erreichbar bzw. verweigert den
Zugriff, MUSS eine feste, verständliche Meldung statt eines Fehlers kommen.

Quelle: `backend/app/tools.py` (`_dispatch_proxmox_live`, `_pick_proxmox_account`), `backend/app/proxmox_live.py` (`_request`, `guest_status`, `node_status`), Tests: `backend/tests/test_proxmox_live.py`, `backend/tests/test_tools_proxmox_live.py`

#### Szenario: Zustand einer VM
- **WENN** der Assistent `get_proxmox_guest` mit dem Namen einer VM aufruft
- **DANN** enthält das Ergebnis Status, Last, Verlauf und die letzten Aufgaben, aber weder Notizen, Log-Text noch Token

#### Szenario: Mehrdeutiger Name
- **WENN** ein Name als VM und als Container existiert
- **DANN** nennt die Antwort die Kandidaten mit VMID und Node und rät nicht

#### Szenario: Kein Zugang oder kein Opt-in
- **WENN** kein Proxmox-Zugang existiert oder „Zum Auslesen verwenden“ fehlt
- **DANN** nennt die Antwort das, und es geht kein Netzwerkaufruf raus

> OFFEN: Noch nicht gegen eine echte Proxmox-Instanz abgenommen (Version nach der Abnahme hier vermerken). → #249

### Requirement: Live-Status lokaler Container
Das System MUSS dem Assistenten (jede Rolle, jeder MCP-Client) mit `get_container_status` den Live-Zustand der
Docker-Container des HomeAtlas-Hosts anbieten ([ADR-0022](../../../adr/0022-container-live-status.md)). Die einzige
Anfrage an die Docker-API ist `GET /containers/json?all=1` (`docker_probe.live_containers`); der Inspect-Pfad
`/containers/{id}/json` und jede andere Methode als GET DÜRFEN dafür nie verwendet werden. Das Ergebnis enthält je
Container nur: Name, Image (ohne `user:pass@`), State, Status-Text, Exit-Code mit kurzer Einordnung (z. B. 137 „vom
System beendet, oft Speicher voll“, 0 „regulär beendet“), Health (healthy/unhealthy/starting, leer ohne
Healthcheck), „seit“ (z. B. „Up 2 hours“, „Exited 3 minutes ago“) und Compose-Projekt. Env-Werte, Command,
Entrypoint, Mounts, Ports und alle Labels außer dem Compose-Projekt DÜRFEN nie ausgegeben werden. Der Parameter
`container` (optional, höchstens 100 Zeichen; Name, Compose-Dienst, Inventar-ID oder Teilstring des Namens) wird nur
mit der Live-Liste verglichen, nie in einen Pfad eingesetzt; leer liefert alle. Höchstens 50 Container pro Antwort,
eine Kürzung wird angezeigt. Ohne Docker-Socket, bei Verbindungs- oder HTTP-Fehlern (auch 403 eines Socket-Proxys)
oder ungültiger Antwort MUSS eine feste, verständliche Meldung statt eines Fehlers kommen. Kein Log, keine
Steuerung, keine Container entfernter Hosts (dort gilt `list_containers`).

Die Regel in `prompts.py` (`CHAT_SYSTEM`) MUSS verlangen: Kann der Assistent etwas nicht selbst tun, erklärt er die
vermutliche Ursache aus dem gemessenen Status, sagt klar, dass der Admin es erledigen muss, formuliert eine kurze
Nachricht an den Admin (Gerät/Dienst, Symptom, Zeitpunkt, Status) und behauptet nie, etwas ausgeführt zu haben. Das
gilt für alle Rollen. MCP bietet keine Prompts; dort trägt die Werkzeugbeschreibung den Hinweis. **[Muss]**

Quelle: `backend/app/docker_probe.py` (`live_containers`, `_live_row`, `_parse_status`), `backend/app/tools.py` (`_container_status`), `backend/app/prompts.py`, Tests: `backend/tests/test_docker_probe.py`, `backend/tests/test_tools_container_status.py`

#### Szenario: Gestoppter Container
- **WENN** der Assistent `get_container_status` für einen Container mit Status „Exited (137) 3 minutes ago“ aufruft
- **DANN** nennt das Ergebnis State `exited`, Exit-Code 137 mit der Einordnung „vom System beendet, oft Speicher voll“

#### Szenario: Neu startender und kranker Container
- **WENN** ein Container „Restarting (1) 5 seconds ago“ bzw. „Up 2 hours (unhealthy)“ meldet
- **DANN** zeigt das Ergebnis State `restarting` mit Exit-Code 1 bzw. Health `unhealthy`

#### Szenario: Nur erlaubte Felder
- **WENN** die Docker-Antwort Env, Command, Mounts und zusätzliche Labels mit Geheimnissen enthält
- **DANN** kommt nichts davon im Ergebnis vor, nur das Compose-Projekt

#### Szenario: Kein Socket
- **WENN** der Docker-Socket nicht eingebunden ist oder die Docker-API nicht antwortet
- **DANN** nennt die Antwort das verständlich, und es wird keine Ausnahme geworfen

### Requirement: Live-Lesen von Home Assistant
Das System MUSS dem Assistenten (jede Rolle, jeder MCP-Client) lesende Live-Abfragen an Home
Assistant anbieten: `get_ha_state` (Zustand, höchstens 50 Entities, Filter `entityIds`/`domain`/`query`),
`get_ha_history` (Verlauf einer Entity mit Auswertung: Anzahl Wechsel, Anzahl `on`, Sekunden je
Zustand), `get_ha_logbook` (inkl. `context_entity_id`/`context_domain`/`context_service` als
Ursache), `get_ha_error_log` (letzte 200 Zeilen, höchstens 20 000 Zeichen) sowie `list_ha_traces`
(letzte 10 Läufe einer `automation.*`/`script.*`) und `get_ha_trace` (Trigger, Bedingungen, Ablauf,
Fehler eines Laufs, höchstens 16 000 Zeichen). Es DÜRFEN nur GET-Aufrufe und die WebSocket-Befehle
`trace/list`/`trace/get` sowie als Rückfall bei HTTP 404 auf `/api/error_log` `system_log/list` gesendet werden ([ADR-0018](../../../adr/0018-wan-status-und-lesepfade.md)). Zeiträume MÜSSEN auf 1–7 Tage (Standard 7) und Eintragszahlen auf
200 (Verlauf) bzw. 100 (Logbuch) begrenzt werden; Kürzung MUSS im Ergebnis als `truncated` und
`note` stehen. Texte aus Fehlerlog, Logbuch, Zuständen und Fehlermeldungen MÜSSEN vor dem Kürzen
geschwärzt werden (Bearer-Tokens, JWTs, `token`/`password`/`secret`/`api_key`-Werte,
`user:pass@`-URLs). Das Zugriffstoken verlässt den Server nie. Gibt es mehrere Zugänge der Kategorie
`homeassistant`, MUSS `accountId` angegeben werden; ohne Zugang oder bei Fehlern kommt ein
`{"error": …}` statt einer Ausnahme. Nur Zugänge mit dem Opt-in „Zum Auslesen verwenden“ werden benutzt; ohne Haken (oder bei einer `accountId` ohne Haken) kommt ein Fehler mit diesem Stichwort. **[Muss]** (#121. YAML-Automationen ohne `id` haben keine Traces.)

#### Szenario: Wie oft war das Licht an
- **WENN** das LLM `get_ha_history` mit `entityId=light.x` und `days=30` aufruft
- **DANN** wird auf 7 Tage gekürzt, `note` sagt das, und `summary.onCount` enthält die Anzahl

#### Szenario: Mehrere Zugänge
- **WENN** zwei Home-Assistant-Zugänge existieren und `accountId` fehlt
- **DANN** lautet das Ergebnis ein Fehler mit der Liste aus ID und Bezeichnung

Quelle: `backend/app/tools.py` (`_dispatch_ha_read`), `backend/app/probe_auth.py` (`ha_get_states`, `ha_history`, `ha_logbook`, `ha_error_log`, `ha_traces`, `_ha_ws_call`, `ha_redact`), Tests: `backend/tests/test_probe_auth_ha_live.py`, `backend/tests/test_tools_ha_live.py`, `backend/tests/test_probe_auth_ha_ws.py`

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

#### Szenario: Zu viele Anfragen
- **WENN** ein Token mehr als 120 Anfragen innerhalb einer Minute sendet
- **DANN** antwortet das System mit 429 und `Retry-After`; andere Tokens sind nicht betroffen, ungültige Tokens bleiben 401

#### Szenario: Tool-Aufruf über MCP
- **WENN** ein Client mit gültigem Token `tools/call` für `network_overview` sendet
- **DANN** erhält er denselben JSON-Text wie der In-App-Assistent, und `lastUsedAt` des Tokens ist gesetzt (aktualisiert nur, wenn der alte Wert leer oder älter als 60 s ist)

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
- Schreibt `apiTokens` (`id`, `label`, `token` als SHA-256-Hash des Rohwerts, `createdAt`, `lastUsedAt`).
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
gibt es nicht (entfallen mit ADR-0023).

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
- Tokens liegen nur als SHA-256-Hash in der DB (wie Sitzungstokens, #251); die MCP-Authentifizierung hasht den Bearer-Wert vor dem Vergleich. Test: `backend/tests/test_token_hashing.py`.
- Home-Assistant-Aufrufe ohne TLS-Prüfung (`verify=False`); Timeout 8 s (Verbindung 3 s).
- UI zeigt unter der Antwort „Dafür geprüft: …“ (deduplizierte `toolsUsed`) und die Dauer.

## OFFEN

