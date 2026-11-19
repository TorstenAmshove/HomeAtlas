# Authentifizierung und Rollen

> Status: Ist-Verhalten, aus dem Code zurückgewonnen (Stand 0159807). Quellen als `datei:zeile`.

## Zweck

HomeAtlas speichert Router-, NAS- und WLAN-Passwörter. Wer die App öffnet, muss sich deshalb mit
Passwort und verpflichtendem zweitem Faktor (Authenticator-App) anmelden. Zwei Rollen trennen den
Haushalt: Administratoren verwalten alles inklusive Geheimnissen, Mitglieder lesen Dokumentation
und nutzen den Assistenten, ohne je ein Klartext-Passwort zu sehen. Ein Zugriffsprotokoll hält fest,
wer sich wann angemeldet oder etwas Sicherheitsrelevantes getan hat; ein Kommandozeilen-Werkzeug
rettet ausgesperrte Instanzen.

## Rollen und Rechte

| Aktion | ADMIN | MEMBER |
|---|---|---|
| Anmelden, Abmelden, eigene Identität abfragen (`/me`) | ja | ja |
| Zweiten Faktor einrichten (solange nicht aktiv) | ja | ja |
| Eigenes Passwort ändern, Passwortrichtlinie lesen | ja (nach MFA) | ja (nach MFA) |
| Benutzer auflisten, anlegen, ändern, löschen | ja | nein (403) |
| Zweiten Faktor eines Benutzers zurücksetzen | ja | nein (403) |
| Zugriffsprotokoll lesen | ja | nein (403) |
| Interaktive Konsolen (WebSocket) öffnen | ja | nein (Verbindung abgewiesen) |
| Selbst den zweiten Faktor abschalten | nein (gibt es nicht) | nein |
| Notfall-Reset per CLI | wer Shell-Zugriff auf den Container hat | – |

## Anforderungen

### Requirement: Initialer Administrator
Das System MUSS beim Start, wenn noch kein Benutzer existiert, genau einen ADMIN anlegen: Name aus
`ADMIN_USERNAME` (Default `admin`), Passwort aus `ADMIN_PASSWORD` oder – falls nicht gesetzt –
generiert und genau einmal im Server-Log ausgegeben. Existiert mindestens ein Benutzer, MÜSSEN beide
Variablen wirkungslos sein. **[Muss]**

#### Szenario: Erster Start ohne Vorgabe
- **WENN** die Benutzertabelle leer ist und `ADMIN_PASSWORD` nicht gesetzt ist
- **DANN** wird ADMIN `admin` mit generiertem Passwort angelegt und Benutzername + Passwort einmalig
  als Warnung ins Log geschrieben (Hinweis: „nur EINMAL angezeigt“)

#### Szenario: Vorgabe per Umgebung
- **WENN** die Tabelle leer ist und `ADMIN_PASSWORD` gesetzt ist
- **DANN** wird der ADMIN mit genau diesem Passwort angelegt und nichts geloggt

#### Szenario: Neustart mit vorhandenen Benutzern
- **WENN** mindestens ein Benutzer existiert
- **DANN** passiert nichts, auch bei geänderten `ADMIN_*`-Variablen

Quelle: `backend/app/auth.py:30`, `backend/app/main.py:47`, Test: `frontend/e2e/smoke.spec.ts::login, MFA enrollment, setup and main routes render without errors` (nutzt `ADMIN_PASSWORD`)

### Requirement: Format des generierten Erstpasswort
Das generierte Passwort SOLL abtippbar sein: 4 zufällige Wörter aus einer festen Liste von 30
deutschen Wörtern plus eine Zahl 10–99, mit `-` verbunden (z. B. `Anker-Linde-Turm-Ufer-42`), und
damit die Passwortrichtlinie über die Passphrasen-Regel (≥ 20 Zeichen) erfüllen. **[Impl]**

#### Szenario: Generiertes Passwort
- **WENN** ein Passwort generiert wird
- **DANN** besteht es aus 5 durch `-` getrennten Teilen, der letzte zweistellig, Länge ≥ 22

Quelle: `backend/app/auth.py:39`, `backend/app/auth.py:47`

### Requirement: Passwort-Speicherung
Das System MUSS Passwörter nur gesalzen und mit einer langsamen Hashfunktion speichern; der
Klartext darf nie persistiert oder zurückgegeben werden. Heute: PBKDF2-HMAC-SHA256, 210 000
Iterationen, 16-Byte-Zufallssalz (hex) je Passwortsetzung. **[Muss]** (Algorithmus/Parameter: **[Impl]**)

#### Szenario: Passwort setzen
- **WENN** ein Passwort gesetzt oder geändert wird
- **DANN** wird ein neues Salz erzeugt und nur Hash + Salz gespeichert

Quelle: `backend/app/auth.py:20`, `backend/app/auth.py:26`, `backend/app/auth.py:122`

### Requirement: Login mit Passwort und zweitem Faktor
`POST /api/auth/login` MUSS drei Fälle unterscheiden:
1. Benutzer unbekannt oder Passwort falsch → 401 „Benutzername oder Passwort stimmt nicht.“
2. Passwort richtig, Konto hat aktiven zweiten Faktor, Code fehlt oder falsch → 401 mit Header
   `X-HomeAtlas-MFA: required`; Text unterscheidet „Code anfordern“ von „Code falsch/abgelaufen“.
3. Erfolg → Session wird angelegt, Antwort `{user}` (öffentliche Felder).

Ein Konto ohne aktiven zweiten Faktor MUSS sich mit Passwort allein anmelden können (es wird danach
in die Einrichtung gezwungen, siehe nächste Requirements); ein mitgeschickter Code wird ignoriert.
**[Muss]**

#### Szenario: Code wird nachgefordert
- **WENN** Passwort korrekt, `totpEnabled` = true, `totpCode` leer
- **DANN** 401, Header `X-HomeAtlas-MFA: required`, Detail „Bitte zusätzlich den 6-stelligen Code aus deiner Authenticator-App eingeben.“, keine Session

#### Szenario: Falscher Code
- **WENN** Passwort korrekt, Code falsch
- **DANN** 401, gleicher Header, Detail „Der Code stimmt nicht oder ist abgelaufen. …“

#### Szenario: Erstanmeldung ohne Faktor
- **WENN** Passwort korrekt, `totpEnabled` = false
- **DANN** 200, Session-Cookie gesetzt, `user.totpEnabled` = 0

Quelle: `backend/app/auth.py:62`, `backend/app/main.py:163`, Test: `frontend/e2e/smoke.spec.ts::login, MFA enrollment, setup and main routes render without errors`

### Requirement: Schutz gegen Durchprobieren
Das System MUSS fehlgeschlagene Anmeldungen (falsches Passwort, falscher oder bereits benutzter
TOTP-Code) zählen und weitere Versuche mit HTTP 429 und `Retry-After` ablehnen, solange in den
letzten 15 Minuten erreicht sind: 5 Fehlversuche für denselben Benutzernamen von derselben
Client-IP, 20 von derselben IP (beliebige Namen) oder 50 für denselben Namen (beliebige IPs). Eine
gesperrte Anmeldung wird nicht geprüft, auch nicht mit richtigem Passwort, und als `login` mit
`ok=0` und „gesperrt nach zu vielen Fehlversuchen“ protokolliert. Die Aufforderung, den Code
einzugeben (Passwort richtig, Code fehlt), ist kein Fehlversuch. Eine erfolgreiche Anmeldung löscht
nur den Zähler für Name + IP. **[Muss]** (Grenzwerte und Speicherung im Arbeitsspeicher **[Impl]**)

#### Szenario: Sperre nach fünf Fehlversuchen
- **WENN** von einer IP fünfmal ein falsches Passwort für „anna“ gesendet wird
- **DANN** antwortet auch der sechste Versuch mit richtigem Passwort und Code mit 429

#### Szenario: Andere Quelle nicht betroffen
- **WENN** die Fehlversuche von 10.0.0.66 kamen
- **DANN** kann sich „anna“ von 10.0.0.5 normal anmelden

Quelle: `backend/app/security.py` (`LoginThrottle`), `backend/app/main.py` (`login`), Tests:
`backend/tests/test_auth_login.py::test_lockout_after_repeated_failures_even_with_correct_password`,
`::test_wrong_codes_count_towards_lockout`, `::test_lockout_is_per_source_for_the_tight_limit`,
`::test_asking_for_the_code_is_not_a_failure`, `::test_ip_limit_covers_many_usernames`

### Requirement: TOTP-Codes sind einmalig
Das System MUSS je Benutzer den Zeitschritt des zuletzt verwendeten TOTP-Codes speichern und einen
Code ablehnen, dessen Zeitschritt nicht neuer ist (Wiederholung oder älterer Code), bei der Anmeldung
wie bei der Bestätigung der Einrichtung. Die Prüfung ist atomar, zwei gleichzeitige Anmeldungen mit
demselben Code können nicht beide gelingen. **[Muss]**

#### Szenario: Wiederverwendeter Code
- **WENN** „anna“ sich mit Code 123456 angemeldet hat und derselbe Code erneut gesendet wird
- **DANN** antwortet das System mit 401 und `X-HomeAtlas-MFA: required`

Quelle: `backend/app/db.py` (`claim_totp_counter`, Spalte `users.totpLastCounter`),
`backend/app/auth.py` (`verify_login`), Tests: `backend/tests/test_auth_login.py::test_totp_code_is_single_use`,
`::test_older_code_after_newer_one_is_rejected`

### Requirement: Kein Benutzer-Enumerations-Hinweis
Das System MUSS bei unbekanntem Benutzer und bei falschem Passwort dieselbe Antwort geben und für
einen unbekannten Benutzer trotzdem einen Hash berechnen, damit die Antwortzeit nichts verrät. Erst
ein korrektes Passwort darf den MFA-Header auslösen. **[Muss]**

#### Szenario: Unbekannter Benutzer
- **WENN** `username` existiert nicht
- **DANN** 401 mit identischem Text wie bei falschem Passwort, Hashberechnung mit Dummy-Salz erfolgt

Quelle: `backend/app/auth.py:67`, `backend/app/main.py:178`

### Requirement: Session
Nach erfolgreichem Login MUSS eine serverseitige Session mit opakem, zufälligem Token (heute 32 Byte
URL-safe) entstehen, übertragen als Cookie `homeatlas_session` mit `HttpOnly`, `SameSite=Lax`,
`Path=/`, `Max-Age` 30 Tage. Die Gültigkeit ist absolut 30 Tage ab Login (keine Verlängerung bei
Aktivität). Abgelaufene Sessions MÜSSEN abgewiesen werden. **[Muss]** (Cookie-Name, 30 Tage: **[Impl]**)

#### Szenario: Abgelaufene Session
- **WENN** ein Request ein Token mit `expiresAt` in der Vergangenheit trägt
- **DANN** 401 „Nicht angemeldet.“

#### Szenario: Aufräumen
- **WENN** eine neue Session angelegt wird
- **DANN** werden vorher alle abgelaufenen Sessions gelöscht

Quelle: `backend/app/auth.py:18`, `backend/app/auth.py:93`, `backend/app/main.py:186`, `backend/app/db.py:556`, `backend/app/db.py:563`

### Requirement: Logout
`POST /api/auth/logout` MUSS ohne Authentifizierungspflicht funktionieren, die übergebene Session
serverseitig löschen (falls vorhanden) und das Cookie entfernen; Antwort immer `{ok: true}`. **[Muss]**

#### Szenario: Logout
- **WENN** ein angemeldeter Client `/logout` aufruft
- **DANN** ist das Token ungültig und weitere Requests mit ihm erhalten 401

Quelle: `backend/app/main.py:193`

### Requirement: Zweiter Faktor ist Pflicht für jede Route
Jede Route außer der Allowlist MUSS für eine Session, deren Konto keinen aktiven zweiten Faktor hat,
mit 403 und Header `X-HomeAtlas-MFA: enrollment-required` antworten (Detail „Bitte zuerst die
Zwei-Faktor-Anmeldung einrichten.“). Allowlist (nur gültige Session nötig): `GET /api/auth/me`,
`POST /api/auth/logout` (gar keine Session nötig), `POST /api/auth/mfa/setup`,
`POST /api/auth/mfa/confirm`. Ohne Login erreichbar: `POST /api/auth/login`, `GET /api/health`.
Die Regel MUSS an genau einer zentralen Stelle durchgesetzt werden, nicht pro Route. Gilt für ADMIN
und MEMBER gleich. **[Muss]**

#### Szenario: Nicht eingerichteter Benutzer ruft Inventar ab
- **WENN** Session gültig, `totpEnabled` = false, Aufruf einer beliebigen anderen `/api/*`-Route
- **DANN** 403 mit `X-HomeAtlas-MFA: enrollment-required`

#### Szenario: Frontend reagiert auf Reset an anderer Stelle
- **WENN** eine API-Antwort den Header `X-HomeAtlas-MFA: enrollment-required` trägt
- **DANN** lädt die Oberfläche neu und zeigt die MFA-Einrichtung

Quelle: `backend/app/main.py:77`, `backend/app/main.py:88`, `frontend/src/lib/api.ts:28`

### Requirement: TOTP-Einrichtung
`POST /api/auth/mfa/setup` MUSS für ein Konto ohne aktiven Faktor ein neues Geheimnis erzeugen,
verschlüsselt speichern (noch nicht aktiv) und `{secret, uri, qrSvg}` zurückgeben. Erst
`POST /api/auth/mfa/confirm` mit gültigem Code DARF den Faktor aktivieren; ein abgebrochenes Setup
darf niemanden aussperren. Ist der Faktor schon aktiv, MUSS `setup` mit 400 („… bereits aktiv.“)
ablehnen. **[Muss]**

Parameter (RFC 6238): 20 Byte Zufall, Base32 ohne Padding; SHA1, 6 Ziffern, 30 s Periode; Toleranz
±1 Zeitschritt; Leerzeichen im Code werden entfernt, sonst muss er genau `\d{6}` sein; Vergleich
konstantzeitig. URI: `otpauth://totp/HomeAtlas:<username>?secret=…&issuer=HomeAtlas&algorithm=SHA1&digits=6&period=30`.
QR als eigenständiges SVG; ist die QR-Bibliothek nicht vorhanden, ist `qrSvg` leer und die UI zeigt
nur den Schlüssel zum Abtippen. **[Muss]** (QR-Erzeugung: **[Impl]**)

#### Szenario: Bestätigung ohne vorheriges Setup
- **WENN** `confirm` ohne gespeichertes Geheimnis aufgerufen wird
- **DANN** 400 „Bitte zuerst die Einrichtung starten.“

#### Szenario: Falscher Bestätigungscode
- **WENN** der Code nicht passt
- **DANN** 400 „Der Code stimmt nicht. …“, `totpEnabled` bleibt false

#### Szenario: Erfolgreiche Aktivierung
- **WENN** der Code zum gespeicherten Geheimnis passt
- **DANN** `totpEnabled` = true, Protokolleintrag `mfa.enable`, Antwort `{ok: true}`

#### Szenario: Setup erneut starten
- **WENN** `setup` vor der Bestätigung zweimal aufgerufen wird
- **DANN** gilt nur das zuletzt erzeugte Geheimnis

Quelle: `backend/app/main.py:245`, `backend/app/main.py:257`, `backend/app/security.py:102`, `backend/app/security.py:120`, `backend/app/security.py:137`, `backend/app/security.py:144`, Test: `frontend/e2e/smoke.spec.ts::login, MFA enrollment, setup and main routes render without errors`

### Requirement: Keine Selbstabschaltung des zweiten Faktors
Es DARF keinen Weg geben, mit dem ein Benutzer seinen eigenen aktiven Faktor abschaltet. Entfernen
kann ihn nur ein ADMIN (Route) oder die CLI. **[Muss]**

#### Szenario: Gestohlenes Passwort
- **WENN** jemand nur das Passwort kennt
- **DANN** kann er den Faktor weder abschalten noch neu einrichten

Quelle: `backend/app/main.py:234`, `backend/app/main.py:249`

### Requirement: Passwortrichtlinie
Neue Passwörter (Selbstwechsel, Anlage, Admin-Reset) MÜSSEN folgende Prüfung in dieser Reihenfolge
bestehen; jede Ablehnung liefert einen deutschen, handlungsleitenden Satz (HTTP 400):
1. Unicode-NFKC-normalisiert ≥ 10 Zeichen.
2. Nicht nur Leerzeichen.
3. Nicht (kleingeschrieben) in einer festen Liste von 20 offensichtlichen Passwörtern
   (`passwort`, `password`, `geheim`, `1234567890`, `administrator`, `homeatlas`, `willkommen`,
   `sonnenschein`, …).
4. Enthält nicht den Benutzernamen (case-insensitiv), sofern dieser ≥ 3 Zeichen lang ist.
5. Ab 20 Zeichen: akzeptiert (Passphrase), keine weiteren Regeln.
6. Sonst mindestens 3 der 4 Klassen: Kleinbuchstaben (inkl. äöüß), Großbuchstaben (inkl. ÄÖÜ),
   Ziffern, Sonderzeichen (`[^\w\s]`).
7. Nicht nur ein wiederholtes Zeichen.
8. Keine der Folgen `abcdef`, `qwertz`, `qwerty`, `123456`, `987654` (case-insensitiv).

Ein Längenlimit im Request-Schema DARF die Richtlinie nicht vorwegnehmen (sonst kommt ein
technischer 422 statt des Satzes). **[Muss]**

#### Szenario: Zu kurz
- **WENN** das neue Passwort 9 Zeichen hat
- **DANN** 400 „Das Passwort ist zu kurz. Es braucht mindestens 10 Zeichen …“

#### Szenario: Lange Passphrase
- **WENN** das Passwort `keller sicherung blau zwölf` lautet (≥ 20, nur Kleinbuchstaben)
- **DANN** akzeptiert

#### Szenario: Zu einfach
- **WENN** `abcdefghij` (10 Zeichen, nur Kleinbuchstaben)
- **DANN** 400 „Das Passwort ist zu einfach. …“

Quelle: `backend/app/security.py:23`, `backend/app/security.py:26`, `backend/app/security.py:30`, `backend/app/security.py:50`, `backend/app/main.py:206`

### Requirement: Richtlinie abfragbar
`GET /api/auth/password-policy` MUSS `{minLength: 10, passphraseLength: 20, rules: [4 deutsche
Sätze]}` liefern; die UI zeigt die Regeln im Passwortwechsel-Formular. **[Muss]**

#### Szenario: Abruf
- **WENN** ein eingerichteter Benutzer die Route aufruft
- **DANN** erhält er die Richtlinie; ohne MFA-Einrichtung 403

Quelle: `backend/app/main.py:228`, `backend/app/security.py:85`

### Requirement: Eigenes Passwort ändern
`POST /api/auth/password` mit `{currentPassword, newPassword}` MUSS das aktuelle Passwort prüfen
(ohne zweiten Faktor) und dann die Richtlinie. Falsches aktuelles Passwort → 400 „Das aktuelle
Passwort stimmt nicht.“ + Protokoll `password.change` ok=false. Erfolg → `{ok: true}` + Protokoll
`password.change`. Bestehende Sessions bleiben gültig. **[Muss]**

#### Szenario: Falsches aktuelles Passwort
- **WENN** `currentPassword` falsch
- **DANN** 400, Protokolleintrag mit `ok = 0`, Detail „aktuelles Passwort falsch“

#### Szenario: Neues Passwort verletzt Richtlinie
- **WENN** aktuelles Passwort korrekt, neues zu schwach
- **DANN** 400 mit Richtlinien-Satz, kein Protokolleintrag

Quelle: `backend/app/auth.py:112`, `backend/app/main.py:213`

### Requirement: Benutzerverwaltung (ADMIN)
ADMIN MUSS Benutzer auflisten, anlegen, ändern und löschen können:
- **Liste** (`GET /api/users`): öffentliche Felder `id, username, role, displayName, totpEnabled,
  createdAt`, sortiert nach Anlagezeit. Hash, Salz, TOTP-Geheimnis nie.
- **Anlegen** (`POST /api/users`, `{username (≥1 Zeichen), password, role = MEMBER, displayName = ""}`):
  Name schon vergeben → 409 „Diesen Benutzernamen gibt es schon.“; Richtlinie gegen Passwort und
  Benutzernamen → 400; unbekannte Rolle wird stillschweigend zu MEMBER; leerer Anzeigename wird zum
  Benutzernamen; neuer Benutzer hat keinen Faktor; Protokoll `user.create` „<name> als <Rolle>“.
- **Ändern** (`PATCH /api/users/{id}`, `{displayName?, role?, newPassword?}`): 404 wenn unbekannt;
  unbekannte Rolle → 400 „Unbekannte Rolle.“; `newPassword` (nicht leer) wird gegen Richtlinie
  geprüft, gesetzt, und ALLE Sessions des Ziels werden beendet; Antwort `{user, changes[]}`
  (deutsche Änderungsliste); Protokoll `user.update` „<name>: <Änderungen>“ nur bei Änderungen.
- **Löschen** (`DELETE /api/users/{id}`): eigenes Konto → 400; entfernt Benutzer und dessen
  Sessions; Antwort `{ok: true}`. **[Muss]**

#### Szenario: Doppelter Benutzername
- **WENN** ADMIN legt `anna` an, obwohl `anna` existiert
- **DANN** 409

#### Szenario: Admin-Reset des Passworts
- **WENN** ADMIN setzt per PATCH `newPassword` für Benutzer X
- **DANN** X ist auf allen Geräten abgemeldet, `changes` enthält „Passwort zurückgesetzt, offene Sitzungen beendet“

#### Szenario: Eigenes Konto löschen
- **WENN** ADMIN löscht sich selbst
- **DANN** 400 „Das eigene Konto lässt sich nicht löschen.“

#### Szenario: MEMBER versucht Verwaltung
- **WENN** MEMBER ruft eine `/api/users*`-Route auf
- **DANN** 403 „Dafür werden Administratorrechte benötigt.“

Quelle: `backend/app/main.py:271`, `backend/app/main.py:283`, `backend/app/main.py:306`, `backend/app/main.py:350`, `backend/app/db.py:488`, `backend/app/db.py:515`, `backend/app/db.py:550`

### Requirement: Mindestens ein Administrator
Das System MUSS verhindern, dass die Instanz ohne ADMIN endet: der letzte ADMIN darf weder herabgestuft
(400 „Der letzte Administrator kann die Rolle nicht abgeben.“) noch gelöscht werden (400 „Der letzte
Administrator lässt sich nicht löschen.“). **[Muss]**

#### Szenario: Letzten Admin herabstufen
- **WENN** genau ein ADMIN existiert und PATCH setzt seine Rolle auf MEMBER
- **DANN** 400, Rolle bleibt ADMIN

Quelle: `backend/app/main.py:324`, `backend/app/main.py:354`

### Requirement: MFA-Reset durch Admin
`POST /api/users/{id}/mfa/reset` MUSS das TOTP-Geheimnis löschen und `totpEnabled` = false setzen
(404 wenn unbekannt), Protokoll `mfa.reset` mit Zielname. Offene Sessions des Ziels werden nicht
gelöscht, sind aber sofort auf die Einrichtungs-Allowlist beschränkt; beim nächsten Request muss der
Benutzer neu einrichten. **[Muss]**

#### Szenario: Telefon verloren
- **WENN** ADMIN setzt den Faktor von X zurück
- **DANN** X kann sich mit Passwort anmelden und muss sofort neu einrichten; eine offene Session von X erhält bei der nächsten Aktion 403 `enrollment-required`

Quelle: `backend/app/main.py:363`

### Requirement: Zugriffsprotokoll
Das System MUSS sicherheitsrelevante Ereignisse mit Zeitpunkt (UTC), Benutzer-ID, Benutzername,
Aktion, Detail, Client-IP, User-Agent und Erfolg speichern. Mindestens: `login` (Erfolg/Fehlschlag),
`login.mfa` (Code angefordert/falsch, ok=false), `password.change`, `mfa.enable`, `mfa.reset`,
`user.create`, `user.update`; außerdem Aktionen anderer Fähigkeiten (`secret.reveal`, `scan.start`,
`console.*.open/close`, `sshkey.*`, `switch.*`, `system.reboot`). Fehlgeschlagene Logins werden mit dem
eingegebenen (ggf. nicht existenten) Benutzernamen protokolliert. Client-IP aus `X-Real-IP` des
vorgeschalteten Proxys, sonst Peer-Adresse. Aufbewahrung: die neuesten 5000 Einträge; Kürzung Detail
500, IP 60, User-Agent 200 Zeichen. **[Muss]** (Grenzen: **[Impl]**)

`GET /api/access-log?limit=200&action=&onlyFailures=false` (ADMIN) MUSS `{entries, actions}` liefern:
neueste zuerst, `limit` auf 1–1000 begrenzt, `action` exakter Filter, `onlyFailures` nur `ok = 0`;
`actions` = alle vorkommenden Aktionsnamen sortiert. **[Muss]**

#### Szenario: Fehlversuche filtern
- **WENN** ADMIN ruft `/api/access-log?onlyFailures=true&limit=5000` auf
- **DANN** höchstens 1000 Einträge, alle mit `ok = 0`, neueste zuerst

#### Szenario: Rotation
- **WENN** der 5001. Eintrag geschrieben wird
- **DANN** wird der älteste gelöscht

Quelle: `backend/app/db.py:1846`, `backend/app/db.py:1849`, `backend/app/db.py:1865`, `backend/app/main.py:109`, `backend/app/main.py:1550`

### Requirement: WebSocket-Authentifizierung
WebSocket-Routen (interaktive Konsolen, siehe [remote-admin](../remote-admin/spec.md)) MÜSSEN vor dem
Annehmen prüfen: (a) ist ein `Origin`-Header vorhanden, muss dessen Hostname exakt dem Hostnamen aus
`Host` entsprechen (Port wird ignoriert, weil Proxys ihn entfernen); (b) gültige Session-Cookie;
(c) `totpEnabled`; (d) Rolle ADMIN. Fehlschlag → Verbindung mit Code 1008 schließen, ohne Details.
Fehlender `Origin` wird akzeptiert. **[Muss]**

#### Szenario: Fremde Origin
- **WENN** `Origin: http://evil.example` bei `Host: homeatlas.lan:8280`
- **DANN** Close 1008

#### Szenario: MEMBER öffnet Konsole
- **WENN** gültige MEMBER-Session mit MFA
- **DANN** Close 1008

Quelle: `backend/app/main.py:121`, `backend/app/main.py:801`

### Requirement: Rollen-Gating in der Oberfläche
Die UI MUSS die Reihenfolge Login → MFA-Einrichtung → (nur ADMIN, wenn Setup offen) Setup-Wizard →
App erzwingen; Admin-Seiten „Benutzer“ (`/benutzer`) und „Protokoll“ (`/protokoll`) sind für MEMBER
weder in der Navigation noch als Route vorhanden. Die Backend-Prüfung bleibt unabhängig davon
maßgeblich. **[Muss]**

#### Szenario: MEMBER öffnet `/benutzer`
- **WENN** MEMBER navigiert direkt zu `/benutzer`
- **DANN** Weiterleitung auf `/`

Quelle: `frontend/src/App.tsx:87`, `frontend/src/App.tsx:94`, `frontend/src/App.tsx:152`

### Requirement: Notfall-Wiederherstellung per Kommandozeile
Mit Shell-Zugriff auf den Backend-Container MUSS es möglich sein, ohne laufende Web-Sitzung:
- ohne Argumente alle Benutzer mit Rolle und MFA-Status aufzulisten;
- `<benutzer> <passwort>`: Passwort setzen; existiert der Benutzer nicht, wird er als ADMIN angelegt;
- `<benutzer> --reset-mfa`: Faktor entfernen, ALLE Sessions des Benutzers beenden, Protokoll
  `mfa.reset` mit Akteur „(Kommandozeile)“;
- beides kombiniert.
Ein reiner Passwort-Reset DARF den Faktor nicht entfernen (getrennte Ereignisse) und beendet keine
Sessions. Unbekannte `--`-Option oder falsche Argumentzahl → Exit 2 mit Aufrufhinweis; `--reset-mfa`
für unbekannten Benutzer ohne Passwort → Exit 1. **[Muss]** (Aufruf `python -m app.reset_password`: **[Impl]**)

#### Szenario: Erstpasswort verloren
- **WENN** `reset_password admin NeuesPasswort42!` ausgeführt wird
- **DANN** Passwort geändert, Faktor bleibt, Hinweis „Der zweite Faktor bleibt aktiv …“

#### Szenario: Handy des einzigen Admins verloren
- **WENN** `reset_password admin --reset-mfa`
- **DANN** Faktor entfernt, offene Sessions beendet, nächster Login führt in die Einrichtung

Quelle: `backend/app/reset_password.py:40`, `backend/app/reset_password.py:73`, `backend/app/reset_password.py:84`, `backend/app/reset_password.py:99`

## Daten

Aus [data-model](../../contracts/data-model.md):
- `users`: `id`, `username` (eindeutig, case-sensitiv), `passwordHash`, `salt`, `role` (`ADMIN`|`MEMBER`),
  `displayName`, `totpSecretEnc` (verschlüsselt, siehe [zugangsdaten](../zugangsdaten/spec.md)),
  `totpEnabled` (0/1), `createdAt`. Öffentlich nur `id, username, role, displayName, totpEnabled, createdAt`.
- `sessions`: `token`, `userId`, `expiresAt` (geschrieben/gelöscht).
- `accessLog`: alle Felder (geschrieben, gelesen).
- `settings`: keine eigenen Keys; `GET /api/health` liest `setupCompleted` (siehe
  [setup-wizard](../setup-wizard/spec.md)).

## Schnittstellen

| Methode | Pfad | Rolle | Zweck |
|---|---|---|---|
| POST | /api/auth/login | öffentlich | Anmelden (Passwort + ggf. TOTP), setzt Session-Cookie |
| POST | /api/auth/logout | öffentlich | Session löschen, Cookie entfernen |
| GET | /api/auth/me | Session (ohne MFA-Pflicht) | Aktueller Benutzer inkl. `totpEnabled` |
| POST | /api/auth/mfa/setup | Session (ohne MFA-Pflicht) | Neues TOTP-Geheimnis + QR erzeugen |
| POST | /api/auth/mfa/confirm | Session (ohne MFA-Pflicht) | Code prüfen, Faktor aktivieren |
| POST | /api/auth/password | ADMIN, MEMBER | Eigenes Passwort ändern |
| GET | /api/auth/password-policy | ADMIN, MEMBER | Passwortrichtlinie |
| GET | /api/users | ADMIN | Benutzer auflisten |
| POST | /api/users | ADMIN | Benutzer anlegen |
| PATCH | /api/users/{user_id} | ADMIN | Anzeigename, Rolle, Passwort-Reset |
| DELETE | /api/users/{user_id} | ADMIN | Benutzer löschen |
| POST | /api/users/{user_id}/mfa/reset | ADMIN | Zweiten Faktor zurücksetzen |
| GET | /api/access-log | ADMIN | Zugriffsprotokoll lesen |

„ADMIN, MEMBER“ heißt hier immer: gültige Session UND aktiver zweiter Faktor. Fehlende Session → 401
„Nicht angemeldet.“; fehlende Admin-Rolle → 403. WebSocket-Regel: siehe Requirement oben; die
Konsolen-Routen selbst gehören zu [remote-admin](../remote-admin/spec.md).

UI-Seite(n): `frontend/src/pages/LoginPage.tsx` (ohne Session, jede Route),
`frontend/src/pages/MfaEnrollPage.tsx` (solange `totpEnabled` false, jede Route),
`frontend/src/pages/UsersPage.tsx` (Route `/benutzer`, ADMIN), `frontend/src/pages/AccessLogPage.tsx`
(Route `/protokoll`, ADMIN), Passwortwechsel + MFA-Status in `frontend/src/pages/SettingsPage.tsx`
(Route `/einstellungen`, Reiter „Konto“), Gating in `frontend/src/App.tsx`.

## Nicht-Ziele und Grenzen

- Kein Rate-Limiting, keine Kontosperre nach Fehlversuchen, kein CAPTCHA (weder Backend noch nginx).
- Keine Selbstregistrierung, kein „Passwort vergessen“ per E-Mail, keine SSO/OIDC/LDAP.
- Kein Selbst-Abschalten des zweiten Faktors, keine Backup-/Recovery-Codes, kein WebAuthn.
- Keine feingranularen Rechte über ADMIN/MEMBER hinaus.
- Kein HTTPS; TLS ist Aufgabe eines vorgeschalteten Reverse Proxys.
- Ausnahme vom Read-only-Prinzip für MEMBER: das Assistenten-Werkzeug `set_switch` (siehe
  [assistent-chat-und-mcp](../assistent-chat-und-mcp/spec.md)); MCP-Token-Auth gehört ebenfalls dorthin.

## Ist-Implementierung (nur Referenz, [Impl])

- Abhängigkeitskette FastAPI: `session_user` (nur Session) → `current_user` (+ `totpEnabled`) →
  `require_admin` (+ Rolle). `backend/app/main.py:77`–`106`.
- Session-Tokens liegen im Klartext in der DB (Begründung in `db.py`-Schemakommentar zu `apiTokens`).
- Login-Fehlerunterscheidung über Exception `MfaRequired(wrong_code)`; Frontend erkennt den Fall nur am
  Header `X-HomeAtlas-MFA: required` (`frontend/src/pages/LoginPage.tsx:22`).
- Die Richtlinie prüft den NFKC-normalisierten Text, gehasht wird der unnormalisierte.
- Regel 7 (ein wiederholtes Zeichen) ist praktisch unerreichbar, weil Regel 6 vorher greift; die
  zweite Hälfte der `_OBVIOUS`-Bedingung (`security.py:64`) ist redundant.
- `auth.verify_password` (`backend/app/auth.py:83`) wird nirgends aufgerufen.
- Erst-Admin-Passwort wird über `logger.warning` mit `=`-Rahmen geloggt (`backend/app/main.py:49`).
- Frontend: Login-Code-Feld erscheint erst nach dem ersten 401 mit MFA-Header, Eingabe nur Ziffern,
  max. 6; Absenden erst bei 6 Ziffern.

## OFFEN

- > OFFEN: `DELETE /api/users/{id}` schreibt keinen Protokolleintrag, obwohl die AccessLogPage ein Label `user.delete` kennt und README „Benutzeränderungen“ als protokolliert nennt (wirkt wie Bug).
- > OFFEN: `DELETE /api/users/{id}` antwortet für unbekannte IDs mit `{ok: true}` statt 404 (PATCH/mfa-reset liefern 404).
- > OFFEN: PATCH `/api/users/{id}` ist nicht atomar: Anzeigename/Rolle werden gespeichert, bevor ein zu schwaches `newPassword` mit 400 abgelehnt wird.
- > OFFEN: POST `/api/users` mappt unbekannte Rollen still auf MEMBER, PATCH antwortet 400 – uneinheitlich.
- > OFFEN: Eigener Passwortwechsel beendet keine anderen Sessions (Admin-Reset schon) – gewollt?
- > OFFEN: Admin-MFA-Reset beendet keine Sessions, die CLI-Variante schon; eine offene Session des Ziels kann den Faktor danach selbst neu einrichten (nur Passwort-Besitz war nötig für die Session, ist aber u. U. ein Angreifer).
- > OFFEN: Ein Konto ohne aktiven Faktor (neu angelegt oder nach Reset) kann von jedem mit dem Passwort eingerichtet werden – bewusste Abwägung laut `reset_password.py`-Docstring, aber ohne Ablaufzeit.
- > OFFEN: Initial-Admin via `ADMIN_PASSWORD` und CLI-Passwortreset umgehen die Richtlinie (CLI prüft nur ≥ 8 Zeichen; README-Beispiel `devpass123` erfüllt sie nicht).
- > OFFEN: UsersPage zeigt „Mindestens 8 Zeichen“ und aktiviert „Anlegen“ ab 8 Zeichen, Richtlinie verlangt 10.
- > OFFEN: AccessLogPage kennt Label `mfa.disable` (nie geschrieben), aber keines für `mfa.reset`; `mfa.reset` ist auch nicht als kritisch markiert.
- > OFFEN: Session-Cookie ohne `Secure`-Flag, auch hinter TLS-Proxy.
- > OFFEN: `X-Real-IP` wird ungeprüft übernommen; sicher nur, solange das Backend ausschließlich über nginx erreichbar ist (ADR-0003).
- > OFFEN: Benutzernamen sind case-sensitiv und werden weder getrimmt noch validiert (außer ≥ 1 Zeichen).
- > OFFEN: Selbst-Herabstufung eines ADMIN ist erlaubt, solange ein weiterer ADMIN existiert; die eigene UI-Ansicht bleibt bis zum Reload Admin.
- > OFFEN: WebSocket-Check akzeptiert fehlenden `Origin`-Header; Docstring nennt die Bedingung „same bar as current_user“, prüft aber zusätzlich ADMIN.
- > OFFEN: `GET /api/health` ist unauthentifiziert und verrät `userCount`; das Frontend nutzt das Feld nicht.
