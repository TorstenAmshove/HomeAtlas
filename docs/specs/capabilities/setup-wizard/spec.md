# Setup-Wizard (Ersteinrichtung)

> Status: Ist-Verhalten, aus dem Code zurückgewonnen (Stand 0159807). Quellen als `datei:zeile`.

## Zweck

Nach dem allerersten Login (und der Pflicht-Einrichtung des zweiten Faktors) fragt HomeAtlas den
Administrator einmalig nach dem, was ein Netzwerk-Scan nie selbst herausfindet: wie der Haushalt
heißt, welche Geräte wirklich wichtig sind und welche Zugänge dazugehören. Danach ist die App
benutzbar; alles lässt sich später in Inventar, Zugängen und Einstellungen ändern.

## Rollen und Rechte

| Aktion | ADMIN | MEMBER |
|---|---|---|
| Wizard angezeigt bekommen, solange Setup offen | ja (erzwungen) | nein, App direkt nutzbar |
| Setup absenden (`POST /api/setup`) | ja | nein (403) |
| Setup-Status lesen (`GET /api/health`) | ja | ja (auch ohne Login) |

## Anforderungen

### Requirement: Setup-Status öffentlich abfragbar
`GET /api/health` MUSS ohne Anmeldung `{status: "ok", setupCompleted: bool, userCount: int}`
liefern.
`setupCompleted` ist `false`, bis das Setup einmal abgeschickt wurde. Die Route dient auch als
Liveness-Check des Stacks. **[Muss]** (`userCount`: **[Impl]**, siehe OFFEN)

#### Szenario: Frische Instanz
- **WENN** noch kein Setup abgeschickt wurde
- **DANN** `setupCompleted` = false

#### Szenario: CI-Gesundheitsprüfung
- **WENN** der Stack startet
- **DANN** antwortet `GET /api/health` über nginx mit 2xx (CI wartet bis 60 s darauf)

Quelle: `backend/app/main.py:157`, `backend/app/db.py:410`, `.github/workflows/build.yml:97`

### Requirement: Gating-Reihenfolge
Die Oberfläche MUSS nach dem Login in dieser Reihenfolge führen: MFA-Einrichtung (falls nötig, siehe
[auth-und-rollen](../auth-und-rollen/spec.md)) → Setup-Wizard, solange `setupCompleted` false UND der
Benutzer ADMIN ist → App. Ein MEMBER wird bei offenem Setup NICHT blockiert. Der Wizard ist
ausschließlich vollflächig; es gibt keine eigene Route und keine Navigation, solange er aktiv ist.
**[Muss]**

#### Szenario: Admin nach MFA-Einrichtung
- **WENN** ADMIN mit aktivem Faktor, `setupCompleted` = false
- **DANN** sieht er nur den Wizard „Willkommen bei HomeAtlas“

#### Szenario: Mitglied bei offenem Setup
- **WENN** MEMBER mit aktivem Faktor, `setupCompleted` = false
- **DANN** sieht er die normale App

#### Szenario: Nach Abschluss
- **WENN** das Setup erfolgreich gespeichert wurde
- **DANN** lädt die UI Benutzer und Health neu und zeigt das Dashboard mit dem gewählten Namen als Überschrift

Quelle: `frontend/src/App.tsx:56`, `frontend/src/App.tsx:104`, Test: `frontend/e2e/smoke.spec.ts::login, MFA enrollment, setup and main routes render without errors`

### Requirement: Abgefragte Angaben
Der Wizard MUSS in drei Schritten (Anzeige „Schritt n von 3“, Vor/Zurück ohne Datenverlust) erfassen:
1. **Zuhause**: Name (Vorbelegung „Mein Zuhause“), optional ein Netzwerkbereich (CIDR-Freitext,
   Platzhalter `192.168.1.0/24`; leer = automatische Erkennung).
2. **Wichtigste Geräte** (Liste, beliebig erweiterbar, mind. ein Eintrag sichtbar): Name, Art (Auswahl
   aus 13 Arten: `router, network, server, nas, pc, printer, smarthome, heating, climate, energy,
   media, camera, other`), IP/Adresse, Standort, Benutzername, Passwort (alle außer Name optional).
   Vorbelegt: ein Gerät der Art `router` mit Zweck „Internetzugang und WLAN“.
3. **Wichtige Konten** ohne Gerätebezug (Liste): Bezeichnung, Art (`contract, login, wifi, apikey,
   other`, Default `contract`), Benutzername/Kundennummer, Passwort, Notiz. Vorbelegt: ein Konto
   „Internetanbieter“.
Abgeschickt wird erst am Ende von Schritt 3; Einträge ohne Namen/Bezeichnung werden weggelassen.
**[Muss]** (konkrete Texte, Vorbelegungen: **[Impl]**)

#### Szenario: Durchklicken ohne Eingaben
- **WENN** der Admin nur den Namen setzt und zweimal „Weiter“, dann „Fertig — los geht's“ klickt
- **DANN** wird Setup mit dem Namen, ohne Geräte (Router-Entwurf hat keinen Namen), mit Konto
  „Internetanbieter“ ohne Passwort gespeichert

Quelle: `frontend/src/gates/Setup.tsx`, `frontend/src/gates/setupModel.ts`, Test: `frontend/e2e/smoke.spec.ts::login, MFA enrollment, setup and main routes render without errors`

### Requirement: Ausweg aus dem Wizard (UI)
Der Wizard MUSS auf jedem Schritt „Abmelden“ anbieten, damit niemand darin festsitzt. Ist schon etwas eingetragen (Angaben weichen von der
Vorbelegung ab oder Schritt > 1), MUSS vorher ein Prüfdialog fragen („Deine Angaben aus der
Einrichtung werden verworfen“, „Trotzdem abmelden“ / „Angemeldet bleiben“). Ein „Überspringen“ gibt
es nicht: für ADMIN bleibt der Wizard, bis das Setup gespeichert ist. **[Muss]**

#### Szenario: Abbrechen in der Einrichtung
- **WENN** der Admin einen Namen eingetragen hat und „Abmelden“ wählt
- **DANN** fragt die Oberfläche nach; „Angemeldet bleiben“ lässt die Eingaben stehen, „Trotzdem
  abmelden“ führt zum Login, und nach dem nächsten Anmelden beginnt der Wizard bei Schritt 1

Quelle: `frontend/src/gates/Setup.tsx`, Test: `frontend/e2e/smoke.spec.ts::login, MFA enrollment, setup and main routes render without errors`

### Requirement: Entwurf übersteht Neuladen, ohne Passwörter und Notizen
Schritt und Angaben des Wizards MÜSSEN ein Neuladen des Tabs überstehen
(`sessionStorage`, Schlüssel `homeatlas.draft.setup.wizard`). Passwörter von Geräten und Konten sowie
Konto-Notizen (dort stehen gelegentlich Zugangshinweise) DÜRFEN NICHT in den Entwurf gelangen;
wurden welche eingegeben, MUSS der Wizard nach dem Neuladen darauf hinweisen, dass sie erneut
einzugeben sind. Benutzername bzw. Kundennummer bleiben erhalten. Abmelden und erfolgreiches Speichern löschen den Entwurf.
Der Entwurf gehört dem angemeldeten Admin (gespeichert mit seiner Benutzer-ID): meldet sich nach
abgelaufener Sitzung im selben Tab jemand anderes an, wird er nicht angezeigt, sondern verworfen.
Beim Laden wird jedes Feld auf seinen Typ geprüft; ein beschädigter Eintrag bringt den Wizard nicht
zum Absturz.
**[Muss]** (Schlüsselname: **[Impl]**)

#### Szenario: Neuladen in Schritt 2
- **WENN** der Admin in Schritt 2 einen Gerätenamen und ein Passwort eingibt und die Seite neu lädt
- **DANN** steht er wieder in Schritt 2 mit dem Gerätenamen, das Passwortfeld ist leer, ein Hinweis
  erklärt das, und der Browser-Speicher enthält das Passwort nicht

#### Szenario: Notiz in Schritt 3
- **WENN** der Admin in Schritt 3 Benutzername, Passwort und eine Notiz eines Kontos eingibt und die
  Seite neu lädt
- **DANN** sind Passwort und Notiz leer, der Benutzername steht noch da, der Hinweis erklärt das, und
  der Browser-Speicher enthält die Notiz nicht

Quelle: `frontend/src/gates/setupModel.ts`, `frontend/src/gates/Setup.tsx`, Test: `frontend/e2e/smoke.spec.ts::login, MFA enrollment, setup and main routes render without errors`

### Requirement: Setup speichern (nur ADMIN)
`POST /api/setup` MUSS ADMIN mit aktivem zweiten Faktor verlangen und akzeptieren:
`{homeName = "Mein Zuhause", systems: [{name, kind = "other", ip, location, purpose, url, username,
password}], accounts: [{label, category = "login", username, secret, url, notes}], scanSubnets: [str]}`.
Antwort `{ok: true, systems: <Anzahl angelegter Geräte>, accounts: <Anzahl angelegter Konten>}`.
**[Muss]**

#### Szenario: MEMBER sendet Setup
- **WENN** ein MEMBER `POST /api/setup` aufruft
- **DANN** 403, nichts wird gespeichert

Quelle: `backend/app/main.py:1638`, `backend/app/main.py:1649`, `backend/app/main.py:1658`, `backend/app/main.py:1665`

### Requirement: Geräte aus dem Wizard
Für jedes Gerät mit nicht-leerem (getrimmtem) Namen MUSS ein Inventareintrag entstehen, als manuell
bestätigt (`confirmed` = 1, `discovered` = 0). Die Wichtigkeit MUSS `critical` sein für die Arten
`router`, `server`, `nas`, `heating`, sonst `normal`. Kritische Geräte mit Adresse werden dadurch
automatisch überwacht (siehe [monitoring](../monitoring/spec.md)). Name wird ungetrimmt übernommen.
**[Muss]** (Art→Wichtigkeit-Zuordnung: **[Muss]**, OFFEN ob Alternative das übernehmen soll)

#### Szenario: NAS mit Adresse
- **WENN** Gerät `{name: "Syno", kind: "nas", ip: "192.168.1.5"}` übergeben wird
- **DANN** entsteht ein System mit `importance = critical`, `confirmed = 1`, `discovered = 0`, das bei der nächsten Überwachungsrunde überwacht wird

#### Szenario: Leerer Name
- **WENN** `name` nur aus Leerzeichen besteht
- **DANN** wird der Eintrag übersprungen und nicht gezählt

Quelle: `backend/app/main.py:1671`, `backend/app/main.py:1676`, `backend/app/db.py:1890`, `backend/app/monitor.py:144`

### Requirement: Zugangsdaten aus dem Wizard verschlüsselt
Hat ein Gerät Benutzername ODER Passwort, MUSS ein zugehöriger Zugang entstehen (Bezeichnung „Zugang
<Gerätename>“, Kategorie `login`, Benutzername, URL des Geräts), dessen Passwort verschlüsselt wie
jeder Zugang gespeichert wird (leeres Passwort bleibt leer). Freie Konten mit nicht-leerer Bezeichnung
MÜSSEN als geräteunabhängige Zugänge mit verschlüsseltem Passwort gespeichert werden. Passwörter
dürfen nie in Freitextfeldern des Geräts landen. Die Zähler in der Antwort zählen nur die freien
Konten, nicht die Gerätezugänge. **[Muss]**

#### Szenario: Router mit Login
- **WENN** Gerät „FRITZ!Box“ mit `username: "admin"`, `password: "geheim123"`
- **DANN** existiert ein Zugang „Zugang FRITZ!Box“ (`category = login`) am Gerät, Passwort nur verschlüsselt gespeichert; `accounts` in der Antwort zählt ihn nicht

#### Szenario: Konto ohne Bezeichnung
- **WENN** ein Konto mit leerer `label` übergeben wird
- **DANN** wird es übersprungen

Quelle: `backend/app/main.py:1679`, `backend/app/main.py:1686`, `backend/app/crypto.py:43`, siehe [zugangsdaten](../zugangsdaten/spec.md)

### Requirement: Einstellungen und Abschluss-Flag
Das Setup MUSS `homeName` (unverändert, auch leer), `setupCompleted = true` und `scanSubnets` (Einträge
getrimmt, leere entfernt; überschreibt bisherige Liste) in den Einstellungen speichern. Nach
erfolgreichem Setup erscheint der Wizard nicht mehr. **[Muss]**

#### Szenario: Netzbereich angegeben
- **WENN** `scanSubnets: [" 192.168.1.0/24 ", ""]`
- **DANN** gespeichert `scanSubnets = ["192.168.1.0/24"]`, `setupCompleted = true`

Quelle: `backend/app/main.py:1692`

### Requirement: Keine automatischen Folgeaktionen
Das Setup MUSS sich auf das Speichern beschränken: es startet keinen Scan und erzeugt keine
Dokumentation. Scan und Doku laufen über ihre eigenen Wege (Zeitplan, manueller Start). **[Impl]**

#### Szenario: Nach dem Setup
- **WENN** das Setup gespeichert ist
- **DANN** existieren noch keine Dokumentationskapitel, bis Doku-Generierung oder Scan laufen

Quelle: `backend/app/main.py:1665`, Test: `frontend/e2e/smoke.spec.ts::login, MFA enrollment, setup and main routes render without errors` (ruft `/api/docs/generate` explizit auf)

## Daten

Aus [data-model](../../contracts/data-model.md):
- `settings` (gelesen/geschrieben): `homeName`, `setupCompleted`, `scanSubnets`.
- `systems` (geschrieben): `name, kind, ip, location, purpose, url, confirmed, discovered, importance`.
- `accounts` (geschrieben): `systemId, label, category, username, secretEnc, url, notes`.
- `users` (gelesen, nur Anzahl für `userCount`).

## Schnittstellen

| Methode | Pfad | Rolle | Zweck |
|---|---|---|---|
| POST | /api/setup | ADMIN | Wizard-Ergebnis speichern, `setupCompleted` setzen |
| GET | /api/health | öffentlich | Liveness + `setupCompleted` + `userCount` |

Berührt: `PATCH /api/settings` kann `setupCompleted`/`homeName` ebenfalls ändern (siehe
[einstellungen-und-llm-provider](../einstellungen-und-llm-provider/spec.md)); `GET /api/settings` gibt
MEMBER nur `homeName` und `setupCompleted`.

UI-Seite(n): `frontend/src/gates/Setup.tsx` (keine eigene Route; ersetzt die App, solange ADMIN
und `setupCompleted` false), Gating in `frontend/src/App.tsx`.

## Nicht-Ziele und Grenzen

- Kein Anlegen weiterer Benutzer, kein LLM-Provider, keine Scan-Optionen außer einem Netzbereich.
- Keine Validierung von IP-Adressen, CIDR-Angaben oder Gerätearten im Backend.
- Der Entwurf (ohne Passwörter) übersteht ein Reload; Abmelden verwirft ihn.
- Kein „Setup erneut ausführen“ in der UI.

## Ist-Implementierung (nur Referenz, [Impl])

- `App.tsx` lädt `/api/auth/me` und `/api/health` parallel; `setupCompleted` steht im Frontend
  initial auf `true`, damit keine Wizard-Blitzanzeige erscheint.
- Die UI sendet nur einen Netzbereich (`scanSubnets` mit max. einem Eintrag) und kennt keine Felder
  für `purpose`/`url` der Geräte bzw. `url` der Konten (nur Vorbelegung `purpose` beim Router).
- Gerätezugänge werden ohne `allowProbe` angelegt (Default aus), also nicht zum Auslesen verwendet
  (siehe [credentialed-probing](../credentialed-probing/spec.md)).

## OFFEN

- > OFFEN: `POST /api/setup` prüft nicht, ob das Setup schon abgeschlossen ist; erneuter Aufruf legt Geräte/Konten doppelt an und überschreibt `homeName`/`scanSubnets`.
- > OFFEN: Antwortfeld `accounts` zählt Gerätezugänge nicht mit – gewollt oder Ungenauigkeit?
- > OFFEN: Keine Validierung der `scanSubnets`-Einträge; ungültiger Freitext landet in den Einstellungen (Verhalten im Scan siehe [discovery-und-scan](../discovery-und-scan/spec.md)).
- > OFFEN: Leerer `homeName` wird gespeichert; Doku/Topologie/Assistent fallen dann teils auf Ersatztexte zurück.
- > OFFEN: `GET /api/health` ist ohne Login erreichbar und verrät `userCount`; das Frontend nutzt das Feld nicht.
- > OFFEN: Art→Wichtigkeit (`router/server/nas/heating` → kritisch) ist hart verdrahtet; `network` (Switch/AP) wird nicht kritisch – Absicht?
- > OFFEN: Kein Duplikatabgleich mit bereits gescannten Geräten gleicher IP; ein späterer Scan muss das zusammenführen (siehe [inventar](../inventar/spec.md)).
