# Dokumentation

> Status: Ist-Verhalten, aus dem Code zurückgewonnen (Stand 0159807). Quellen als `datei:zeile`.

## Zweck

Haushaltsmitglieder ohne IT-Kenntnisse sollen im Störungsfall nachlesen können, was es im Heimnetz
gibt, wozu es dient und was zu tun ist. Das System erzeugt dazu aus dem Inventar eine nach
Themen (nicht nach Technik) sortierte Markdown-Dokumentation in 12 Kapiteln. Bewohner können je
Kapitel eigene, dauerhafte Notizen ergänzen oder eine ganze Seite selbst schreiben; jeder frühere
Stand bleibt abrufbar und wiederherstellbar.

## Rollen und Rechte

| Aktion | ADMIN | MEMBER |
|---|---|---|
| Kapitelliste und Kapitel lesen (inkl. eigener Notizen) | ja | ja |
| Versionen eines Kapitels auflisten und ansehen | ja | ja (nur API; UI zeigt „Verlauf“ nur Admins) |
| Gesamte Doku neu erzeugen | ja | nein |
| Seite komplett von Hand überschreiben | ja | nein |
| Eigene Notizen eines Kapitels bearbeiten | ja | nein |
| Seite zurücksetzen („Neu erzeugen“) | ja | nein |
| Alte Version wiederherstellen | ja | nein |

Alle Routen setzen eine angemeldete Sitzung mit eingerichteter Zwei-Faktor-Anmeldung voraus, siehe
[auth-und-rollen](../auth-und-rollen/spec.md).

## Anforderungen

### Requirement: Feste Kapitelstruktur
Das System MUSS genau 12 Kapitel mit festen Kürzeln, Titeln und fester Reihenfolge erzeugen; Geräte
werden über ihre Kategorie (`kind`) genau einem Kapitel zugeordnet. **[Muss]**

| # | Slug | Titel | Kategorien | Inhalt |
|---|---|---|---|---|
| 0 | `ueberblick` | Überblick: So hängt alles zusammen | – | Einleitung, „Was es im Heimnetz gibt“ (Anzahl je Kategorie), letzter Scan |
| 1 | `internet-und-router` | Internet und Router | router | Einleitung, Gerätetabelle, Details |
| 2 | `netzwerk` | Netzwerk: Switche, WLAN und Verkabelung | network | Einleitung, „Vom Controller erfasste Netze“, Gerätetabelle, Details |
| 3 | `server-und-speicher` | Server und Netzwerkspeicher | server, nas | Einleitung, Gerätetabelle, Details |
| 4 | `container-und-vms` | Container und virtuelle Maschinen | container, vm | Einleitung, Gerätetabelle, Details gruppiert nach Compose-Stack |
| 5 | `computer-und-mobilgeraete` | Computer und Mobilgeräte | pc, mobile | Einleitung, Gerätetabelle, Details |
| 6 | `smart-home` | Smart Home und Automation | smarthome, iot | Einleitung, Gerätetabelle, Details |
| 7 | `klima-heizung-energie` | Wärme, Klima und Energie | heating, climate, energy | Einleitung, Gerätetabelle, Details |
| 8 | `drucker-medien-kameras` | Drucker, Medien und Kameras | printer, media, camera | Einleitung, Gerätetabelle, Details |
| 9 | `sonstige-geraete` | Weitere Geräte | other | Einleitung, Gerätetabelle, Details |
| 10 | `zugaenge-und-konten` | Zugänge und Konten | – | Einleitung, „Hinterlegte Zugänge“ |
| 11 | `notfall` | Wenn etwas nicht funktioniert | – | Notfall-Checkliste |

Jedes Kapitel hat einen festen, handgeschriebenen Einleitungstext (Fallback) und eine Kurzbeschreibung
(`intro`), die als Metadatum gespeichert wird. Kategorielabels (deutsch) und Zustandslabels
(`online`→„erreichbar“, `offline`→„nicht erreichbar“, `unknown`→„unbekannt“) sind fest.

#### Szenario: Kapitelzuordnung
- **WENN** ein Gerät mit `kind = vm` existiert und die Doku erzeugt wird
- **DANN** erscheint es im Kapitel `container-und-vms` und in keinem anderen Kapitel

Quelle: `backend/app/docs.py:21`, `backend/app/docs.py:44`, `backend/app/docs.py:504`, Test: `backend/tests/test_docs_compose_groups.py::test_container_chapter_groups_by_stack`

### Requirement: Faktenteil ohne KI vollständig
Das System MUSS den Faktenteil (Tabellen, Details, Zugänge, Notfall-Checkliste) deterministisch aus
der Datenbank erzeugen; jedes Kapitel MUSS auch ohne KI-Anbieter, ohne API-Schlüssel oder bei
KI-Fehlern vollständig entstehen. **[Muss]**

#### Szenario: Generierung ohne KI
- **WENN** die Doku mit „ohne KI“ erzeugt wird
- **DANN** enthält jedes Kapitel den festen Einleitungstext plus alle Faktenabschnitte

Quelle: `backend/app/docs.py:510`, `backend/app/docs.py:536`, Test: `backend/tests/test_docs_compose_groups.py::test_no_projects_stays_flat`

### Requirement: Optionale KI-Einleitung mit Fallback
Das System SOLL die Kapiteleinleitung von einem LLM schreiben lassen, und zwar nur, wenn (a) die
Generierung mit KI angefordert ist, (b) die Einstellung `scanUseLlm` wahr ist, (c) das Kapitel
Gerätekategorien hat und (d) mindestens ein Gerät enthält. Bei jedem Fehler oder leerer Antwort
MUSS der feste Einleitungstext verwendet werden; ein KI-Fehler darf die Generierung nie abbrechen.
**[Muss]**

Details **[Impl]**: Prompt enthält Kapiteltitel, Kurzbeschreibung und höchstens die ersten 25 Geräte
(Name, Kategorie, Hersteller, Zweck); Systemprompt `DOCS_SYSTEM` verlangt 150–300 Wörter, keine
Überschriften der Ebene 1/2, nichts erfinden. Modellwahl mit Zweck `ANALYSIS` (bei „Automatisch“ das
Flaggschiff-Modell, siehe [einstellungen-und-llm-provider](../einstellungen-und-llm-provider/spec.md)).
Kapitel werden nacheinander erzeugt.

#### Szenario: KI-Anbieter nicht erreichbar
- **WENN** der LLM-Aufruf mit einem Fehler endet
- **DANN** steht der feste Einleitungstext im Kapitel und die übrigen Kapitel werden weiter erzeugt

#### Szenario: Leeres Kapitel
- **WENN** das Kapitel `smart-home` keine Geräte enthält
- **DANN** wird kein LLM aufgerufen und der feste Einleitungstext verwendet

Quelle: `backend/app/docs.py:477`, `backend/app/docs.py:536`, `backend/app/prompts.py:103`

### Requirement: Gerätetabelle je Kapitel
Das System MUSS in jedem Kapitel mit Kategorien den Abschnitt „Geräte auf einen Blick“ mit einer
Tabelle der Spalten Gerät | Adresse im Netz | Art | Zustand | Standort ausgeben; die Adresse ist die IP,
ergänzt um den Kurz-Hostnamen (Teil vor dem ersten Punkt) in Klammern. Ohne Geräte steht dort
„_In dieser Kategorie ist bisher nichts dokumentiert._“ und der Abschnitt „Die Geräte im Einzelnen“
entfällt. **[Muss]**

#### Szenario: Leere Kategorie
- **WENN** es kein Gerät der Kategorie `printer`, `media` oder `camera` gibt
- **DANN** zeigt das Kapitel `drucker-medien-kameras` den Leer-Hinweis statt einer Tabelle

Quelle: `backend/app/docs.py:208`, `backend/app/docs.py:550`

### Requirement: Gerätedetails
Das System MUSS je Gerät einen Abschnitt mit Name als Überschrift, „Wozu“-Beschreibung und den
vorhandenen Fakten ausgeben: IP, MAC, Hersteller, Modell, Standort, Bedeutung (nur wenn ≠ normal),
„Läuft auf“ (Elterngerät), Weboberfläche, Hersteller-Dokumentation, eigene Dokumentation, zuletzt
gesehen (Format `TT.MM.JJJJ HH:MM`); ferner falls vorhanden: direkt vom Gerät ausgelesene Werte
(höchstens 14, mehrzeilige als Codeblock), Docker-Fakten (Image, Compose-Projekt, Port-Weiterleitungen,
höchstens 6 Volumes), Proxmox-Fakten (Node, VM-ID, CPU-Kerne, RAM in MB), Tabelle der Kindgeräte
(„Läuft auf diesem Gerät“, Funktion auf 140 Zeichen gekürzt), höchstens 15 erreichbare Dienste
(Port | Dienst | Bedeutung), PoE-Hinweis bei einem Tag mit „poe“ und die Gerätenotiz. **[Muss]**
Die genauen Obergrenzen sind **[Impl]**.

#### Szenario: Container auf Host
- **WENN** ein Container das Elterngerät „NAS“ hat
- **DANN** zeigt sein Abschnitt „Läuft auf: NAS“ und der Abschnitt von „NAS“ listet ihn unter „Läuft auf diesem Gerät“

Quelle: `backend/app/docs.py:249`, `backend/app/docs.py:291`, `backend/app/docs.py:308`, `backend/app/docs.py:325`, `backend/app/docs.py:341`, `backend/app/docs.py:344`

### Requirement: „Wozu ist das“-Beschreibung
Das System MUSS je Gerät die beste verfügbare Zweckbeschreibung zeigen, in der Reihenfolge:
handgeschriebene Beschreibung → gespeicherter Zweck (außer er beginnt mit „Gerät “) → fester Satz je
Kategorie, ergänzt um den aussagekräftigsten Dienst und ggf. das Container-Image. **[Muss]**

Bevorzugte Dienste für den Zusatz **[Impl]**: erster Dienst mit Port 8123, 32400, 8096, 9100, 631,
445, 5001, 8006, 1883 oder 554, sonst der erste Dienst.

#### Szenario: Keine Beschreibung gepflegt
- **WENN** ein Drucker weder Beschreibung noch Zweck hat, aber Dienst 9100
- **DANN** lautet der Text „Netzwerkdrucker, über den alle Geräte im Haus drucken können. Erreichbar ist unter anderem …“

Quelle: `backend/app/docs.py:159`

### Requirement: Tabellensicheres Escaping
Das System MUSS Freitext in Tabellenzellen so maskieren, dass ein `|` oder Zeilenumbruch in Namen,
Notizen oder Werten die Markdown-Tabelle nicht zerstört (`|` → `\|`, Zeilenumbruch → Leerzeichen).
**[Muss]**

#### Szenario: Pipe im Projektnamen
- **WENN** ein Compose-Projekt `pape|r` heißt
- **DANN** enthält das Kapitel die Überschrift `### Stack: pape\|r`

Quelle: `backend/app/docs.py:202`, Test: `backend/tests/test_docs_compose_groups.py::test_container_chapter_groups_by_stack`

### Requirement: Compose-Gruppen im Container-Kapitel
Das System MUSS im Kapitel `container-und-vms` die Gerätedetails je Compose-Projekt gruppieren:
eine Überschrift „Stack: <Projekt>“ je Projekt (alphabetisch, ohne Groß-/Kleinschreibung), Geräte
darunter eine Ebene tiefer und alphabetisch; Geräte ohne Projekt (auch VMs) folgen unter „Ohne
Compose-Projekt“. Gibt es kein Projekt, MUSS die Ausgabe der flachen Liste entsprechen. **[Muss]**

#### Szenario: Stacks und Rest
- **WENN** Container der Projekte `immich` und `pape|r` sowie ein Container ohne Projekt und eine VM existieren
- **DANN** stehen `#### postgres · immich` unter `### Stack: immich` und `### Ohne Compose-Projekt` nach allen Stacks mit `#### loose` und `#### Gast`

#### Szenario: Keine Projekte
- **WENN** kein Container ein Compose-Projekt hat
- **DANN** erscheinen Geräte als `### <Name>` und das Wort „Stack:“ kommt nicht vor

Quelle: `backend/app/docs.py:226`, `backend/app/docs.py:230`, Test: `backend/tests/test_docs_compose_groups.py::test_container_chapter_groups_by_stack`, `backend/tests/test_docs_compose_groups.py::test_no_projects_stays_flat`

### Requirement: Netzwerkressourcen im Kapitel Netzwerk
Das System MUSS im Kapitel `netzwerk` den Abschnitt „Vom Controller erfasste Netze“ ausgeben, mit nur
aktiven Ressourcen, getrennt in drei Tabellen: „VLANs und Netze“ (Name | Standort | VLAN | Netzwerk |
Notiz), „WLANs“ (Name | Standort | Sicherheit | Notiz), „Internet-Anschlüsse“ (Name | Standort | Typ |
Adresse | Notiz). Fehlende Werte erscheinen als `-`; die lokal gepflegte Notiz der Ressource wird
angezeigt. Ohne Ressourcen: „_Noch keine VLAN-, WLAN- oder WAN-Daten vom Controller erfasst._“
**[Muss]** Siehe [netzwerkressourcen-vlans](../netzwerkressourcen-vlans/spec.md).

#### Szenario: Netz und WLAN mit Notiz
- **WENN** ein aktives Netz „IoT“ (VLAN 20, 192.168.20.0/24) und ein WLAN „Haus-IoT“ (WPA2, Notiz „Nur Geräte“) erfasst sind
- **DANN** enthält das Kapitel `| IoT | Haus | 20 | 192.168.20.0/24 | - |` und `| Haus-IoT | Haus | WPA2 | Nur Geräte |`

Quelle: `backend/app/docs.py:380`, `backend/app/docs.py:547`, Test: `backend/tests/test_docs_network_resources.py::test_network_documentation_includes_active_controller_resources`

### Requirement: Überblick
Das System MUSS im Kapitel `ueberblick` eine Tabelle „Bereich | Anzahl Geräte“ je vorhandener
Kategorie ausgeben (absteigend nach Anzahl, bei Gleichstand nach Kategorie-Kürzel) und darunter
Datum des letzten Scans samt gescannten Netzen (bzw. „automatisch erkannter Bereich“) oder „Es wurde
noch kein Netzwerk-Scan durchgeführt.“ Ohne Geräte: Hinweis, einen Scan zu starten. **[Muss]**

#### Szenario: Noch nichts gescannt
- **WENN** das Inventar leer ist
- **DANN** zeigt der Überblick „_Noch keine Geräte dokumentiert. Starte einen Netzwerk-Scan, um zu beginnen._“

Quelle: `backend/app/docs.py:460`, `backend/app/docs.py:541`

### Requirement: Notfall-Checkliste
Das System MUSS im Kapitel `notfall` eine feste, unter Zeitdruck lesbare Checkliste ausgeben:
Problemgröße eingrenzen (ein Gerät / nur Internet / gar nichts), Router mit Name, IP und
Weboberfläche (erstes Gerät der Kategorie `router`), Anleitung Router-Neustart (30 s stromlos,
2–3 Minuten warten), Liste aller als „kritisch“ markierten Geräte mit IP und Zweck, Verweis auf den
KI-Assistenten. Dieses Kapitel nutzt nie ein LLM. **[Muss]**

#### Szenario: Kein Router bekannt
- **WENN** kein Gerät die Kategorie `router` hat
- **DANN** steht dort „Es ist noch kein Router dokumentiert -- ein Netzwerk-Scan trägt ihn automatisch ein.“

Quelle: `backend/app/docs.py:408`, `backend/app/docs.py:532`

### Requirement: Zugänge ohne Geheimnisse
Das System MUSS im Kapitel `zugaenge-und-konten` hinterlegte Zugänge als Tabelle Zugang | Art |
Benutzername | Gehört zu | Adresse | Passwort hinterlegt (ja/nein) zeigen und darf weder Passwort,
Schlüssel, Passphrase noch Token ausgeben; ein Hinweis erklärt, dass Passwörter bewusst fehlen.
Ohne Zugänge erscheint ein Hinweis, wo man sie anlegt. **[Muss]**

Artlabels **[Impl]**: login→Anmeldung, apikey→API-Schlüssel, wifi→WLAN, contract→Vertrag/Kundenkonto,
other→Sonstiges; andere Kategorien erscheinen roh.

#### Szenario: Zugang mit Passwort
- **WENN** ein Zugang „Router“ mit Benutzer `admin` und gespeichertem Passwort existiert
- **DANN** zeigt die Zeile `admin` und „ja“, aber nicht das Passwort

Quelle: `backend/app/docs.py:355`

### Requirement: Keine Secrets in der Doku
Das System DARF in keinem Kapitel entschlüsselte Zugangsdaten, API-Schlüssel oder sonstige
verschlüsselt gespeicherte Werte ausgeben; die Doku entsteht nur aus Inventar-, Zugangs-Metadaten,
Netzwerkressourcen- und Scan-Daten. **[Muss]**

#### Szenario: Gerät mit SSH-Schlüssel
- **WENN** für ein Gerät ein SSH-Schlüssel hinterlegt ist
- **DANN** erscheint in keinem Kapitel Schlüsselmaterial

Quelle: `backend/app/docs.py:1`, `backend/app/docs.py:355`

### Requirement: Eigene Notizen getrennt vom erzeugten Text
Das System MUSS je Kapitel ein eigenes Notizfeld führen, das keine automatische Generierung je
liest oder verändert. Das Speichern der Notizen DARF den Modus der Seite (automatisch/manuell) nicht
ändern, sodass Gerätetabellen weiter aktualisiert werden. **[Muss]**

#### Szenario: Notiz übersteht Neuerzeugung
- **WENN** ein Admin die Notiz „Sicherung F3 im Keller“ speichert und danach ein Scan die Doku neu erzeugt
- **DANN** ist die Notiz unverändert und der erzeugte Teil aktualisiert

#### Szenario: Unbekanntes Kapitel
- **WENN** Notizen für einen nicht existierenden Slug gespeichert werden
- **DANN** antwortet das System mit 404 „Kapitel nicht gefunden.“

Quelle: `backend/app/db.py:1626`, `backend/app/main.py:1293`, `backend/app/db.py:1640`

### Requirement: Ganze Seite manuell überschreiben
Das System MUSS erlauben, den erzeugten Text einer Seite komplett zu ersetzen; die Seite gilt danach
als „von Hand bearbeitet“ und folgende Generierungen DÜRFEN ihren Text und ihre Kurzbeschreibung
nicht ändern (nur Titel, Thema und Reihenfolge werden nachgezogen). **[Muss]**

#### Szenario: Manuelle Seite bleibt
- **WENN** ein Admin `netzwerk` von Hand speichert und danach „Alles neu erzeugen“ auslöst
- **DANN** bleibt der von Hand geschriebene Text stehen und die Seite ist weiter als manuell markiert

#### Szenario: Unbekanntes Kapitel
- **WENN** ein Text für einen nicht existierenden Slug gespeichert wird
- **DANN** antwortet das System mit 404

Quelle: `backend/app/db.py:1667`, `backend/app/db.py:1660`, `backend/app/main.py:1285`

### Requirement: Seite zurücksetzen
Das System MUSS eine manuell überschriebene Seite wieder in den automatischen Modus versetzen und
sofort neu erzeugen können. Die eigenen Notizen (`manualMd`) bleiben dabei unverändert. Der
überschriebene Text wird nur dann als Version („automatisch neu erzeugt“) gesichert, wenn der neu
erzeugte Text sich von ihm unterscheidet; ist er gleich, entsteht kein Snapshot. **[Muss]**

Heute **[Impl]**: Reset setzt den Modus und erzeugt danach **alle** Kapitel neu (KI gemäß `scanUseLlm`),
Antwort ist die zurückgesetzte Seite.

#### Szenario: Reset
- **WENN** ein Admin bei der manuell bearbeiteten Seite `notfall` „Neu erzeugen“ wählt
- **DANN** enthält sie wieder die erzeugte Checkliste, ihre eigenen Notizen sind unverändert und der
  Verlauf hat einen Eintrag „automatisch neu erzeugt“ mit dem alten Text

#### Szenario: Reset ohne Textänderung
- **WENN** der manuell gesetzte Text zufällig dem neu erzeugten entspricht
- **DANN** wechselt die Seite in den automatischen Modus, ohne dass eine neue Version entsteht

Quelle: `backend/app/main.py:1302`, `backend/app/db.py:1675`, `backend/app/db.py:1645`, `backend/app/db.py:1646`,
`backend/app/db.py:1656` (Update ohne `manualMd`)

### Requirement: Versionierung vor jeder Änderung
Das System MUSS vor jeder Änderung eines Kapitels den bisherigen Stand (Titel, Text, Notizen, Modus)
mit Anlass und Zeitstempel sichern. Anlässe: „automatisch neu erzeugt“ (nur wenn der erzeugte Text
sich tatsächlich ändert und die Seite automatisch ist), „vor manueller Bearbeitung“, „vor Änderung der
eigenen Notizen“, „vor Wiederherstellung“. Ein Stand mit leerem Text und leeren Notizen wird nicht
gesichert. **[Muss]** Aufbewahrung: die neuesten 50 Versionen je Kapitel, ältere werden gelöscht
**[Impl]**.

#### Szenario: Unveränderte Neuerzeugung
- **WENN** die Doku zweimal hintereinander ohne Inventaränderung erzeugt wird
- **DANN** entsteht beim zweiten Lauf keine neue Version

Quelle: `backend/app/db.py:1572`, `backend/app/db.py:1575`, `backend/app/db.py:1645`

### Requirement: Versionen auflisten und ansehen
Das System MUSS die Versionen eines Kapitels neueste zuerst auflisten (ID, Slug, Titel, Modus, Anlass,
Zeitpunkt, Textgröße in Zeichen, ohne Inhalt) und eine einzelne Version vollständig liefern. Eine
Version, die nicht zu dem angefragten Slug gehört, MUSS mit 404 „Version nicht gefunden.“ abgelehnt
werden. **[Muss]**

#### Szenario: Fremde Version
- **WENN** eine Version von `netzwerk` unter `/api/docs/notfall/versions/{id}` angefragt wird
- **DANN** antwortet das System mit 404

Quelle: `backend/app/db.py:1596`, `backend/app/main.py:1318`, `backend/app/main.py:1323`

### Requirement: Version wiederherstellen
Das System MUSS eine alte Version wiederherstellen können: zuerst wird der aktuelle Stand gesichert
(Anlass „vor Wiederherstellung“), dann werden Text **und** Notizen der Version übernommen und die Seite
als manuell markiert, damit die nächste Generierung den gewählten Stand nicht überschreibt. **[Muss]**

#### Szenario: Wiederherstellen ist rückgängig machbar
- **WENN** ein Admin eine alte Version wiederherstellt
- **DANN** ist der vorherige Stand als neueste Version im Verlauf und die Seite trägt die Markierung „von Hand bearbeitet“

Quelle: `backend/app/db.py:1610`, `backend/app/main.py:1331`

### Requirement: Auslöser der Generierung
Das System MUSS die Doku (a) am Ende jedes Netzwerk-Scans und (b) auf Admin-Anforderung neu erzeugen.
Bei (a) DARF ein Fehler der Doku-Generierung den Scan nicht scheitern lassen, sondern wird als
Warnung im Scan-Ergebnis vermerkt. Bei (b) bestimmt der Parameter `useLlm` die KI-Nutzung, Default
ist der Wert von `scanUseLlm`. Die Antwort nennt die geschriebenen Slugs in Kapitelreihenfolge.
**[Muss]**

#### Szenario: Scan mit Doku-Fehler
- **WENN** die Doku-Generierung während eines Scans eine Ausnahme wirft
- **DANN** endet der Scan mit Warnung „Dokumentation konnte nicht vollständig erzeugt werden: …“, das Inventar bleibt gespeichert

Quelle: `backend/app/pipeline.py:532`, `backend/app/main.py:1310`, `backend/app/docs.py:510`

### Requirement: Kapitelliste
Das System MUSS die Kapitel sortiert nach Reihenfolge, dann Titel (ohne Groß-/Kleinschreibung)
liefern, ohne den Haupttext (Metadaten und Notizen sind enthalten). Ein unbekannter Slug beim Lesen
eines Kapitels ergibt 404 „Kapitel nicht gefunden.“ **[Muss]**

#### Szenario: Vor dem ersten Scan
- **WENN** noch nie generiert wurde
- **DANN** ist die Liste leer (UI: „Noch keine Kapitel. Führe einen Netzwerk-Scan durch.“)

Quelle: `backend/app/main.py:1272`, `backend/app/db.py:1562`, `backend/app/main.py:1277`

## Daten

Siehe [data-model](../../contracts/data-model.md).

- Schreibt `docPages` (`slug`, `topic`, `title`, `bodyMd`, `manualMd`, `intro`, `generated` 1=automatisch/0=von Hand, `sortOrder`, `updatedAt`).
- Schreibt `docPageVersions` (`slug`, `title`, `bodyMd`, `manualMd`, `generated`, `reason`, `createdAt`).
- Liest `systems` (alle Felder inkl. `extra.docker`, `extra.proxmox`, `extra.probe`, `services`, `tags`, `parentId`, `notes`), `accounts` (nur Metadaten und ob `secretEnc` gesetzt ist), `networkResources` (aktive), `scans` (letzter), `settings` (`scanUseLlm`, `llmProvider` und Provider-Felder, `scanSubnets`, `scanControllerNetworkIds`).

## Schnittstellen

| Methode | Pfad | Rolle | Zweck |
|---|---|---|---|
| GET | /api/docs | MEMBER | Kapitelliste ohne `bodyMd` |
| POST | /api/docs/generate | ADMIN | Alle Kapitel neu erzeugen; Body `{useLlm?: bool}` → `{generated: [slug]}` |
| GET | /api/docs/{slug} | MEMBER | Ein Kapitel; 404 wenn unbekannt |
| PUT | /api/docs/{slug} | ADMIN | Ganze Seite überschreiben `{bodyMd}` → Seite manuell |
| PUT | /api/docs/{slug}/manual | ADMIN | Eigene Notizen setzen `{manualMd}` |
| POST | /api/docs/{slug}/reset | ADMIN | Zurück in Automatik + Neuerzeugung |
| GET | /api/docs/{slug}/versions | MEMBER | Versionsliste (Metadaten, `size`) |
| GET | /api/docs/{slug}/versions/{version_id} | MEMBER | Eine Version vollständig |
| POST | /api/docs/{slug}/versions/{version_id}/restore | ADMIN | Version wiederherstellen |

„MEMBER“ heißt: jede angemeldete Rolle. Der Assistent liest Kapitel über die Tools
`list_documentation`/`get_documentation` (siehe [assistent-chat-und-mcp](../assistent-chat-und-mcp/spec.md),
[llm-tools](../../contracts/llm-tools.md)); der Scan-Auslöser ist in
[discovery-und-scan](../discovery-und-scan/spec.md) beschrieben.

UI-Seite(n): `frontend/src/pages/DocsPage.tsx` (Routen `/dokumentation`, `/dokumentation/:slug`).

## Nicht-Ziele und Grenzen

- Keine Volltextsuche, kein Export (PDF o. ä.), kein Diff zwischen Versionen.
- Keine freien Kapitel: Struktur ist fest; Bewohner ergänzen nur Notizen oder überschreiben Seiten.
- Keine Bearbeitung durch MEMBER; kein Bearbeiten durch den Assistenten.
- Keine Mehrsprachigkeit (Doku ist deutsch).

## Ist-Implementierung (nur Referenz, [Impl])

- Markdown wird serverseitig als String zusammengesetzt; Rendering im Browser (`components/Markdown`).
- `intro` speichert die feste Kurzbeschreibung (`intro_hint`), nicht den KI-Text; der KI-Text steht am Anfang von `bodyMd`.
- `topic` wird mit dem Kapiteltitel befüllt.
- Zeitstempel mit Sekundenauflösung (UTC, `…Z`); Gleichstand in der Versionsliste über Einfügereihenfolge aufgelöst.
- Die Netzübersicht im Überblick nutzt die effektiven Scan-Netze inkl. Fallback auf Host-Interfaces (startet ggf. einen Subprozess).

## OFFEN

- > OFFEN: Reset eines Kapitels erzeugt alle 12 Kapitel neu (Laufzeit/KI-Kosten, neue Versionen auf anderen Seiten). Absicht oder sollte nur das eine Kapitel neu entstehen?
- > OFFEN: `POST /api/docs/{slug}/reset` mit unbekanntem Slug liefert 200 mit `page: null` statt 404.
- > OFFEN: `GET /api/docs/{slug}/versions` mit unbekanntem Slug liefert leere Liste statt 404.
- > OFFEN: `PUT /api/docs/{slug}` ohne Feld `bodyMd` speichert leeren Text (keine Validierung).
- > OFFEN: Wiederherstellen überschreibt auch die eigenen Notizen mit dem alten Stand — gewollt, obwohl Notizen „nie angefasst“ werden sollen (gilt laut Code nur für die Automatik)?
- > OFFEN: UI-Bestätigung beim Reset sagt „Änderungen gehen verloren“, tatsächlich bleiben sie im Verlauf.
- > OFFEN: Kapitel, deren Slug nicht mehr definiert ist, werden nie gelöscht (`db.delete_doc_page` ungenutzt).
- > OFFEN: Benutzernamen und URLs von Zugängen sind über die Doku für MEMBER sichtbar, obwohl die Zugangs-API admin-only ist. Ebenso Gerätenotizen und ausgelesene Gerätewerte — falls dort Geheimnisse stehen, landen sie in der Doku.
- > OFFEN: Ohne Schlüssel/erreichbaren Anbieter wird der KI-Aufruf trotzdem je Kapitel versucht (Timeout 120 s, sequentiell) — kann die Generierung stark verzögern.
- > OFFEN: Keine Sperre gegen gleichzeitige Generierungen (Scan + manueller Lauf) — mögliche doppelte Versionen/Race.
- > OFFEN: Bei mehreren Routern nimmt die Notfall-Seite den ersten aus der Inventarreihenfolge.
- > OFFEN: `useLlm: true` im Request wird ignoriert, wenn `scanUseLlm` aus ist (die Einleitung prüft die Einstellung erneut).
