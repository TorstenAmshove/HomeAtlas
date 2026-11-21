# Dashboard

> Status: Ist-Verhalten, aus dem Code zurückgewonnen (Stand 0159807). Quellen als `datei:zeile`.

## Zweck

Die Startseite nach dem Login gibt jedem im Haushalt auf einen Blick den Zustand des Heimnetzes:
wie viele Geräte dokumentiert und erreichbar sind, ob die wichtigsten Geräte gerade laufen, was es
im Netz gibt und wann zuletzt gescannt wurde. Sie ist der Einstieg bei „Internet geht nicht" –
mit einem Knopf für den Internet-Schnelltest – und weist den Admin auf fehlende Einrichtung hin.

## Rollen und Rechte

| Aktion | ADMIN | MEMBER |
|---|---|---|
| Dashboard-Daten abrufen | ja | ja |
| Internet-Schnelltest starten | ja | ja |
| Knopf „Netzwerk scannen" sehen | ja | nein |
| Hinweise „KI-Assistent nicht eingerichtet" / „Überwachung aus" sehen | ja | nein |

Rollenprüfung: `backend/app/main.py:1608` (`Depends(current_user)`); UI-Gating
`frontend/src/pages/DashboardPage.tsx:77`, `:87`, `:159`.

## Anforderungen

### Requirement: Kennzahlen
Das System MUSS folgende Zähler über das gesamte Inventar liefern: `total` (alle Geräte), `online`
(`status = online`), `critical` (`importance = critical`) und
`accounts` (alle gespeicherten Zugänge); `counts` hat genau diese vier Schlüssel. Die Oberfläche zeigt vier Kacheln: Geräte insgesamt, gerade
erreichbar (grün), kritisch fürs Haus (gelb, wenn > 0), hinterlegte Zugänge. **[Muss]**

#### Szenario: Zählung
- **WENN** 5 Geräte existieren, davon 3 `online`, 1 `offline`, 1 `unknown`, 2 `critical`
- **DANN** ist `counts = {total: 5, online: 3, critical: 2, accounts: …}`

#### Szenario: Leeres Inventar
- **WENN** noch kein Gerät existiert
- **DANN** zeigt die Kopfzeile „Noch nichts dokumentiert. Ein Netzwerk-Scan findet die Geräte im Haus automatisch."
- **SONST** „<total> Geräte dokumentiert, davon <online> gerade erreichbar."

Quelle: `backend/app/main.py:1616`, `frontend/src/pages/DashboardPage.tsx:68`, `:97`

### Requirement: Geräte nach Art
Das System MUSS je vorkommender Art (`kind`) die Anzahl Geräte liefern (`byKind`, nur Arten mit
mindestens einem Gerät) sowie die deutschen Anzeigenamen (`kindLabels`). Die Oberfläche listet sie
absteigend nach Anzahl („Was es im Netz gibt"); jeder Eintrag verlinkt auf die gefilterte
Geräteliste `/geraete?kind=<art>`. **[Muss]**

#### Szenario: Drill-down
- **WENN** der Nutzer auf „Router (2)" klickt
- **DANN** öffnet sich die Geräteliste, gefiltert auf Art `router`

Quelle: `backend/app/main.py:1624`, `backend/app/docs.py:21`, `frontend/src/pages/DashboardPage.tsx:175`

### Requirement: Wichtigste Geräte live
Das System MUSS die als kritisch markierten Geräte (höchstens 10, in Inventar-Standardreihenfolge,
d. h. nach Name ohne Groß/Klein) mit allen Gerätefeldern und den effektiv überwachten Ports
(`monitorPortsEffective`) liefern. Die Oberfläche zeigt je Gerät Name (Link zur Detailseite),
IP (oder „—"), „Port a, b" bzw. „Ping" und den Zustand: `online` → „erreichbar", `offline` → „nicht
erreichbar", sonst „wird geprüft…". Ohne kritische Geräte erscheint ein Hinweis, wie man Geräte als
kritisch markiert. **[Muss]**

#### Szenario: Neu als kritisch markiert
- **WENN** ADMIN ein Gerät mit IP als kritisch markiert und das Dashboard neu lädt
- **DANN** erscheint es in der Liste und wird bereits überwacht (nicht dauerhaft „wird geprüft…")

Quelle: `backend/app/main.py:1626`, `backend/app/main.py:1629`, `backend/app/db.py:632`, `backend/app/db.py:1890`,
`backend/app/monitor.py:40`, `frontend/src/pages/DashboardPage.tsx:128`

### Requirement: Überwachungsstatus und automatische Aktualisierung
Das System MUSS `monitorEnabled` (Default `true`) und `monitorIntervalSeconds` (Default 10) aus den
Einstellungen liefern. Die Oberfläche MUSS bei aktiver Überwachung „live · alle <n> s" anzeigen und
die Daten im Takt von max(5, `monitorIntervalSeconds`) Sekunden neu laden – nur solange der Tab
sichtbar ist. Bei abgeschalteter Überwachung: Badge „Überwachung aus", kein automatisches Neuladen,
für ADMIN ein Hinweis mit Link auf Einstellungen → Überwachung. **[Muss]** (Untergrenze 5 s **[Impl]**)

#### Szenario: Hintergrund-Tab
- **WENN** der Browser-Tab in den Hintergrund wechselt
- **DANN** stoppt das periodische Neuladen und startet beim Zurückkehren wieder

Quelle: `backend/app/main.py:1630`, `backend/app/db.py:443`, `backend/app/db.py:444`, `frontend/src/pages/DashboardPage.tsx:30`

### Requirement: Letzter Scan
Das System MUSS den zuletzt gestarteten Scan (nach Startzeit) liefern oder `null`, wenn es keinen
gibt. Die Oberfläche zeigt „Letzter Scan: <Datum/Uhrzeit de-DE> (<status>)". **[Muss]**

#### Szenario: Noch nie gescannt
- **WENN** kein Scan existiert
- **DANN** ist `lastScan = null` und die Zeile entfällt

Quelle: `backend/app/main.py:1633`, `backend/app/db.py:1817`, `frontend/src/pages/DashboardPage.tsx:192`

### Requirement: Einrichtungsstand
Das System MUSS `homeName` (Default „Mein Zuhause", Seitentitel) und `llmConfigured` liefern. `llmConfigured` ist wahr, wenn der gewählte Anbieter Ollama
ist oder für den gewählten Anbieter ein API-Schlüssel hinterlegt ist. Ist er falsch, sieht ADMIN
einen Hinweis mit Link auf Einstellungen → KI-Assistent. Der API-Schlüssel selbst wird nicht
ausgeliefert. **[Muss]**

#### Szenario: Ollama ohne Schlüssel
- **WENN** `llmProvider = OLLAMA` und kein Schlüssel gesetzt ist
- **DANN** ist `llmConfigured = true`

Quelle: `backend/app/main.py:1614`, `backend/app/main.py:1634`, `backend/app/llm_providers.py:88`,
`frontend/src/pages/DashboardPage.tsx:87`, `backend/app/db.py:409`

### Requirement: Internet-Schnelltest
Die Oberfläche MUSS jedem angemeldeten Nutzer einen Knopf „Internet prüfen" bieten, der den
Diagnose-Test `internet_check` ausführt und das Ergebnis als Hinweis zeigt (grün nur, wenn
Internet erreichbar, DNS funktioniert und Webseiten laden; sonst rot), mit der Erklärung im Klartext. **[Muss]**

#### Szenario: DNS defekt
- **WENN** der Test meldet, dass DNS nicht funktioniert
- **DANN** erscheint die Erklärung als roter Hinweis

Quelle: `frontend/src/pages/DashboardPage.tsx:45`, `:82`, `backend/app/main.py:1471`;
Details: [diagnose](../diagnose/spec.md)

### Requirement: Neue Oberfläche (Schalter `uiCalm`)
Ist die neue Oberfläche aktiv (`uiCalm` bzw. `?ui=calm`), MUSS `/` statt der Kacheln die Startseite
`StartCalm` zeigen; bei ausgeschaltetem Schalter bleibt alles oben Beschriebene unverändert. Sie
ruft dieselben Endpunkte (`/api/dashboard`, zusätzlich `/api/monitor`; `/api/docs` nur, solange ein
Gerät ausgefallen ist) im selben Takt und mit derselben Pause bei verstecktem Tab auf. Abweichend
von oben gilt mit Schalter: **[Muss]**
- Kein Seitentitel `<h1>` und kein Untertitel; der Name des Zuhauses steht in der Shell.
- Ein Status-Hero oben: Sind überwachte Geräte (`/api/monitor` → `systems`, `status = offline`;
  dieselbe Menge wie der Netzplan, nicht alle Geräte mit Status `offline`) nicht erreichbar, nennt er bei einem
  Gerät dessen Namen mit „seit <Zeit>" (jüngster `offline`-Eintrag in `events`), sonst die Anzahl;
  Aktionen „Ansehen" (Geräteseite, bei mehreren `/plan`), „Assistent fragen" (`/assistent`) und
  „Notfall-Checkliste" (`/dokumentation/notfall`, nur wenn das Kapitel existiert). Sonst „Alles
  erreichbar" bzw. ein Hinweis bei leerem Inventar, abgeschalteter Überwachung oder ohne
  überwachtes Gerät.
- Eine Zahlenzeile ersetzt die vier Kacheln: `total` Geräte · `online` erreichbar · `critical`
  wichtig · `accounts` Zugänge · Scan <Zeit von `lastScan.startedAt`> (Zusatz bei `failed`/`running`).
- Sind mehr kritische Geräte vorhanden als geliefert, steht unter der Liste „+<critical − Anzahl>
  weitere" mit Link auf `/geraete?importance=critical` (dieselbe Menge, siehe [inventar](../inventar/spec.md)).
- Ein kritisches Gerät, das die Überwachung nicht prüft (nicht in `/api/monitor`, z. B. ohne IP und
  Hostname, oder Überwachung aus), zeigt „Stand letzter Scan" statt eines Live-Status.
- Das Ergebnis von „Internet prüfen" bleibt mit Uhrzeit sichtbar, bis die Seite verlassen wird;
  ein Fehler erscheint dort statt die Seite zu ersetzen.
- Der KI-Hinweis (nur ADMIN) ist ein Status-Chip „Assistent nicht eingerichtet · Einrichten".
- Während des Ladens erscheint ein Skeleton statt eines Spinners.
- Der Hero ist nur grün („Alles erreichbar"), wenn **jedes** überwachte Gerät `online` ist; solange
  eines noch `unknown` ist (z. B. direkt nach dem Einschalten der Überwachung), steht dort neutral
  „Wird geprüft …".
- Schlägt eine spätere Aktualisierung fehl, bleibt der letzte bekannte Stand sichtbar, darüber ein
  Hinweis „Aktualisierung fehlgeschlagen"; die nächste erfolgreiche Aktualisierung entfernt ihn. Nur
  ein Fehler beim ersten Laden ersetzt die Seite durch die Fehlermeldung.
- Wird der Tab wieder sichtbar, lädt die Seite sofort neu (zusätzlich zum Takt der Überwachung).
- Alarm (roter Hero) nur bei eingeschalteter Überwachung: Ist sie aus, zählt ein gespeicherter
  Status `offline` nicht als aktueller Ausfall; der Hero sagt dann „Überwachung ist aus".
- Die Alarm-Menge sind die überwachten Geräte (`monitored = 1`, wie im Netzplan), deshalb heißt es
  „überwachtes Gerät", nicht „wichtiges Gerät".

#### Szenario: Ein überwachtes Gerät fällt aus
- **WENN** die Überwachung die Heizung seit 07:42 als `offline` führt
- **DANN** steht oben „Heizung ist nicht erreichbar" mit „seit 07:42" und den drei Aktionen

#### Szenario: Kurzer Aussetzer des Backends
- **WENN** die Seite geladen ist und eine spätere Aktualisierung fehlschlägt
- **DANN** bleiben Hero und Listen mit dem letzten Stand stehen, darüber steht „Aktualisierung
  fehlgeschlagen", und nach der nächsten erfolgreichen Aktualisierung verschwindet der Hinweis

#### Szenario: Zwölf kritische Geräte
- **WENN** 12 Geräte kritisch sind
- **DANN** zeigt die Liste 10 und darunter „+2 weitere"

Quelle: `frontend/src/pages/start/StartCalm.tsx`, `frontend/src/App.tsx` (Route `/`)

## Daten

Aus [data-model](../../contracts/data-model.md), nur lesend:
- `systems`: alle Felder (Zähler, Arten, kritische Geräte).
- `accounts`: nur Anzahl.
- `scans`: jüngste Zeile komplett (`id, startedAt, finishedAt, status, subnets, progress, phase, summary, log`).
- `settings`: `homeName`, `setupCompleted`, `llmProvider`, API-Schlüssel des gewählten Anbieters
  (nur geprüft, ob gesetzt), `monitorEnabled`, `monitorIntervalSeconds`.

## Schnittstellen

| Methode | Pfad | Rolle | Zweck |
|---|---|---|---|
| GET | /api/dashboard | MEMBER | `{homeName, counts, byKind, kindLabels, criticalSystems, monitorIntervalSeconds, monitorEnabled, lastScan, llmConfigured}` |

Berührte fremde Routen: `POST /api/diagnostics` ([diagnose](../diagnose/spec.md)); Links auf
`/scan` ([discovery-und-scan](../discovery-und-scan/spec.md)), `/einstellungen`
([einstellungen-und-llm-provider](../einstellungen-und-llm-provider/spec.md)), `/geraete`
([inventar](../inventar/spec.md)).

UI-Seite(n): `frontend/src/pages/DashboardPage.tsx` (Route `/`); mit Schalter `uiCalm`
`frontend/src/pages/start/StartCalm.tsx`.

## Nicht-Ziele und Grenzen

- Keine eigene Datenhaltung, keine Historie/Diagramme; Status kommt aus der Überwachung
  ([monitoring](../monitoring/spec.md)) bzw. dem letzten Scan.
- Kein Push (WebSocket/SSE); Aktualität nur durch periodisches Neuladen.
- Keine Konfiguration der Kacheln.

## Ist-Implementierung (nur Referenz, [Impl])

- Alle Zähler werden bei jedem Aufruf aus der vollständigen Geräteliste im Speicher berechnet.
- Reihenfolge von `byKind` im JSON: alphabetisch nach Art; sortiert wird erst im Client.

## OFFEN

- > OFFEN: `lastScan` liefert die komplette Scan-Zeile inkl. vollständigem `log` und `summary` an MEMBER (`backend/app/main.py:1633`); die UI braucht nur `startedAt`/`status`. Unnötige Datenmenge und Offenlegung von Scan-Details.
- > OFFEN: Kritische Geräte ohne IP und Hostname werden nie überwacht (`backend/app/db.py:1900`) und stehen dauerhaft als „wird geprüft…" auf dem Dashboard – irreführend.
- > OFFEN: Bei mehr als 10 kritischen Geräten werden still nur die ersten 10 (alphabetisch) gezeigt; die Kachel nennt die volle Zahl, ein Hinweis auf weitere fehlt.
- > OFFEN: Status `unknown` und jeder andere Wert erscheinen gleichermaßen als „wird geprüft…", auch wenn die Überwachung abgeschaltet ist (dann wird nichts geprüft).
