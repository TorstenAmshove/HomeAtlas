# Zugangsdaten

> Status: Ist-Verhalten, aus dem Code zurückgewonnen (Stand 0159807). Quellen als `datei:zeile`.

## Zweck

Ein Haushalt legt die Zugänge zu seiner Technik (Router, NAS, Switches, Provider-Kundenkonto,
WLAN, API-Tokens, SSH-Schlüssel) an einer Stelle ab, damit man im Störungsfall drankommt. Die
Secrets liegen verschlüsselt, verlassen den Server nur einzeln auf ausdrückliche Admin-Anfrage
und erscheinen nie in Dokumentation, Chat oder LLM-Kontext. Ein Zugang kann einem oder mehreren
Geräten (auch ganzen Gerätetypen/Subnetzen) zugeordnet und optional fürs lesende Auslesen
freigegeben werden. HomeAtlas kann zudem SSH-Schlüssel erzeugen und auf Geräten hinterlegen.

## Rollen und Rechte

| Aktion | ADMIN | MEMBER |
|---|---|---|
| Zugänge auflisten, anlegen, ändern, löschen | ja | nein |
| Secret eines Zugangs im Klartext abrufen | ja (einzeln, protokolliert) | nein |
| Zuordnungen lesen/ersetzen | ja | nein |
| SSH-Schlüssel erzeugen / auf Gerät einspielen | ja | nein |
| Metadaten der Zugänge eines Geräts sehen (Bezeichnung, Kategorie, Benutzer, URL, Notiz, `hasSecret`) über Geräteansicht/Doku/Assistent | ja | ja |
| Ein Secret, eine Passphrase oder einen Chiffretext sehen | nur über Abruf-Route | nie |

## Anforderungen

### Requirement: Verwaltung nur durch Admins
Das System MUSS alle Routen zum Auflisten, Anlegen, Ändern, Löschen, Abrufen, Zuordnen,
Schlüsselerzeugen und Ausrollen ausschließlich ADMIN-Konten (mit abgeschlossener MFA) erlauben;
die Seite „Zugänge“ ist nur für Admins erreichbar. **[Muss]**

#### Szenario: MEMBER ruft Zugangsliste ab
- **WENN** ein MEMBER `GET /api/accounts` aufruft
- **DANN** wird die Anfrage abgewiesen (403)

Quelle: `backend/app/main.py:647`, `backend/app/main.py:102`, `frontend/src/App.tsx:145`

### Requirement: Zugang anlegen
Das System MUSS einen Zugang mit den Feldern Gerät (`systemId`, optional), Bezeichnung (Default
„Zugang“), Kategorie (Default `login`), Benutzername, Secret, Passphrase, URL, Notiz, Freigabe
`allowProbe` (Default aus) und Port (Default 0 = Standardport) anlegen. Secret und Passphrase
MÜSSEN vor dem Speichern verschlüsselt werden; leere Werte werden als leer gespeichert. Die
Antwort enthält den Zugang ohne Secret/Passphrase/Chiffretext, dafür `hasSecret`/`hasPassphrase`. **[Muss]**

#### Szenario: Anlegen mit Passwort
- **WENN** ein Admin einen Zugang mit Secret „geheim“ anlegt
- **DANN** enthält die Antwort `hasSecret: true` und weder „geheim“ noch `secretEnc`

Quelle: `backend/app/main.py:656`, `backend/app/main.py:619`, `backend/app/db.py:1369`

### Requirement: Kategorien
Das System MUSS die Kategorien `contract` (Vertrag/Kundenkonto), `login`, `sshkey`, `snmp`,
`omada`, `unifi`, `homeassistant`, `proxmox`, `adguard`, `wifi`, `apikey`, `other` anbieten; die
Kategorie bestimmt die Bedeutung der Felder: `omada` Benutzer = Client-ID, Secret = Client-Secret;
`proxmox` Benutzer = Token-ID (`user@realm!name`), Secret = Token-Secret; `homeassistant` Secret =
Long-Lived-Token; `snmp` Secret = Community; `unifi` Secret = API-Key; `sshkey` Secret = privater
Schlüssel (PEM), Passphrase optional. Bei `omada`/`homeassistant`/`proxmox`/`adguard` ist die URL
Pflicht in der UI. Port ist nur für `sshkey`/`login`/`snmp` relevant. **[Muss]**

#### Szenario: Proxmox-Zugang
- **WENN** ein Admin die Kategorie „Proxmox VE (API-Token)“ wählt
- **DANN** fragt die UI Token-ID, Token-Secret und Adresse ab

Quelle: `frontend/src/pages/zugaenge/AccountFormPage.tsx`

### Requirement: Zugangsliste ohne Secrets
Das System MUSS Admins alle Zugänge sortiert nach Bezeichnung (case-insensitiv) liefern, je Eintrag
alle Felder außer Secret/Passphrase/Chiffretext, plus `hasSecret`, `hasPassphrase` und
`assignmentCount` (Anzahl zusätzlicher Zuordnungen). Keine Route gibt Secrets gesammelt aus. **[Muss]**

#### Szenario: Liste nach Zuordnung
- **WENN** einem Zugang eine Gruppe `kind = network` zugeordnet wurde
- **DANN** zeigt die Liste für ihn `assignmentCount = 1` und kein `secretEnc`/`passphraseEnc`

Quelle: `backend/app/main.py:647`, Test: `backend/tests/test_main_account_assignments_api.py::test_assignment_round_trip`

### Requirement: Zugang ändern ohne Secret-Verlust
Das System MUSS beim Ändern ein leeres Secret und eine leere Passphrase als „unverändert lassen“
behandeln (das Formular erhält gespeicherte Werte nie); nicht-leere Werte werden neu verschlüsselt.
Unbekannte ID → 404 „Zugang nicht gefunden.“ **[Muss]**

#### Szenario: Nur Bezeichnung geändert
- **WENN** ein Admin die Bezeichnung ändert und das Passwortfeld leer lässt
- **DANN** bleibt das gespeicherte Secret erhalten (`hasSecret` bleibt true)

Quelle: `backend/app/main.py:664`

### Requirement: Ändern betrifft nur gesendete Felder
Das System MUSS beim Ändern nur die Felder übernehmen, die der Client sendet; nicht gesendete
Felder bleiben unverändert, insbesondere die Freigabe `allowProbe`. **[Muss]**

#### Szenario: Teil-PATCH
- **WENN** `PATCH /api/accounts/{id}` nur `{"label": "Neu"}` enthält
- **DANN** ändert sich nur die Bezeichnung; Kategorie, Gerät, URL, Notiz, Port und Freigabe bleiben

Quelle: `backend/app/main.py` (`update_account`), Test:
`backend/tests/test_llm_defaults_and_accounts.py::test_partial_patch_keeps_other_fields`

### Requirement: Zugang löschen
Das System MUSS beim Löschen den Zugang und alle seine Zuordnungen entfernen und von ihm
synchronisierte Netzwerkressourcen als inaktiv markieren (Notizen bleiben erhalten). Antwort
`{ok: true}`. **[Muss]**

#### Szenario: Gelöschter Gruppen-Zugang
- **WENN** ein per `kind = router` zugeordneter Zugang gelöscht wird
- **DANN** hat er keine Zuordnungen mehr und erscheint bei keinem Router mehr als Probe-Zugang

Quelle: `backend/app/main.py:691`, `backend/app/db.py:1548`, Test: `backend/tests/test_db_account_assignments.py::test_delete_account_removes_its_assignments`

### Requirement: Secret einzeln abrufen und protokollieren
Das System MUSS das entschlüsselte Secret genau eines Zugangs nur auf ausdrückliche Admin-Anfrage
liefern (`{secret}`) und jeden Abruf im Zugriffsprotokoll festhalten (Aktion `secret.reveal`,
Benutzer, Client-IP, User-Agent, Detail = Bezeichnung). Unbekannte ID → 404 ohne Protokolleintrag.
Lässt sich das Secret nicht entschlüsseln (z. B. Schlüsseldatei ersetzt), antwortet das System mit
409 („Secret nicht lesbar – Schlüsseldatei geändert?“) und protokolliert den Abruf mit `ok=0`. Die Passphrase eines SSH-Schlüssels
wird nie ausgeliefert. **[Muss]**

#### Szenario: Router-Passwort anzeigen
- **WENN** ein Admin bei „Router“ auf „Anzeigen“ klickt
- **DANN** erhält er das Klartext-Passwort, und das Zugriffsprotokoll enthält einen
  `secret.reveal`-Eintrag mit seinem Namen und „Router“

#### Szenario: Secret nicht entschlüsselbar
- **WENN** die Schlüsseldatei nach einer Wiederherstellung fehlt und ein Admin ein Secret anzeigt
- **DANN** erhält er 409, und das Protokoll enthält einen `secret.reveal`-Eintrag mit `ok=0`

Quelle: `backend/app/routes/accounts.py`, `backend/app/crypto.py`

### Requirement: Verschlüsselung at rest
Das System MUSS Secrets, Passphrasen, den Standard-Zugang und gesicherte Gerätekonfigurationen
symmetrisch authentifiziert verschlüsselt speichern. Der Schlüssel liegt als Datei neben der
Datenbank (`HOMEATLAS_KEY_PATH`, Default `/data/secret.key`), wird beim ersten Gebrauch erzeugt und
best effort auf Modus 0600 gesetzt. Schutzziel: verlorene DB-Kopie, nicht root auf dem Host
(ADR 0007). Ein leerer Klartext wird als leerer String gespeichert. **[Muss]** (Verfahren Fernet **[Impl]**)

#### Szenario: Schlüsseldatei fehlt bei vorhandener DB
- **WENN** die Schlüsseldatei ersetzt wurde und ein Secret nicht entschlüsselbar ist
- **DANN** bleiben Inventar, Doku und Zugangsliste nutzbar (`crypto.decrypt` liefert dort ""); jede
  Benutzung des Secrets (Abruf, Probing, Controller-Abfragen, Remote-Admin, KI-Schlüssel,
  `set_switch`) bricht ab (`crypto.decrypt_strict` → `SecretUnreadable`): Abruf/Schreibrouten 409
  mit `ok=0`-Protokoll, Scan überspringt den Zugang mit Warnung, nie mit leerem Passwort

Quelle: `backend/app/crypto.py`, `docs/adr/0007-credentials-fernet-schluessel-im-volume.md`

### Requirement: Primäres Gerät und zusätzliche Zuordnungen
Das System MUSS einem Zugang ein primäres Gerät (`systemId`) und beliebig viele zusätzliche
Zuordnungen geben können: Typ `system` (Geräte-ID), `kind` (Gerätetyp, z. B. `router`) oder
`subnet` (CIDR). Das Setzen ersetzt immer die komplette Liste; Einträge mit unbekanntem Typ, leerem
Wert oder (bei `subnet`) nicht parsebarem CIDR werden stillschweigend verworfen. Die Liste wird
nach (Typ, Wert) sortiert geliefert. Unbekannter Zugang → 404 bei Lesen und Setzen. **[Muss]**

#### Szenario: Ungültige Einträge
- **WENN** ein Admin `[{subnet, "kein-cidr"}, {foo, "x"}, {kind, "router"}]` setzt
- **DANN** wird nur `kind = router` gespeichert

Quelle: `backend/app/main.py:710`, `backend/app/main.py:717`, `backend/app/db.py:1509`, Test: `backend/tests/test_db_account_assignments.py::test_set_account_assignments_drops_unparseable_subnet_and_unknown_type`, `backend/tests/test_db_account_assignments.py::test_set_account_assignments_replaces_the_whole_list`, `backend/tests/test_main_account_assignments_api.py::test_assignments_404_for_unknown_account`

### Requirement: Zuordnungen auflösen
Das System MUSS einen Zugang einem Gerät zurechnen, wenn er direkt daran hängt oder eine Zuordnung
auf die Geräte-ID, den Gerätetyp oder ein Subnetz mit der Geräte-IP zeigt. Fürs Auslesen zählen
nur freigegebene Zugänge (Details [credentialed-probing](../credentialed-probing/spec.md)); für die
Anzeige am Gerät alle, markiert mit `viaAssignment`. **[Muss]**

#### Szenario: Zusätzliches Einzelgerät
- **WENN** ein Zugang von Gerät A zusätzlich per `system`-Zuordnung auf Gerät B zeigt
- **DANN** erscheint er bei B mit `viaAssignment: true`

Quelle: `backend/app/db.py:1408`, `backend/app/db.py:1464`, `backend/app/main.py:551`, Test: `backend/tests/test_db_account_assignments.py::test_list_probe_accounts_includes_directly_assigned_additional_system`

### Requirement: Freigabe fürs Auslesen ist eigenständige Einwilligung
Das System MUSS die Freigabe `allowProbe` je Zugang getrennt speichern (Default aus) und nur fürs
automatische lesende Auslesen auswerten; schreibende Funktionen (SSH-Konsole, Remote-Admin) DÜRFEN
diese Freigabe weder voraussetzen noch als Ersatz für eigene Berechtigungsprüfungen nutzen. **[Muss]**

#### Szenario: Zugang ohne Freigabe
- **WENN** ein `login`-Zugang ohne Freigabe an einem Server hängt
- **DANN** wird er im Scan nicht genutzt, bleibt aber als Ablage sichtbar

Quelle: `backend/app/db.py:228`, `backend/app/main.py:791`

### Requirement: SSH-Schlüssel erzeugen
Das System MUSS Admins für ein Gerät ein neues Ed25519-Schlüsselpaar ohne Passphrase erzeugen und
als Zugang der Kategorie `sshkey` speichern: privater Schlüssel (OpenSSH-PEM) verschlüsselt als
Secret, öffentlicher Schlüssel (`ssh-ed25519 <base64> homeatlas@<Gerätename>`) im Notizfeld,
Benutzer leer, Port 22, Freigabe aus, Bezeichnung aus Anfrage (Default „SSH-Schlüssel
(HomeAtlas)“). Antwort enthält Zugang und `publicKey`; Protokolleintrag `sshkey.generate`.
Unbekanntes Gerät → 404. **[Muss]**

#### Szenario: Schlüssel für NAS
- **WENN** ein Admin für „NAS“ einen Schlüssel erzeugt
- **DANN** existiert ein neuer `sshkey`-Zugang am NAS, dessen Notiz mit `ssh-ed25519 ` beginnt und
  auf `homeatlas@NAS` endet

Quelle: `backend/app/main.py:736`, `backend/app/remote_admin.py:45`

### Requirement: SSH-Schlüssel auf Gerät einspielen
Das System MUSS den öffentlichen Schlüssel eines `sshkey`-Zugangs auf dessen Gerät hinterlegen. Die
Zeile wird aus dem gespeicherten privaten Schlüssel abgeleitet (Kommentar `homeatlas@<Gerätename>`),
nie aus dem editierbaren Notizfeld; ein unlesbarer privater Schlüssel → 400. Angemeldet wird
mit einem anderen, bereits hinterlegten Zugang desselben Geräts. Prüfungen: Schlüssel
fehlt oder ist nicht `sshkey` → 404; Login-Zugang fehlt → 404; anderes Gerät → 400; Schlüssel
ohne Gerät → 400; Gerät ohne IP/Hostname → 400. Die Datei `~/.ssh/authorized_keys` wird gelesen
und die Zeile nur angehängt, wenn sie noch nicht exakt vorhanden ist (idempotent, `changed`);
`~/.ssh` wird bei Bedarf mit 0700 angelegt, die Datei auf 0600 gesetzt; nie überschrieben.
Port = Anfrage, sonst Port des Login-Zugangs, sonst 22. Jeder Versuch wird als `sshkey.deploy`
mit Erfolg/Misserfolg protokolliert; Fehlschlag → 400 mit Fehlermeldung. **[Muss]**

#### Szenario: Schlüssel schon vorhanden
- **WENN** die exakte Zeile bereits in `authorized_keys` steht
- **DANN** antwortet das System `{ok: true, changed: false}` und schreibt nichts

Quelle: `backend/app/main.py:761`, `backend/app/remote_admin.py:111`, `remote_admin.public_line_for`, Test:
`backend/tests/test_llm_defaults_and_accounts.py::test_deploy_ignores_edited_notes`

### Requirement: Secrets nie in Dokumentation, Chat oder LLM-Kontext
Das System MUSS Secrets und Passphrasen aus allen Ausgaben außer der Einzelabruf-Route fernhalten:
Geräteansicht (nur `hasSecret`/`hasPassphrase`), generierte Doku (Tabelle mit Bezeichnung, Art,
Benutzer, Gerät, Adresse, „Passwort hinterlegt ja/nein“), LLM-Werkzeug `list_accounts` (id,
Bezeichnung, Kategorie, Benutzer, URL, Notiz, Gerät, `hasSecret`) und Fehlermeldungen von Probes. **[Muss]**

#### Szenario: Assistent nach Router-Passwort gefragt
- **WENN** ein Nutzer im Chat nach dem Router-Passwort fragt
- **DANN** kann der Assistent nur sagen, wo der Zugang hinterlegt ist; das Werkzeug liefert
  „Passwörter werden hier bewusst nicht ausgegeben.“

Quelle: `backend/app/tools.py:316`, `backend/app/docs.py:355`, `backend/app/main.py:546`, Test: `backend/tests/test_unifi_probe.py::test_probe_reports_authentication_failure_without_echoing_api_key`

### Requirement: Zugänge folgen dem Gerät
Das System MUSS beim Löschen eines Geräts dessen direkt angehängte Zugänge samt deren Zuordnungen
und alle `system`-Zuordnungen auf dieses Gerät löschen, über die API aber nur mit
`?withAccounts=true` (sonst 409 mit der Anzahl, nichts wird gelöscht); beim Zusammenführen zweier Geräte werden
Zugänge und `system`-Zuordnungen auf das verbleibende Gerät umgehängt. **[Muss]**

#### Szenario: Gerät gelöscht
- **WENN** Gerät A mit eigenem Zugang gelöscht wird und ein fremder Zugang per `system` auf A zeigte
- **DANN** ist As Zugang gelöscht und die Zuordnung des fremden Zugangs entfernt

Quelle: `backend/app/db.py:692`, `backend/app/db.py:885`, Test: `backend/tests/test_db_account_assignments.py::test_delete_system_removes_assignments_targeting_it_and_owned_by_its_accounts`

### Requirement: Zugänge: Liste und Formular
`/zugaenge` (nur ADMIN) MUSS eine ruhige Liste mit Suche in `?q=`
zeigen (dieselben Felder wie bisher: Bezeichnung, Benutzername, Adresse, Notiz, Gerätename).
„Neuer Zugang“ und Bearbeiten MÜSSEN eigene Routen sein (`/zugaenge/neu`, `/zugaenge/:id`, beide nur
ADMIN). Das Formular MUSS einen
Entwurf im `sessionStorage` halten (Schlüssel `homeatlas.draft.account.form.<id|neu>`) und vor dem
Verlassen mit ungespeicherten Änderungen fragen; die Secret-Felder (Passwort/Token/privater Schlüssel,
Passphrase) DÜRFEN NIE in einen Speicher oder die URL geschrieben werden, gespeichert wird nur, *dass*
etwas eingetippt war, und das Formular bittet nach dem Wiederherstellen um erneute Eingabe. „Anzeigen“
holt ein Secret einzeln über `GET /api/accounts/{id}/secret` und verbirgt es nach 30 s wieder.
Löschen MUSS über einen Prüfdialog laufen, der den Verlust des gespeicherten Passworts, das Gerät und
alle Zuordnungen nennt, die den Zugang verlieren, und sagt, dass es kein Rückgängig gibt. Der Hinweis
„kein Passwort-Manager“ erscheint einmal und danach hinter „ⓘ“ (gemerkt im `localStorage`).
SSH-Schlüssel erzeugen, Schlüssel auf Gerät einspielen (mit Prüfdialog) und Zuordnungen bleiben
erreichbar. „Art“ MUSS das erste Feld des Formulars sein; Beschriftungen, Platzhalter, Hinweise und
Sichtbarkeit der Felder (Benutzername, Adresse, Port, „zum Auslesen verwenden“) MÜSSEN je Art aus einer
zentralen Definition kommen (`categoryFields.ts`, ein `Record` über alle Arten, sodass der Build bei
einer fehlenden Art scheitert). Ausgeblendete Felder DÜRFEN beim Bearbeiten gespeicherte Werte nicht
überschreiben (sie werden nicht gesendet). Bei Cloudflare (Zone-ID in `url`, Account-ID in `username`)
MUSS das Formular vor dem Speichern 32 Zeichen `0-9a-f` prüfen (Account-ID optional).
Datenmodell und API bleiben unverändert. **[Muss]** (Texte und Aufteilung **[Impl]**)

#### Szenario: Cloudflare-Zone-ID ungültig
- **WENN** ein ADMIN bei „Art“ Cloudflare wählt und eine Zone-ID ohne 32 Hex-Zeichen einträgt
- **DANN** zeigt das Formular eine Fehlermeldung und sendet nichts an die API

#### Szenario: Entwurf ohne Passwort
- **WENN** ein ADMIN in „Neuer Zugang“ Bezeichnung und Passwort eintippt und Zurück drückt
- **DANN** steht im `sessionStorage` die Bezeichnung, aber nicht das Passwort, und Vorwärts zeigt die
  Bezeichnung mit leerem Passwortfeld und dem Hinweis, es erneut einzugeben

#### Szenario: Löschen abbrechen
- **WENN** ein ADMIN „Löschen …“ wählt und im Prüfdialog „Abbrechen“ klickt
- **DANN** bleibt der Zugang unverändert

Quelle: `frontend/src/pages/zugaenge/AccountsPage.tsx`, `frontend/src/pages/zugaenge/AccountFormPage.tsx`, `frontend/src/pages/zugaenge/categoryFields.ts`,
`frontend/src/pages/zugaenge/accountDraft.ts`, `frontend/src/pages/zugaenge/DeleteAccountDialog.tsx`,
`frontend/src/lib/useRevealedSecrets.ts`

### Requirement: Standard-Zugang maskiert verwalten
Das System MUSS das globale Standard-SSH-Secret und dessen Passphrase verschlüsselt in den
Einstellungen speichern, sie nie (auch nicht als Chiffretext) ausliefern, sondern nur
`hasDefaultCredentialSecret`/`hasDefaultCredentialPassphrase`; ein leerer Wert beim Speichern lässt
den gespeicherten Wert unverändert. **[Muss]**

#### Szenario: Einstellungen speichern ohne Secret
- **WENN** ein Admin eine andere Einstellung ändert und das Feld leer lässt
- **DANN** bleibt der Standard-Zugang erhalten

Quelle: `backend/app/main.py:386`, `backend/app/main.py:404`

## Daten

Siehe [data-model](../../contracts/data-model.md).
- `accounts`: id, systemId, label, category, username, secretEnc, passphraseEnc, url, notes,
  allowProbe (0/1), port, updatedAt – gelesen/geschrieben.
- `accountAssignments`: id, accountId, targetType (`system`|`kind`|`subnet`), targetValue,
  createdAt – gelesen/geschrieben (Replace-all).
- `networkResources.active` – beim Löschen eines Zugangs auf 0.
- `accessLog` – Aktionen `secret.reveal`, `sshkey.generate`, `sshkey.deploy`.
- `settings`: `defaultCredentialEnabled`, `defaultCredentialUsername`, `defaultCredentialIsKey`,
  `defaultCredentialSecretEnc`, `defaultCredentialPassphraseEnc`, `defaultCredentialPort`
  (Pflege über [einstellungen-und-llm-provider](../einstellungen-und-llm-provider/spec.md)).
- Schlüsseldatei (`HOMEATLAS_KEY_PATH`), muss zusammen mit der DB gesichert werden.

## Schnittstellen

| Methode | Pfad | Rolle | Zweck |
|---|---|---|---|
| GET | /api/accounts | ADMIN | Alle Zugänge ohne Secrets, mit `assignmentCount` |
| POST | /api/accounts | ADMIN | Zugang anlegen (Secret/Passphrase verschlüsselt) |
| PATCH | /api/accounts/{account_id} | ADMIN | Zugang ändern; leeres Secret/Passphrase = unverändert |
| DELETE | /api/accounts/{account_id} | ADMIN | Zugang samt Zuordnungen löschen |
| GET | /api/accounts/{account_id}/assignments | ADMIN | Zusätzliche Zuordnungen lesen |
| PUT | /api/accounts/{account_id}/assignments | ADMIN | Zuordnungsliste komplett ersetzen |
| POST | /api/accounts/{account_id}/deploy | ADMIN | Öffentlichen Schlüssel per Login-Zugang aufs Gerät bringen |
| GET | /api/accounts/{account_id}/secret | ADMIN | Ein Secret im Klartext, protokolliert |
| POST | /api/systems/{system_id}/ssh-keys | ADMIN | Ed25519-Schlüsselpaar für ein Gerät erzeugen |

Request-Körper: Zugang `{systemId?, label, category, username, secret, passphrase, url, notes,
allowProbe, port}`; Zuordnungen `[{targetType, targetValue}]`; Deploy `{loginAccountId, port=0}`;
Schlüssel `{label}`.

Berührte fremde Routen: `GET /api/systems/{id}` liefert Zugänge des Geräts ohne Secrets
([inventar](../inventar/spec.md)); `PATCH /api/settings` für den Standard-Zugang
([einstellungen-und-llm-provider](../einstellungen-und-llm-provider/spec.md)).

UI-Seite(n): `frontend/src/pages/zugaenge/AccountsPage.tsx`, `frontend/src/pages/zugaenge/AccountFormPage.tsx` (Routen `/zugaenge`, `/zugaenge/neu`,
`/zugaenge/:id`, nur Admin).

## Nicht-Ziele und Grenzen

- Kein Passwort-Manager (keine Browser-Integration, Freigaben, Notfallzugriff) – README „Sicherheit“.
- Kein Schutz gegen root auf dem Docker-Host (Schlüssel liegt im selben Volume).
- Kein Abruf der Passphrase, kein Export aller Zugänge.
- Kein Entfernen eines ausgerollten Schlüssels vom Gerät; kein Schlüsselwechsel.
- Interaktive Konsole, Neustart, Container-Steuerung: [remote-admin](../remote-admin/spec.md).

## Ist-Implementierung (nur Referenz, [Impl])

- Fernet (`cryptography`), Schlüssel als Datei; Ver-/Entschlüsselung in `crypto.py`.
- Keine Fremdschlüssel in SQLite; Kaskaden manuell in `db.delete_account`/`db.delete_system`.
- SSH-Ausrollen per SFTP (asyncssh), Hostschlüssel ungeprüft (`known_hosts=None`), Connect-Timeout 10 s.
- Öffentlicher Schlüssel lebt im Notizfeld; dadurch braucht es keine eigene Abruf-Route.
- UI zeigt beim Ausrollen nur Login-Zugänge desselben Geräts mit `hasSecret`.

## OFFEN

- > OFFEN: Kategorie wird serverseitig nicht validiert; beliebige Werte werden gespeichert. → #128
- > OFFEN: Secret und Passphrase lassen sich über die API nicht mehr leeren (leer = unverändert). → #128
- > OFFEN: Ausrollen akzeptiert jede Kategorie als Login-Zugang (z. B. `snmp`, `wifi`); das Secret
  wird dann als SSH-Passwort benutzt. → #128
- > OFFEN: `systemId` wird beim Anlegen/Ändern nicht auf Existenz geprüft. → #128
- > OFFEN: Löschen eines unbekannten Zugangs liefert `{ok: true}` statt 404. → #128
- > OFFEN: Anlegen, Ändern und Löschen von Zugängen werden nicht im Zugriffsprotokoll erfasst,
  nur Abruf, Erzeugung und Ausrollen. → #122
- > OFFEN: MEMBER sehen über Geräteansicht und Doku Benutzernamen, URLs und Notizen aller Zugänge;
  ob Notizen sensibel sein dürfen, ist nicht geregelt. → entschieden in #48: in Ordnung, solange keine Secrets
