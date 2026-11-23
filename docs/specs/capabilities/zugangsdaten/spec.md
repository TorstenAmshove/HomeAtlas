# Zugangsdaten

> Status: Ist-Verhalten, aus dem Code zurückgewonnen (Stand 0159807). Quellen als `datei:zeile`.

## Zweck

Ein Haushalt legt die Zugänge zu seiner Technik (Router, NAS, Switches, Provider-Kundenkonto,
WLAN, API-Tokens, SSH-Schlüssel) an einer Stelle ab, damit man im Störungsfall drankommt. Die
Secrets liegen verschlüsselt, verlassen den Server nur einzeln auf ausdrückliche Admin-Anfrage
und erscheinen nie in Dokumentation, Chat oder LLM-Kontext. Ein Zugang kann einem oder mehreren
Geräten (auch ganzen Gerätetypen/Subnetzen) zugeordnet und optional fürs lesende Auslesen
freigegeben werden. SSH-Schlüssel erzeugt und verteilt HomeAtlas nicht (ADR-0023); ein außerhalb
angelegter Schlüssel wird als Zugang der Art `sshkey` eingetragen und fürs lesende Probing genutzt.

## Rollen und Rechte

| Aktion | ADMIN | MEMBER |
|---|---|---|
| Zugänge auflisten, anlegen, ändern, löschen | ja | nein |
| Secret eines Zugangs im Klartext abrufen | ja (einzeln, protokolliert) | nein |
| Zuordnungen lesen/ersetzen | ja | nein |
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
Antwort enthält den Zugang ohne Secret/Passphrase/Chiffretext, dafür `hasSecret`/`hasPassphrase`.
Eine angegebene, nicht (mehr) vorhandene `systemId` → 422 „Gerät nicht gefunden.“; `null`/leer löst die
Zuordnung. **[Muss]**

#### Szenario: Anlegen mit Passwort
- **WENN** ein Admin einen Zugang mit Secret „geheim“ anlegt
- **DANN** enthält die Antwort `hasSecret: true` und weder „geheim“ noch `secretEnc`

Quelle: `backend/app/main.py:656`, `backend/app/main.py:619`, `backend/app/db.py:1369`

### Requirement: Kategorien
Das System MUSS die Kategorien `contract` (Vertrag/Kundenkonto), `login`, `sshkey`, `snmp`,
`omada`, `unifi`, `homeassistant`, `proxmox`, `adguard`, `traefik`, `cloudflare`,
`exposure_cloudflared`, `exposure_caddy`, `exposure_ddclient`, `firewall_nftables`, `wifi`, `apikey`,
`other` anbieten; jede andere Kategorie wird beim Anlegen und Ändern mit 422 abgelehnt. Die
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
Zum Leeren dient das explizite Feld `clearSecrets` (Liste aus `secret`/`passphrase`, wie bei
`PATCH /api/settings`); es zusammen mit einem neuen Wert für dasselbe Feld → 422 (ohne den Wert zu
spiegeln). Unbekannte ID → 404 „Zugang nicht gefunden.“ (vor der Prüfung der `systemId`, die bei
unbekanntem Gerät 422 liefert). **[Muss]**

#### Szenario: Passwort entfernen
- **WENN** `PATCH /api/accounts/{id}` `{"clearSecrets": ["secret"]}` enthält
- **DANN** ist `hasSecret` false; die Passphrase bleibt unberührt

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
`{ok: true}`; unbekannte ID → 404 „Zugang nicht gefunden.“ **[Muss]**

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
  Benutzung des Secrets (Abruf, Probing, Controller-Abfragen, KI-Schlüssel,
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
automatische lesende Auslesen auswerten; schreibende Gerätefunktionen gibt es nicht (ADR-0023); für das Schalten per Assistent gilt dieselbe
Freigabe bei Home-Assistant-Zugängen (siehe assistent-chat-und-mcp). **[Muss]**

#### Szenario: Zugang ohne Freigabe
- **WENN** ein `login`-Zugang ohne Freigabe an einem Server hängt
- **DANN** wird er im Scan nicht genutzt, bleibt aber als Ablage sichtbar

Quelle: `backend/app/db.py:228`, `backend/app/main.py:791`

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
Zuordnungen bleiben erreichbar. „Art“ MUSS das erste Feld des Formulars sein; Beschriftungen, Platzhalter, Hinweise und
Sichtbarkeit der Felder (Benutzername, Adresse, Port, „zum Auslesen verwenden“) MÜSSEN je Art aus einer
zentralen Definition kommen (`categoryFields.ts`, ein `Record` über alle Arten, sodass der Build bei
einer fehlenden Art scheitert). Ausgeblendete Felder DÜRFEN beim Bearbeiten gespeicherte Werte nicht
überschreiben (sie werden nicht gesendet). Bei Cloudflare (Zone-ID in `url`, Account-ID in `username`)
MUSS das Formular vor dem Speichern 32 Zeichen `0-9a-f` prüfen (Account-ID optional).
Datenmodell und API bleiben unverändert (die UI nutzt `clearSecrets` nicht). **[Muss]** (Texte und Aufteilung **[Impl]**)

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
| PATCH | /api/accounts/{account_id} | ADMIN | Zugang ändern; leeres Secret/Passphrase = unverändert, `clearSecrets` leert |
| DELETE | /api/accounts/{account_id} | ADMIN | Zugang samt Zuordnungen löschen |
| GET | /api/accounts/{account_id}/assignments | ADMIN | Zusätzliche Zuordnungen lesen |
| PUT | /api/accounts/{account_id}/assignments | ADMIN | Zuordnungsliste komplett ersetzen |
| GET | /api/accounts/{account_id}/secret | ADMIN | Ein Secret im Klartext, protokolliert |

Request-Körper: Zugang `{systemId?, label, category, username, secret, passphrase, url, notes,
allowProbe, port}` (PATCH zusätzlich `clearSecrets?`); Zuordnungen `[{targetType, targetValue}]`.

Berührte fremde Routen: `GET /api/systems/{id}` liefert Zugänge des Geräts ohne Secrets
([inventar](../inventar/spec.md)); `PATCH /api/settings` für den Standard-Zugang
([einstellungen-und-llm-provider](../einstellungen-und-llm-provider/spec.md)).

UI-Seite(n): `frontend/src/pages/zugaenge/AccountsPage.tsx`, `frontend/src/pages/zugaenge/AccountFormPage.tsx` (Routen `/zugaenge`, `/zugaenge/neu`,
`/zugaenge/:id`, nur Admin).

## Nicht-Ziele und Grenzen

- Kein Passwort-Manager (keine Browser-Integration, Freigaben, Notfallzugriff) – README „Sicherheit“.
- Kein Schutz gegen root auf dem Docker-Host (Schlüssel liegt im selben Volume).
- Kein Abruf der Passphrase, kein Export aller Zugänge.
- Kein Erzeugen oder Verteilen von SSH-Schlüsseln (ADR-0023): Schlüssel legt der Admin außerhalb an (z. B. per Ansible) und trägt sie als Zugang der Kategorie `sshkey` ein; bestehende `sshkey`-Zugänge dienen weiter dem lesenden Auslesen.
- Keine Fernwartung (Konsole, Neustart, Container-Steuerung); entfallen mit ADR-0023.

## Ist-Implementierung (nur Referenz, [Impl])

- Fernet (`cryptography`), Schlüssel als Datei; Ver-/Entschlüsselung in `crypto.py`.
- Keine Fremdschlüssel in SQLite; Kaskaden manuell in `db.delete_account`/`db.delete_system`.
- SSH-Ausrollen per SFTP (asyncssh), Hostschlüssel ungeprüft (`known_hosts=None`), Connect-Timeout 10 s.
- Öffentlicher Schlüssel lebt im Notizfeld; dadurch braucht es keine eigene Abruf-Route.
- UI zeigt beim Ausrollen nur Login-Zugänge desselben Geräts mit `hasSecret`.

### Requirement: Zugangsänderungen werden protokolliert
Das System MUSS erfolgreiches Anlegen, Ändern und Löschen eines Zugangs als `account.create`,
`account.update` und `account.delete` ins Zugriffsprotokoll schreiben (Aktor: handelnder ADMIN). Das
Detail enthält die Bezeichnung, bei `account.update` zusätzlich die Namen der gesendeten Felder
(`<Bezeichnung>: Passwort, Scan-Freigabe`, `Passwort entfernt` bei `clearSecrets`), nie einen Wert.
Ein leerer Patch, 404, 422 und 403 erzeugen keinen Eintrag. **[Muss]**

#### Szenario: Passwort ändern
- **WENN** ein ADMIN nur `secret` per PATCH sendet
- **DANN** steht `account.update` mit Detail `<Bezeichnung>: Passwort` im Protokoll, ohne das Passwort

## OFFEN

- > OFFEN: MEMBER sehen über Geräteansicht und Doku Benutzernamen, URLs und Notizen aller Zugänge;
  ob Notizen sensibel sein dürfen, ist nicht geregelt. → entschieden in #48: in Ordnung, solange keine Secrets
