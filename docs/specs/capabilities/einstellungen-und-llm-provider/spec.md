# Einstellungen und LLM-Provider

> Status: Ist-Verhalten, aus dem Code zurückgewonnen (Stand 0159807). Quellen als `datei:zeile`.

## Zweck

Der Administrator stellt an einer Stelle ein, wie HomeAtlas arbeitet: Name des Zuhauses,
KI-Anbieter (Claude, OpenAI/OpenRouter, Gemini, DeepSeek oder lokales Ollama) mit Schlüssel und
Modell, Scan- und Überwachungsverhalten sowie einen Standard-Zugang fürs Auslesen. Schlüssel lassen
sich vor dem Speichern testen, verfügbare Modelle direkt beim Anbieter abrufen. Mitglieder sehen von
den Einstellungen nur, was sie für die Oberfläche brauchen.

## Rollen und Rechte

| Aktion | ADMIN | MEMBER |
|---|---|---|
| Einstellungen lesen | alle Schlüssel, Geheimnisse maskiert | nur `homeName`, `setupCompleted` (+ Anbieterliste, Katalog, OUI-/Docker-Status) |
| Einstellungen ändern | ja | nein |
| Modelle beim Anbieter abrufen | ja | nein |
| Verbindung zum Anbieter testen | ja | nein |

## Settings-Schlüssel

Alle Einstellungen bilden ein einziges Dokument. Default gilt, solange nichts gespeichert ist.
Sichtbar für MEMBER sind nur Zeilen mit „M“. Sem. Details der Scan-/Monitor-Schlüssel stehen in den
verlinkten Fähigkeiten. Quelle Defaults: `backend/app/db.py:408`.

| Schlüssel | Default | Bedeutung | Gelesen von |
|---|---|---|---|
| `homeName` (M) | „Mein Zuhause“ | Name des Zuhauses (Überschrift, Prompts, Topologie) | tools, main (Dashboard), topology |
| `setupCompleted` (M) | false | Ersteinrichtung abgeschlossen; regulär durch [setup-wizard](../setup-wizard/spec.md) gesetzt (`main.py:1692`), aber auch per `PATCH /api/settings` beliebig setz- und rücksetzbar (`main.py:434`, siehe OFFEN) | main (`/api/health`, Dashboard) |
| `llmProvider` | `DEEPSEEK` | Gewählter Anbieter: `CLAUDE`, `OPENAI`, `GEMINI`, `DEEPSEEK`, `OLLAMA` | tools, docs, classify, main |
| `claudeApiKey` | „“ | Geheimnis, maskiert | llm_providers |
| `claudeModel` | `auto` | Modell-ID oder `auto` | llm_providers |
| `claudeBaseUrl` | „“ | leer = `https://api.anthropic.com/v1` | llm_providers |
| `openAiApiKey` / `openAiModel` / `openAiBaseUrl` | „“ / `auto` / „“ | leer = `https://api.openai.com/v1` (auch OpenRouter u. ä.) | llm_providers |
| `geminiApiKey` / `geminiModel` | „“ / `auto` | Gemini; Adresse nicht konfigurierbar | llm_providers |
| `deepseekApiKey` / `deepseekModel` | „“ / `auto` | DeepSeek | llm_providers |
| `deepseekBaseUrl` | (fehlt in Defaults) | leer = `https://api.deepseek.com/v1` | llm_providers |
| `ollamaApiKey` / `ollamaModel` / `ollamaBaseUrl` | (fehlen in Defaults) | Ollama; Schlüssel optional; leer = `http://localhost:11434/v1` | llm_providers |
| `providerModelCache` | `{}` | Je Anbieter `{models: [{id, label}]}` aus „Modelle laden“ | llm_providers, main |
| `systemPromptOverride` | „“ | Ersetzt den Chat-Systemprompt (keine UI) | tools, siehe [assistent-chat-und-mcp](../assistent-chat-und-mcp/spec.md) |
| `scanSubnets` | `[]` | Freitext-Netze für Scans | discovery |
| `scanControllerNetworkIds` | `[]` | Ausgewählte Controller-Netze (IDs) | discovery, tools |
| `scanControllerNetworksSeen` | `[]` | Beim letzten Speichern angezeigte Netz-IDs (Markierung „neu“) | nur UI |
| `scanTimeoutMs` | 700 | Timeout je Probe (min. 100 ms wirksam) | discovery |
| `scanConcurrency` | 128 | Parallelität, wirksam 8–512 | discovery |
| `scanEnableMdns`, `scanEnableSsdp`, `scanEnableDocker`, `scanEnableUnifi`, `scanEnableOmada`, `scanEnableProxmox`, `scanEnableAdguard`, `scanEnableTraefik`, `scanEnableUnifiClassic`, `scanEnableExposureFiles`, `scanEnableHttpBanner` | true | Quellen einzeln abschaltbar | discovery, pipeline |
| `scanEnableFirewallUnifi` | false | UniFi-Firewall-Zonen und -Regeln lesen (Opt-in, ADR-0017, [firewall](../firewall/spec.md)) | pipeline |
| `scanUseLlm` | true | KI-Einordnung und KI-Doku-Einleitungen | pipeline, docs, main |
| `scanExcludeIps` | `[]` | Auszuschließende IPs | discovery |
| `scanExtraTargets` | `[]` | Einzelziele außerhalb der Netze | pipeline |
| `scanUseCredentials` | true | Auslesen mit Zugangsdaten | pipeline |
| `scanAutoEnabled` | false | Automatischer Scan | pipeline |
| `scanAutoIntervalHours` | 24 | Intervall, wirksam 1–720 h | pipeline |
| `configVersionKeep` | 50 | Aufbewahrte Konfig-Backups je Gerät, wirksam 1–1000 | db |
| `monitorEnabled` | true | Überwachung wichtiger Geräte | monitor, main |
| `monitorIntervalSeconds` | 10 | Intervall, wirksam 5–600 s | monitor, main |
| `monitorTimeoutMs` | 1500 | Timeout je TCP-Portprüfung, wirksam ≥ 200 ms; gilt nicht für den Ping (fest `-W 2`, 1 Paket; `monitor.py:141`, `diagnostics.py:75`) | monitor |
| `defaultCredentialEnabled` | false | Standard-Zugang fürs Auslesen aktiv | probe_auth |
| `defaultCredentialUsername` | „“ | leer = `root` | probe_auth |
| `defaultCredentialIsKey` | false | Geheimnis ist SSH-Schlüssel | probe_auth |
| `defaultCredentialSecretEnc` | „“ | verschlüsselt, nie ausgeliefert | probe_auth |
| `defaultCredentialPassphraseEnc` | „“ | verschlüsselt, nie ausgeliefert | probe_auth |
| `defaultCredentialPort` | 0 | 0 = Port 22 | probe_auth |
| `dnsTestNames` | `www.google.com`, `heise.de`, `github.com` | Namen für den DNS-Selbsttest | main (`/api/diagnostics/dns`) |

Fachliche Details: [discovery-und-scan](../discovery-und-scan/spec.md),
[klassifikation-llm](../klassifikation-llm/spec.md), [credentialed-probing](../credentialed-probing/spec.md),
[monitoring](../monitoring/spec.md), [diagnose](../diagnose/spec.md),
[netzwerkressourcen-vlans](../netzwerkressourcen-vlans/spec.md), [dokumentation](../dokumentation/spec.md).

## Anforderungen

### Requirement: Einstellungen als Dokument mit Defaults
Das System MUSS Einstellungen als ein Dokument speichern, beim Lesen fehlende Schlüssel mit den
Defaults auffüllen und Änderungen als flaches Zusammenführen anwenden: nur übermittelte Schlüssel
ändern sich, alle anderen bleiben erhalten. Änderungen MÜSSEN beim nächsten Lesen wirksam sein
(kein Neustart). **[Muss]**

#### Szenario: Teil-Update
- **WENN** erst `scanControllerNetworkIds=["a"]`, `scanControllerNetworksSeen=["a","b"]` und danach nur `homeName="X"` gespeichert wird
- **DANN** sind beide Netz-Listen unverändert und der Default von `scanControllerNetworkIds` bleibt `[]`

Quelle: `backend/app/db.py:462`, `backend/app/db.py:474`, Test: `backend/tests/test_main_settings_api.py::test_controller_network_selection_roundtrip`

### Requirement: Einstellungs-Reiter in der URL
Die Seite MUSS den offenen Reiter in `?tab=` halten (`general`, `llm`, `scan`, `monitor`,
`mcp`, `account`, `display`, `about`), sodass Zurück und Neuladen auf ihm landen; ein Reiter, den die
Rolle nicht hat, fällt auf den ersten erlaubten zurück (MEMBER: Konto). Auf dem Desktop MUSS
die Seite die Reiter als Liste links zeigen und auf dem Handy als Liste mit
Unterseite (ohne `?tab=` die Liste); mit ungespeicherten Änderungen MUSS ein Reiterwechsel nachfragen
(„Verwerfen und wechseln“ / „Hier bleiben“) und das Verlassen der Seite ebenso; Einstellungen werden
dabei nicht zwischengespeichert (sie können API-Schlüssel enthalten). „Token widerrufen“ liegt unter
„⋯“ mit Prüfdialog. Ein
MEMBER sieht genau Konto, Darstellung und Über. **[Muss]** (Layout **[Impl]**)

#### Szenario: Zurück landet im Reiter
- **WENN** jemand im Reiter „Netzwerk-Scan“ eine andere Seite öffnet und Zurück drückt
- **DANN** ist wieder „Netzwerk-Scan“ offen (beide Oberflächen)

Quelle: `frontend/src/pages/SettingsPage.tsx`, `frontend/src/pages/mehr/mehr.css`

### Requirement: Rollenabhängige Sicht
Das System MUSS beim Lesen der Einstellungen MEMBER nur `homeName` und `setupCompleted` zeigen; ADMIN
sieht alle Schlüssel (maskiert). Beide erhalten zusätzlich die Anbieterliste mit Anzeigenamen, den
Modellkatalog je Anbieter (`id`, `label`, `price_tier`), ob die Herstellerdatenbank geladen ist und
wie viele Einträge sie hat, und ob der Docker-Socket verfügbar ist. Ändern, Modelle laden und
Verbindung testen MÜSSEN Admins vorbehalten sein (sonst 403). **[Muss]**

#### Szenario: Mitglied liest
- **WENN** ein MEMBER `GET /api/settings` aufruft
- **DANN** enthält `settings` genau `homeName` und `setupCompleted`

Quelle: `backend/app/main.py:422`, `backend/app/main.py:434`, `backend/app/main.py:480`, `backend/app/main.py:487`

### Requirement: Geheimnisse maskiert, nie im Klartext zurück
Das System DARF gespeicherte API-Schlüssel nie ausliefern: ein gesetzter Schlüssel erscheint als
`********`, ein leerer als „“. Verschlüsselt gespeicherte Felder (Standard-Zugang: Geheimnis,
Passphrase) DÜRFEN weder im Klartext noch als Chiffrat ausgeliefert werden; stattdessen meldet das
System `hasDefaultCredentialSecret` / `hasDefaultCredentialPassphrase` (bool). API-Schlüssel
werden verschlüsselt gespeichert und nur im Moment eines Anbieter-Aufrufs entschlüsselt
(`llm_providers.api_key_for`); Klartext-Schlüssel älterer Versionen werden beim Start verschlüsselt.
**[Muss]** (Test: `backend/tests/test_secrets_at_rest.py`)

#### Szenario: Gespeicherter Claude-Schlüssel
- **WENN** `claudeApiKey` gesetzt ist
- **DANN** liefert `GET /api/settings` `"claudeApiKey": "********"`

Quelle: `backend/app/main.py:383`, `backend/app/main.py:386`, `backend/app/main.py:393`

### Requirement: Maskierte Werte beim Zurückschreiben
Das System MUSS beim Speichern den Maskenwert `********` eines API-Schlüssels als „unverändert“
behandeln. Für den Standard-Zugang nimmt es Klartext unter dem Namen ohne `Enc`
(`defaultCredentialSecret`, `defaultCredentialPassphrase`) entgegen, speichert ihn verschlüsselt und
behandelt einen leeren Wert als „unverändert“; mitgeschickte `has…`-Felder werden verworfen. Die
Antwort ist das zusammengeführte, maskierte Dokument. **[Muss]**

#### Szenario: Anderes Feld ändern
- **WENN** die UI das ganze Formular mit `"claudeApiKey": "********"` und geändertem `homeName` speichert
- **DANN** bleibt der echte Claude-Schlüssel erhalten

#### Szenario: Passwort leer gelassen
- **WENN** `defaultCredentialSecret: ""` gesendet wird
- **DANN** bleibt das gespeicherte Geheimnis unverändert

Quelle: `backend/app/main.py:404`, `backend/app/main.py:435`

### Requirement: Anbieterauswahl
Das System MUSS fünf Anbieter unterstützen — `CLAUDE` („Anthropic Claude API“), `OPENAI` („OpenAI
API / OpenRouter“), `GEMINI` („Google Gemini API“), `DEEPSEEK` („DeepSeek API (günstig)“), `OLLAMA`
(„Ollama / lokaler Server (kostenlos, ohne Cloud)“) — mit je eigenem Schlüssel, Modell und (außer
Gemini) überschreibbarer Server-Adresse. Ollama MUSS ohne Schlüssel funktionieren; bei leerem Schlüssel
wird kein Authorization-Header gesendet. OpenAI, DeepSeek und Ollama sprechen das OpenAI-kompatible
`/chat/completions`-Format. Der Client MUSS anbieterneutral ohne Hersteller-SDK arbeiten (ADR 0006).
**[Muss]**

#### Szenario: Ollama lokal
- **WENN** `llmProvider=OLLAMA` ohne Schlüssel und ohne Adresse gewählt ist
- **DANN** gehen Anfragen an `http://localhost:11434/v1/chat/completions` ohne Authorization-Header

Quelle: `backend/app/model_catalog.py:14`, `backend/app/model_catalog.py:19`, `backend/app/model_catalog.py:65`, `backend/app/llm_providers.py:83`, `backend/app/llm_providers.py:302`, `backend/app/llm_providers.py:328`

### Requirement: Anthropic-spezifische Korrektheit
Das System DARF an Anthropic keine Sampling-Parameter (`temperature`, `top_p`, `top_k`) senden und
`thinking` nie explizit konfigurieren; Thinking-Blöcke einer Antwort mit Werkzeugaufrufen MÜSSEN
im nächsten Aufruf unverändert zurückgespielt werden. **[Muss]**

Details **[Impl]**: `max_tokens` 8192 (Thinking teilt sich das Budget), Header `anthropic-version:
2023-06-01`, Schlüssel im Header `x-api-key`. Andere Anbieter erhalten `temperature` 0.2; Gemini erhält
den Schlüssel als Query-Parameter `key`.

#### Szenario: Anfrage an Claude
- **WENN** der Assistent mit Anbieter CLAUDE eine Frage beantwortet
- **DANN** enthält der Request-Body weder `temperature` noch `thinking`

Quelle: `backend/app/llm_providers.py:1`, `backend/app/llm_providers.py:30`, `backend/app/llm_providers.py:33`, `backend/app/llm_providers.py:116`, `backend/app/llm_providers.py:151`

### Requirement: Modellauswahl „Automatisch“
Das System MUSS je Anbieter eine explizite Modell-ID oder `auto` erlauben. Eine explizite ID MUSS
unverändert verwendet werden. `auto` MUSS je Zweck auflösen: `CHAT` (Assistent, Geräte-Einordnung) →
schnellstes/günstigstes Katalogmodell (erster Eintrag), `ANALYSIS` (Doku-Texte) → Flaggschiff (letzter
Eintrag). Gibt es eine geladene Live-Liste, gewinnt das bevorzugte Katalogmodell, wenn es darin
enthalten ist, sonst der erste (CHAT) bzw. letzte (ANALYSIS) Eintrag der Live-Liste. Ergibt sich kein
Modell, MUSS der Aufruf mit „Kein Modell ausgewählt -- bitte unter Einstellungen -> KI-Assistent eines
wählen.“ scheitern. **[Muss]**

Kuratierter Katalog **[Impl]**: CLAUDE `claude-haiku-4-5`, `claude-sonnet-5`, `claude-opus-5`; OPENAI
`gpt-4o-mini`, `gpt-4o`; GEMINI `gemini-2.0-flash`, `gemini-2.5-pro`; DEEPSEEK `deepseek-chat`,
`deepseek-reasoner`; OLLAMA leer (nur Live-Liste).

#### Szenario: Doku mit Claude auf Automatisch
- **WENN** `claudeModel=auto` und keine Live-Liste geladen ist
- **DANN** nutzt der Chat `claude-haiku-4-5` und die Doku-Einleitung `claude-opus-5`

#### Szenario: Ollama ohne Live-Liste
- **WENN** `llmProvider=OLLAMA` und weder Modell noch Live-Liste vorhanden sind
- **DANN** scheitert jeder KI-Aufruf mit „Kein Modell ausgewählt …“

Quelle: `backend/app/model_catalog.py:35`, `backend/app/model_catalog.py:76`, `backend/app/llm_providers.py:92`, `backend/app/llm_providers.py:337`

### Requirement: Modelle beim Anbieter laden
Das System MUSS mit dem aktuellen, ungespeicherten Formularstand (maskierte Werte = gespeicherter
Wert) die Modellliste des Anbieters abrufen und bei Erfolg unter `providerModelCache[<Anbieter>]` als
`{models: [{id, label}]}` speichern, nach ID sortiert. Andere Formularwerte werden dabei nicht
gespeichert. Bei Gemini zählen nur Modelle mit `generateContent`. Bei Netzwerkfehler, HTTP ≥ 400,
Nicht-JSON-Antwort („stimmt die Server-Adresse?“) oder leerer Liste MUSS `ok=false` mit Meldung
zurückkommen und der Cache unverändert bleiben. Erfolgsmeldung: „<n> Modelle gefunden.“ **[Muss]**

Details **[Impl]**: Timeout 30 s (Verbindung 10 s); Claude `GET /models?limit=100`; OpenAI-kompatibel
`GET /models`; Gemini `GET …/v1beta/models`.

#### Szenario: Schlüssel noch nicht gespeichert
- **WENN** ein Admin einen neuen OpenAI-Schlüssel eintippt und „Modelle laden“ wählt
- **DANN** wird mit dem eingetippten Schlüssel abgefragt, der Schlüssel selbst aber nicht gespeichert

Quelle: `backend/app/main.py:473`, `backend/app/main.py:487`, `backend/app/llm_providers.py:353`

### Requirement: Verbindung testen
Das System MUSS mit dem ungespeicherten Formularstand eine echte Mini-Anfrage („Antworte nur mit dem
einzelnen Wort OK.“) an genau das Modell stellen, das verwendet würde, und `{ok, message, model}`
liefern; gespeichert wird nichts. Eine leere Textantwort MUSS als Erfolg mit Hinweis gelten.
Fehlermeldungen MÜSSEN verständlich unterscheiden: unbekanntes/unzugängliches Modell („Das Modell
'<id>' gibt es bei diesem Anbieter nicht …“), abgelehnter Schlüssel („Der API-Schlüssel wurde
abgelehnt.“), Netzwerkfehler, kein Modell; die Rohantwort wird angehängt. Bei Erfolg enthält
`message` die Antwort (max. 200 Zeichen). **[Muss]**

#### Szenario: Falsche Modell-ID
- **WENN** `claudeModel=claude-gibtsnicht` getestet wird und Anthropic `not_found_error` liefert
- **DANN** ist `ok=false` und `message` beginnt mit „Das Modell 'claude-gibtsnicht' gibt es bei diesem Anbieter nicht“

Quelle: `backend/app/main.py:480`, `backend/app/llm_providers.py:406`, `backend/app/llm_providers.py:411`, `backend/app/llm_providers.py:426`

### Requirement: Fehler und Zeitgrenzen der Anbieter
Das System MUSS Anbieterfehler (HTTP ≥ 400, unerwartete Antwortstruktur, unbekannter Anbieter) als
eigene Fehlerart mit HTTP-Code und gekürzter Rohantwort (max. 500 Zeichen) melden, die Aufrufer
abfangen können. KI-Aufrufe MÜSSEN begrenzt sein: heute 120 s gesamt, 10 s Verbindungsaufbau
**[Impl]**.

#### Szenario: Anbieter antwortet 429
- **WENN** OpenAI mit HTTP 429 antwortet
- **DANN** meldet der Client „HTTP 429: …“ und der Chat antwortet mit 502

Quelle: `backend/app/llm_providers.py:26`, `backend/app/llm_providers.py:36`, `backend/app/llm_providers.py:307`

### Requirement: Betrieb ohne KI
Das System MUSS ohne konfigurierten KI-Anbieter voll nutzbar bleiben (Inventar, Scan, Doku mit
festen Texten); nur Chat und KI-Texte fallen weg. **[Muss]**

#### Szenario: Kein Schlüssel
- **WENN** kein Schlüssel hinterlegt ist und ein Scan läuft
- **DANN** entsteht die Doku mit festen Einleitungstexten und der Chat meldet 400 „Es ist noch kein KI-Zugang eingerichtet.“

Quelle: `backend/app/docs.py:477`, `backend/app/main.py:1523`

## Daten

Siehe [data-model](../../contracts/data-model.md).

- Liest/schreibt `settings` (eine Zeile, Schlüssel `app`, Wert = JSON-Dokument aller oben gelisteten Schlüssel).
- Schreibt `providerModelCache` innerhalb dieses Dokuments.
- Verschlüsselung der `…Enc`-Felder über den gemeinsamen Schlüssel (siehe [zugangsdaten](../zugangsdaten/spec.md)).

## Schnittstellen

| Methode | Pfad | Rolle | Zweck |
|---|---|---|---|
| GET | /api/settings | MEMBER | Einstellungen (rollenabhängig gefiltert, maskiert) + `providers`, `catalog`, `ouiLoaded`, `ouiEntries`, `dockerAvailable` |
| PATCH | /api/settings | ADMIN | Teil-Update (beliebige Schlüssel) → `{settings}` maskiert |
| POST | /api/settings/llm/models | ADMIN | `{provider, settings}` → `{ok, message, models}`; speichert Cache |
| POST | /api/settings/llm/test | ADMIN | `{provider, settings}` → `{ok, message, model}` |

„MEMBER“ heißt: jede angemeldete Rolle. Weitere Routen unter `/api/settings/…` gehören zu anderen
Fähigkeiten: MCP-Tokens → [assistent-chat-und-mcp](../assistent-chat-und-mcp/spec.md), OUI-Refresh →
[discovery-und-scan](../discovery-und-scan/spec.md). Ob ein Anbieter konfiguriert ist, zeigt das
[dashboard](../dashboard/spec.md) (`llmConfigured`).

UI-Seite(n): `frontend/src/pages/SettingsPage.tsx` (Route `/einstellungen`; Tabs Allgemein, KI-Assistent, Netzwerk-Scan, Überwachung, MCP-Server nur für
Admins; Konto und Über für alle; Darstellung (System · Hell · Dunkel, pro Browser) für alle); offener Reiter in `?tab=`.

## Nicht-Ziele und Grenzen

- Keine Einstellungen pro Benutzer; keine Umgebungsvariablen für diese Werte. Der Hell/Dunkel-Modus gilt pro Browser
  (`localStorage`), nicht pro Konto.
- Kein Änderungsverlauf und kein Zugriffsprotokoll für Einstellungsänderungen.
- Keine serverseitige Validierung von Typen, Wertebereichen oder erlaubten Schlüsseln (siehe OFFEN).
- Kein Streaming, kein Prompt-Caching, keine Kostenanzeige.

## Ist-Implementierung (nur Referenz, [Impl])

- Ein JSON-Blob in Tabelle `settings` unter Schlüssel `app`; Defaults im Code, nicht in der DB.
- Wertebereiche werden erst beim Lesen im jeweiligen Modul geklemmt (siehe Tabelle „wirksam“); die UI setzt nur `min`/`max` am Eingabefeld.
- Die UI speichert in mehreren Tabs das gesamte Formular (`save(form)`), auf dem Allgemein-Tab nur `homeName`.
- Gemini-Tool-Schemas werden auf eine Schlüssel-Allowlist reduziert (Gemini lehnt Unbekanntes ab).

## OFFEN

- > OFFEN: Ein leer gesendeter API-Schlüssel löscht ihn, ein leer gesendetes Standard-Zugang-Geheimnis bleibt erhalten — uneinheitliche Semantik. → #124
- > OFFEN: `PATCH /api/settings` akzeptiert beliebige Schlüssel und Typen, auch `setupCompleted` oder ein rohes `defaultCredentialSecretEnc`. → #124
- > OFFEN: UI-Fehler: Nach „Modelle laden“ wird nur `data`, nicht `form` aktualisiert; die neue Liste erscheint erst nach Neuladen, und ein anschließendes „Speichern“ schreibt den alten `providerModelCache` zurück. → #125
- > OFFEN: Die Live-Liste wird nach ID sortiert gespeichert; der Fallback „erster/letzter Eintrag“ in `resolve` wählt dadurch alphabetisch, nicht nach Anbieter-Reihenfolge (Docstring geht von Anbieterreihenfolge aus). → #125
- > OFFEN: `providerModelCache` wird bei Wechsel von Schlüssel oder Server-Adresse nicht verworfen. → #125
- > OFFEN: Claude-Modellabruf holt höchstens 100 Modelle, ohne Paginierung. → #125
- > OFFEN: Ollama-, `deepseekBaseUrl`-Schlüssel fehlen in den Defaults (funktional egal, aber unvollständig dokumentiert). → #124
- > OFFEN: Test/Modelle-Laden schicken Anfragen an eine frei eingebbare Server-Adresse (Admin-only, aber serverseitige Anfrage an beliebige URL). → #114
- > OFFEN: Gemini-Schlüssel steht als Query-Parameter in der URL (kann in Proxy-Logs landen). → #125
