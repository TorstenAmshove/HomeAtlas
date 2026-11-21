# Klassifikation (LLM)

> Status: Ist-Verhalten, aus dem Code zurückgewonnen (Stand 0159807). Quellen als `datei:zeile`.

## Zweck

Die regelbasierte Erkennung lässt Geräte übrig, die sie nicht oder nur als Platzhalter einordnen
kann („Gerät mit Netzwerkdiensten“). Während eines Scans lässt das System ein Sprachmodell aus den
gesammelten Belegen Art, Name, Hersteller, Modell, Zweck, eine Laienbeschreibung, Wichtigkeit und
einen Link zur Hersteller-Doku vorschlagen. Das Ergebnis ist rein ergänzend: unsichere Antworten,
tote Links und Änderungen an quellgestützten oder manuell gepflegten Namen werden verworfen. Ohne
konfiguriertes Modell funktioniert der Scan weiter, nur ohne diese Ergänzungen.

## Rollen und Rechte

| Aktion | ADMIN | MEMBER |
|---|---|---|
| Einordnung auslösen (indirekt per Scan, nur neue Geräte) | ja | nein |
| Einzelnes Gerät neu einordnen (`POST /api/systems/{system_id}/classify`) | ja | nein (403) |
| Einordnung ein-/ausschalten (`scanUseLlm`) | ja | nein |
| Ergebnisse im Inventar lesen | ja | ja, siehe [inventar](../inventar/spec.md) |

## Anforderungen

### Requirement: Abschaltbar und optional
Das System MUSS die KI-Einordnung nur ausführen, wenn `scanUseLlm` (Default an) gesetzt ist **und**
für den gewählten Anbieter ein Zugang eingerichtet ist (Cloud-Anbieter: API-Schlüssel; Ollama:
immer), und ohne sie vollständig nutzbare, regelbasierte Ergebnisse liefern. Fehlt der Zugang,
werden keine Gerätedaten gesendet; der Scan meldet „KI-Einordnung übersprungen …“ als Hinweis.
**[Muss]**

#### Szenario: Frische Installation ohne Schlüssel
- **WENN** der Standard-Anbieter DEEPSEEK ohne Schlüssel eingestellt ist
- **DANN** findet kein LLM-Aufruf statt (Test: `backend/tests/test_llm_defaults_and_accounts.py::test_classify_without_key_sends_nothing`)

#### Szenario: Abgeschaltet
- **WENN** `scanUseLlm=false`
- **DANN** findet kein LLM-Aufruf statt, Funde behalten die Regel-Einordnung

Quelle: `backend/app/pipeline.py:469`, `backend/app/discovery.py:653`

### Requirement: Kandidatenauswahl
Das System MUSS nur Funde einordnen lassen, die (a) kein Docker-Container sind, (b) mindestens einen
Beleg haben (offene Ports, MAC-Hersteller, Hostname, mDNS, SSDP oder HTTP-Banner) und (c) entweder
Art `other`/leer haben, nur eine Platzhalter-Einordnung (`extra.guessConfident=false`) tragen, oder
noch keinen Zweck oder keinen Doku-Link besitzen. Der Scan ordnet zusätzlich nur Funde ein, die das
Inventar noch nicht kennt (kein Treffer über Schlüssel, Legacy-Schlüssel, Alias, MAC, Proxmox,
IP+Hostname oder Controller-IP; alle Quellen). Bekannte Geräte werden nie erneut gefragt, auch nicht
nach verworfener Antwort; das Protokoll nennt neue, eingeordnete und übersprungene Funde. **[Muss]**

#### Szenario: Zweiter Scan ohne neue Geräte
- **WENN** alle Funde bereits im Inventar stehen
- **DANN** findet kein LLM-Aufruf statt (Test: `backend/tests/test_pipeline_classify_new_only.py::test_second_scan_sends_nothing`)

#### Szenario: Stiller Host
- **WENN** ein Fund weder Ports noch Hersteller, Hostname, mDNS, SSDP oder Banner hat
- **DANN** wird er nicht an das Modell geschickt

#### Szenario: Container und Host mit gleicher IP
- **WENN** ein Host (`kind=other`, Port 22) und zwei Container dieselbe IP haben
- **DANN** ist nur der Host Kandidat

Quelle: `backend/app/classify.py:50`, Test: `backend/tests/test_classify_source_names.py::test_containers_with_same_ip_untouched`

### Requirement: KI-Ergebnis bleibt bei Folge-Scans erhalten
Das System MUSS bei unbestätigten Zeilen mit `extra.aiConfidence` Art, Name, Hersteller, Modell,
Zweck, Beschreibung, Doku-Link und Wichtigkeit nicht mit Regelwerten späterer Scans überschreiben;
von Quellen (Docker, Proxmox, UniFi, Omada) oder vom Gerät selbst gemeldete Namen/Arten wirken weiter.
**[Muss]**

Quelle: `backend/app/db/systems.py` (`upsert_discovered_system`), Test: `backend/tests/test_discovery_lookup.py::test_ai_result_survives_next_scan`

### Requirement: Manuelle Einordnung am Gerät
Das System MUSS Admins `POST /api/systems/{system_id}/classify` bieten (MEMBER: 403), unabhängig von
`scanUseLlm`. Es gelten die Scan-Regeln (niedrige Konfidenz verworfen, Quell- und selbstgemeldete
Namen bleiben); Kandidatenkriterien zu Art/Zweck entfallen (`force`), Container, Geräte ohne IP und
ohne Beleg werden abgelehnt (400), ebenso fehlender KI-Zugang (400). Providerfehler → 502, Gerät
unverändert. Bestätigte Zeilen erhalten nur leere Felder (Hersteller, Modell, Zweck, Beschreibung,
Link), nie Art, Name oder Wichtigkeit; `confirmed` bleibt. Antwort: `{system, changed, warnings}`.
**[Muss]** Die Funktion steht nicht in `tools.py`.

Quelle: `backend/app/routes/systems.py` (`classify_system`), `backend/app/classify.py` (`apply_to_system`), Test: `backend/tests/test_systems_classify_route.py`

### Requirement: Container nie einordnen
Das System MUSS Docker-Container (Fund mit `extra.docker`) vollständig von der Einordnung ausnehmen –
weder Aufruf noch Anwendung –, weil sie die Host-IP teilen und Antworten per IP zugeordnet werden. **[Muss]**

#### Szenario: Nur Container im Scan
- **WENN** alle Funde Container sind
- **DANN** kein LLM-Aufruf, Ergebnis leer, keine Warnung

Quelle: `backend/app/classify.py:39`, `backend/app/classify.py:61`, `backend/app/classify.py:197`,
Test: `backend/tests/test_classify_source_names.py::test_classify_run_skips_containers`

### Requirement: Übermittelte Belege
Das System MUSS je Kandidat nur technische Belege übermitteln: IP, Hostname, MAC-Hersteller,
bisherige Art und bisheriger Zweck, offene Ports als „<port> (<dienst>)“ (max. 20), mDNS-Dienste
(Typ, Name; max. 8), UPnP-Beschreibungen (max. 4), ersten UPnP-Server-Header, Webseitentitel,
Webserver-Header. Zugangsdaten, Notizen oder Ergebnisse authentifizierter Abfragen DÜRFEN NICHT
übermittelt werden. **[Muss]** Feldnamen (`macVendor`, `bisherigeEinordnung`, …) sind **[Impl]**.

#### Szenario: Ports gekürzt
- **WENN** ein Gerät 30 offene Ports hat
- **DANN** enthält die Anfrage die ersten 20 (nach Port sortiert)

Quelle: `backend/app/classify.py:77`

### Requirement: Stapelverarbeitung
Das System MUSS Kandidaten in Stapeln zu höchstens 10 Geräten anfragen; ein fehlgeschlagener Stapel
darf die anderen nicht beeinflussen. **[Muss]** Stapelgröße 10 und die Nutzernachricht „Ordne diese
N Geräte ein:“ + JSON sind **[Impl]**.

#### Szenario: 25 Kandidaten
- **WENN** 25 Geräte einzuordnen sind
- **DANN** 3 Anfragen (10, 10, 5); Protokoll „KI-Einordnung: N Geräte geprüft“ je erfolgreichem Stapel

Quelle: `backend/app/classify.py:27`, `backend/app/classify.py:124`

### Requirement: Modellanweisung
Das System MUSS das Modell anweisen: Selbstauskunft (UPnP, mDNS) vor Port-Vermutung; nicht raten,
sondern `other` mit niedriger Konfidenz; Zweck immer ausfüllen; Beschreibung 1–2 Sätze für Laien
über das *Wozu*; `docUrl` nur, wenn sicher bekannt, Support-Startseite bevorzugen; keine Räume,
Standorte, Besitzer erfinden; Antwort ausschließlich als JSON-Array mit je
`ip, kind, name, vendor, model, purpose, description, docUrl, importance, confidence`;
`importance=critical` nur für Geräte, deren Ausfall im Haus spürbar ist, `low` für Gäste-/Wegwerfgeräte.
Sprache Deutsch. **[Muss]** Exakter Wortlaut **[Impl]**.

#### Szenario: Unklare Belege
- **WENN** nur ein unbekannter Port offen ist
- **DANN** soll das Modell `kind="other"`, `confidence="low"` liefern (und wird verworfen)

Quelle: `backend/app/prompts.py:64`, `backend/app/prompts.py:87`, `backend/app/prompts.py:96`, `backend/app/prompts.py:99`

### Requirement: Antwort robust parsen
Das System MUSS eine Antwort auch dann auswerten, wenn das JSON-Array in Markdown-Zäune oder
Begleittext eingebettet ist (ausgeschnitten vom ersten `[` bis zum letzten `]`). Kein Array ⇒
Stapel-Fehler. **[Muss]**

#### Szenario: Zaun
- **WENN** die Antwort ```` ```json [ … ] ``` ```` lautet
- **DANN** wird das Array ausgewertet

Quelle: `backend/app/classify.py:103`

### Requirement: Antworten filtern und normalisieren
Das System MUSS Einträge verwerfen, die keine Objekte sind, deren `ip` nicht im Stapel vorkam oder
deren `confidence` `low` ist. Unbekannte `kind` werden zu `other`, unbekannte `importance` zu
`normal`; fehlende Konfidenz gilt als `medium`. Längen: Name 80, Hersteller 80, Modell 100, Zweck
200, Beschreibung 800, docUrl 300 Zeichen. **[Muss]**

#### Szenario: Halluzinierte IP
- **WENN** das Modell einen Eintrag für eine IP liefert, die nicht im Stapel war
- **DANN** wird er ignoriert

Quelle: `backend/app/classify.py:29`, `backend/app/classify.py:140`, `backend/app/classify.py:146`

### Requirement: Fehler nie fatal
Ein Provider-Fehler (auch Netzwerkfehler wie Timeout oder nicht erreichbares Ollama, die der
LLM-Client als `ProviderError` meldet), eine unparsebare Antwort oder ungültiges JSON MUSS nur den betroffenen Stapel
überspringen und die Warnung „KI-Einordnung für N Geräte fehlgeschlagen: …“ erzeugen; der Scan endet
mit den Regel-Ergebnissen. **[Muss]**

#### Szenario: Kein Modell gewählt
- **WENN** der Provider „Kein Modell ausgewählt“ meldet
- **DANN** Warnung je Stapel, Scan `completed`

Quelle: `backend/app/classify.py:134`, `backend/app/pipeline.py:471`

### Requirement: Additiv anwenden
Beim Übernehmen MUSS gelten:
- leere Werte des Modells überschreiben nie einen vorhandenen Wert;
- bei Funden mit Namensquelle (Quellen-Token oder `extra`-Schlüssel `docker`, `proxmox`, `unifi`,
  `omada`) bleiben `name` und `kind` unverändert, andere Felder (Zweck, Beschreibung, …) werden ergänzt;
- bei Funden mit selbst gemeldetem Namen (`extra.nameSource` = `upnp`, `mdns` oder `shelly`, von
  Discovery gesetzt) bleibt nur der `name` unverändert; `kind` darf die KI weiter setzen, da solche
  Namen wenig über den Gerätetyp sagen. Ist zusätzlich eine Namensquelle (oben) im Spiel, gilt deren
  Schutz für Name und Art;
- ein bereits vorhandener (kuratierter) Doku-Link gewinnt immer gegen einen KI-Link;
- `discoverySource` erhält `+ki`, `extra.aiConfidence` die Konfidenz.
Übernommen werden `kind, name, vendor, model, purpose, descriptionMd, importance, docUrl`. Manuell
bestätigte Geräte schützt zusätzlich das Inventar-Zusammenführen (nur leere Felder werden gefüllt,
siehe [inventar](../inventar/spec.md)). **[Muss]**

#### Szenario: UniFi-Gerät
- **WENN** ein Fund aus UniFi „Mein Gerät“/`network` heißt und das Modell `vm`/„Proxmox VM …“/Zweck liefert
- **DANN** bleiben Name und Art, der Zweck wird übernommen

#### Szenario: UPnP-Name
- **WENN** `extra.nameSource="upnp"` und die KI einen anderen Namen und `kind=vm` liefert
- **DANN** bleibt der Name, `kind` und Zweck kommen von der KI

#### Szenario: mDNS-Name
- **WENN** `extra.nameSource="mdns"` und die KI einen anderen Namen liefert
- **DANN** bleibt der Name; `kind` darf ergänzt werden

#### Szenario: Quellen-Token
- **WENN** `discoverySource="docker+ki"` ⇒ Namensquelle; `"arp+ki"` oder leer ⇒ keine

Quelle: `backend/app/classify.py:36`, `backend/app/classify.py:43`, `backend/app/classify.py:194`,
`backend/app/classify.py:206`, `backend/app/db.py:1224`,
Tests: `backend/tests/test_classify_source_names.py::test_source_names_keep_name_and_kind_but_get_purpose`,
`backend/tests/test_classify_source_names.py::test_upnp_name_kept_kind_updated`,
`backend/tests/test_classify_source_names.py::test_mdns_name_kept_kind_updated`,
`::test_discovery_source_variants`, `::test_containers_with_same_ip_untouched`

### Requirement: Kuratierte Hersteller-Links
Das System MUSS ohne Netzwerkzugriff einen kuratierten Doku-Link vergeben, wenn Hersteller, Modell,
Name, Webseitentitel oder Server-Header (kleingeschrieben, Substring) zu einer gepflegten Liste
passen; erste Übereinstimmung gewinnt, spezifische Einträge stehen vor allgemeinen (z. B.
„fritz!repeater“ vor „avm“). **[Muss]** Die Liste (41 Einträge, deutsche
Support-Seiten) ist **[Impl]**.

#### Szenario: FRITZ!Repeater
- **WENN** Name „FRITZ!Repeater 3000“, Hersteller „AVM“
- **DANN** Link `https://avm.de/service/` (nicht die FRITZ!Box-Handbücher)

Quelle: `backend/app/vendor_docs.py:21`, `backend/app/vendor_docs.py:66`, `backend/app/discovery.py:926`

### Requirement: KI-Links prüfen
Jeder vom Modell vorgeschlagene Doku-Link MUSS vor dem Speichern abgerufen werden (GET, Redirects
folgen, Timeout 6 s, Connect 4 s, User-Agent `HomeAtlas/1.0 (link check)`); nur `http(s)`-URLs mit
Status < 400 bleiben, alle anderen werden geleert. Bei Verwürfen MUSS die Warnung „X von Y
vorgeschlagenen Hersteller-Links waren nicht erreichbar und wurden verworfen.“ entstehen.
Kuratierte Links werden nicht geprüft. **[Muss]**

#### Szenario: 404
- **WENN** das Modell `https://example.com/handbuch.pdf` vorschlägt und der Server 404 liefert
- **DANN** `docUrl=""` und Warnung „1 von 1 …“

Quelle: `backend/app/classify.py:168`, `backend/app/vendor_docs.py:77`, `backend/app/vendor_docs.py:92`

### Requirement: Wirkung der KI-Wichtigkeit
Eine übernommene Wichtigkeit `critical` MUSS (über den Scan) zur Dauerüberwachung des Geräts führen,
siehe [discovery-und-scan](../discovery-und-scan/spec.md) und [monitoring](../monitoring/spec.md). **[Muss]**

#### Szenario: Heizungssteuerung kritisch
- **WENN** das Modell `importance="critical"` für ein unbestätigtes Gerät mit IP liefert
- **DANN** ist es nach dem Scan `monitored=1`

Quelle: `backend/app/pipeline.py:512`

## Daten

Siehe [data-model](../../contracts/data-model.md).

- Liest (Funde im Speicher, vor dem Inventar): `ip, hostname, vendor, kind, purpose, services,
  docUrl, openPorts, discoverySource, extra.{mdns, ssdp, httpBanner, guessConfident, docker,
  proxmox, unifi, omada}`.
- Schreibt (in den Fund, danach per Inventar-Zusammenführen in **systems**): `kind, name, vendor,
  model, purpose, descriptionMd, importance, docUrl, discoverySource (+ki), extra.aiConfidence`.
- Settings gelesen: `scanUseLlm`, `llmProvider` sowie über den LLM-Client die Schlüssel/Modelle/
  Base-URLs des Providers (Modellzweck „CHAT“), siehe
  [einstellungen-und-llm-provider](../einstellungen-und-llm-provider/spec.md). Schreibt keine Settings.

## Schnittstellen

| Methode | Pfad | Rolle | Zweck |
|---|---|---|---|
| — | — | — | Keine eigene Route; läuft innerhalb von `POST /api/scans`, siehe [discovery-und-scan](../discovery-und-scan/spec.md) |

UI-Seite(n): keine eigene; Ergebnisse in `frontend/src/pages/SystemDetailPage.tsx` / Inventar,
Warnungen in `frontend/src/pages/ScanPage.tsx` (Route `/scan`).

## Nicht-Ziele und Grenzen

- Keine Einordnung außerhalb eines Scans, kein manueller „neu einordnen“-Knopf.
- Kein Schreiben an Geräten; das Modell erhält keine Werkzeuge.
- Kein eigener Modellzweck für Klassifikation; es wird das Chat-Modell des aktiven Providers genutzt.
- Die Doku-Texte (`DOCS_SYSTEM`) und der Chat-Prompt gehören zu
  [dokumentation](../dokumentation/spec.md) bzw. [assistent-chat-und-mcp](../assistent-chat-und-mcp/spec.md).

## Ist-Implementierung (nur Referenz, [Impl])

- Aufruf über den eigenen provider-neutralen Client `llm_providers.chat(provider, settings,
  CLASSIFY_SYSTEM, [user-msg], purpose="CHAT")`, Provider-Timeout 120 s (Connect 10 s).
- Ergebnis als Dict `ip → Klassifikation`; Anwendung im Scan per IP auf *alle* Funde mit dieser IP.
- Link-Prüfungen laufen parallel (`asyncio.gather`).

## OFFEN

- > OFFEN: Weil `importance` nach Normalisierung nie leer ist, überschreibt die KI-Wichtigkeit immer
  die regelbasierte – auch beim Gateway (`critical`), sobald es Kandidat ist (z. B. kein kuratierter
  Doku-Link bei Nicht-AVM-Routern). Ebenso überschreibt eine ungültige KI-`kind` (→ `other`) eine
  korrekte Regel-Art wie `router`.
- > OFFEN: Ein sicher erkanntes Gerät wird schon Kandidat, wenn nur der Doku-Link fehlt.
- > OFFEN: Nur exakt `"low"` wird verworfen; „LOW“, „niedrig“ o. Ä. gelten als akzeptiert.
- > OFFEN: Die Link-Prüfung führt GET auf beliebige vom Modell gelieferte URLs vom Server aus,
  auch auf LAN-Adressen (SSRF-artig); kein Ausschluss privater Ziele.
- > OFFEN: Gleiche IP in mehreren Funden (Netzwerk-Fund plus UniFi/Omada/Proxmox/AdGuard) –
  mehrere Belegsätze pro IP im selben Stapel möglich, der letzte gewinnt, und das Ergebnis wird auf
  alle Funde dieser IP angewandt.
- > OFFEN: Der Prompt verlangt dieselbe Reihenfolge wie die Eingabe; der Code ordnet ausschließlich
  per IP zu (Reihenfolge irrelevant) – unschädlich, aber Anforderung an Modell überflüssig.
