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
`frontend/src/pages/start/StartPage.tsx`.

## Anforderungen

### Requirement: Kennzahlen
Das System MUSS folgende Zähler über das gesamte Inventar liefern: `total` (alle Geräte), `online`
(`status = online`), `critical` (`importance = critical`) und
`accounts` (alle gespeicherten Zugänge); `counts` hat genau diese vier Schlüssel. Die Oberfläche zeigt sie als Zahlenzeile (siehe „Startseite“). **[Muss]**

#### Szenario: Zählung
- **WENN** 5 Geräte existieren, davon 3 `online`, 1 `offline`, 1 `unknown`, 2 `critical`
- **DANN** ist `counts = {total: 5, online: 3, critical: 2, accounts: …}`

#### Szenario: Leeres Inventar
- **WENN** noch kein Gerät existiert
- **DANN** weist die Startseite auf das leere Inventar hin (Status-Hero, siehe „Startseite“)

Quelle: `backend/app/main.py:1616`, `frontend/src/pages/start/StartPage.tsx`

### Requirement: Geräte nach Art
Das System MUSS je vorkommender Art (`kind`) die Anzahl Geräte liefern (`byKind`, nur Arten mit
mindestens einem Gerät) sowie die deutschen Anzeigenamen (`kindLabels`). Die Oberfläche listet sie
absteigend nach Anzahl („Was es im Netz gibt"); jeder Eintrag verlinkt auf die gefilterte
Geräteliste `/geraete?kind=<art>`. **[Muss]**

#### Szenario: Drill-down
- **WENN** der Nutzer auf „Router (2)" klickt
- **DANN** öffnet sich die Geräteliste, gefiltert auf Art `router`

Quelle: `backend/app/main.py:1624`, `backend/app/docs.py:21`, `frontend/src/pages/start/StartPage.tsx`

### Requirement: Wichtigste Geräte live
Das System MUSS die als kritisch markierten Geräte (höchstens 10, in Inventar-Standardreihenfolge,
d. h. nach Name ohne Groß/Klein) mit allen Gerätefeldern und den effektiv überwachten Ports
(`monitorPortsEffective`) liefern. Die Oberfläche zeigt je Gerät Name (Link zur Detailseite),
IP (oder „—"), „Port a, b" bzw. „Ping" und den Zustand: `online` → „erreichbar", `offline` → „nicht
erreichbar", sonst „wird geprüft…". Ohne Live-Ergebnis unterscheidet die Oberfläche den Grund (siehe unten). Ohne kritische Geräte erscheint ein Hinweis, wie man Geräte als
kritisch markiert. **[Muss]**

#### Szenario: Neu als kritisch markiert
- **WENN** ADMIN ein Gerät mit IP als kritisch markiert und das Dashboard neu lädt
- **DANN** erscheint es in der Liste und wird bereits überwacht (nicht dauerhaft „wird geprüft…")

#### Szenario: Kein Live-Ergebnis
- **WENN** ein kritisches Gerät nicht live geprüft wird
- **DANN** steht je nach Grund (in dieser Reihenfolge) „nicht überwachbar – keine Adresse", „Überwachung aus" (Gerät abgewählt), „Stand letzter Scan" (globale Überwachung aus) oder „wird geprüft …" (überwacht, noch kein Ergebnis); der Tooltip nennt den Letztstand vom Scan

Quelle: `backend/app/main.py:1626`, `backend/app/main.py:1629`, `backend/app/db.py:632`, `backend/app/db.py:1890`,
`backend/app/monitor.py:40`, `frontend/src/pages/start/StartPage.tsx`

### Requirement: Überwachungsstatus und automatische Aktualisierung
Das System MUSS `monitorEnabled` (Default `true`) und `monitorIntervalSeconds` (Default 10) aus den
Einstellungen liefern. Die Oberfläche MUSS bei aktiver Überwachung „live · alle <n> s" anzeigen und
die Daten im Takt von max(5, `monitorIntervalSeconds`) Sekunden neu laden – nur solange der Tab
sichtbar ist. Bei abgeschalteter Überwachung: Badge „Überwachung aus", kein automatisches Neuladen,
für ADMIN ein Hinweis mit Link auf Einstellungen → Überwachung. **[Muss]** (Untergrenze 5 s **[Impl]**)

#### Szenario: Hintergrund-Tab
- **WENN** der Browser-Tab in den Hintergrund wechselt
- **DANN** stoppt das periodische Neuladen und startet beim Zurückkehren wieder

Quelle: `backend/app/main.py:1630`, `backend/app/db.py:443`, `backend/app/db.py:444`, `frontend/src/pages/start/StartPage.tsx`

### Requirement: Letzter Scan
Das System MUSS den zuletzt gestarteten Scan (nach Startzeit) liefern oder `null`, wenn es keinen
gibt. Die Oberfläche zeigt ihn in der Zahlenzeile (siehe „Startseite“). **[Muss]** Der Eintrag
enthält nur `startedAt`, `finishedAt` und `status`, nie `log`, `summary` oder `subnets`, weil
das Dashboard auch MEMBER offensteht und Scan-Details nur Admins zustehen (#119). **[Muss]**

#### Szenario: Noch nie gescannt
- **WENN** kein Scan existiert
- **DANN** ist `lastScan = null` und die Zeile entfällt

#### Szenario: MEMBER ruft das Dashboard ab
- **WENN** ein MEMBER `GET /api/dashboard` aufruft und ein Scan existiert
- **DANN** hat `lastScan` genau die Schlüssel `startedAt`, `finishedAt`, `status`

Quelle: `backend/app/routes/overview.py`, `backend/app/db.py:1817`, `frontend/src/pages/start/StartPage.tsx`

### Requirement: Einrichtungsstand
Das System MUSS `homeName` (Default „Mein Zuhause", Seitentitel) und `llmConfigured` liefern. `llmConfigured` ist wahr, wenn der gewählte Anbieter Ollama
ist oder für den gewählten Anbieter ein API-Schlüssel hinterlegt ist. Ist er falsch, sieht ADMIN
einen Hinweis mit Link auf Einstellungen → KI-Assistent. Der API-Schlüssel selbst wird nicht
ausgeliefert. **[Muss]**

#### Szenario: Ollama ohne Schlüssel
- **WENN** `llmProvider = OLLAMA` und kein Schlüssel gesetzt ist
- **DANN** ist `llmConfigured = true`

Quelle: `backend/app/main.py:1614`, `backend/app/main.py:1634`, `backend/app/llm_providers.py:88`,
`frontend/src/pages/start/StartPage.tsx`, `backend/app/db.py:409`

### Requirement: Internet-Schnelltest
Die Oberfläche MUSS jedem angemeldeten Nutzer einen Knopf „Internet prüfen" bieten, der den
Diagnose-Test `internet_check` ausführt und das Ergebnis als Hinweis zeigt (grün nur, wenn
Internet erreichbar, DNS funktioniert und Webseiten laden; sonst rot), mit der Erklärung im Klartext. **[Muss]**

#### Szenario: DNS defekt
- **WENN** der Test meldet, dass DNS nicht funktioniert
- **DANN** erscheint die Erklärung als roter Hinweis

Quelle: `frontend/src/pages/start/StartPage.tsx`, `backend/app/main.py:1471`;
Details: [diagnose](../diagnose/spec.md)

### Requirement: Startseite
Die Route `/` MUSS die Startseite `StartPage` zeigen. Sie ruft `/api/dashboard`, zusätzlich
`/api/monitor` (und `/api/docs` nur, solange ein Gerät ausgefallen ist) im Takt der Überwachung und
mit Pause bei verstecktem Tab auf. Zusätzlich zu den oben beschriebenen Daten gilt: **[Muss]**
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
- Ein kritisches Gerät, das die Überwachung nicht prüft (nicht in `/api/monitor`), zeigt statt eines
  Live-Status je nach Grund: ohne IP und Hostname „nicht überwachbar – keine Adresse", mit
  `monitored=0` „Überwachung aus", bei global abgeschalteter Überwachung „Stand letzter Scan",
  sonst „wird geprüft …". Die Untertitelzeile „beim Scan <Status>" bleibt als Zusatzinfo.
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

Quelle: `frontend/src/pages/start/StartPage.tsx`, `frontend/src/App.tsx` (Route `/`)

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

UI-Seite(n): `frontend/src/pages/start/StartPage.tsx` (Route `/`).

## Nicht-Ziele und Grenzen

- Keine eigene Datenhaltung, keine Historie/Diagramme; Status kommt aus der Überwachung
  ([monitoring](../monitoring/spec.md)) bzw. dem letzten Scan.
- Kein Push (WebSocket/SSE); Aktualität nur durch periodisches Neuladen.
- Keine Konfiguration der Kacheln.

## Ist-Implementierung (nur Referenz, [Impl])

- Alle Zähler werden bei jedem Aufruf aus der vollständigen Geräteliste im Speicher berechnet.
- Reihenfolge von `byKind` im JSON: alphabetisch nach Art; sortiert wird erst im Client.

## OFFEN

