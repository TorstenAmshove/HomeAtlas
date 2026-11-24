# Datenmodell

> Stand: Commit 0159807. Erzeugt aus dem Schema, das `backend/app/db/_core.py:init_db` anlegt
> (frische DB, `.schema`), ergänzt um die Bedeutung der Felder. Schema-Quelle: `backend/app/db/`
> (`_SCHEMA` und Migrationen in `init_db`, `backend/app/db/_core.py`).

Technik-Hinweis **[Impl]**: SQLite ohne ORM, IDs sind zufällige Text-IDs, Zeitstempel sind
ISO-8601-Text in UTC, JSON-Felder (`openPorts`, `services`, `tags`, `extra`, `facts`, `summary`,
`toolCalls`, `providerRaw`) sind JSON als Text. Eine Alternative darf ein anderes Speichermodell
wählen. Fachlich verbindlich **[Muss]** sind die Entitäten, ihre Beziehungen und die unten
markierten Regeln.

## Übersicht

```
users ─┬─ sessions
       └─ accessLog (userId, auch ohne User bei fehlgeschlagenem Login)
apiTokens                                  (MCP-Zugang, an keinen User gebunden)
settings (key/value)

systems ─┬─ systems (parentId: Container/VM → Host)
         ├─ systemAliases        (frühere IP/MAC-Identitäten nach Merge)
         ├─ duplicateDismissals  (Paar idA/idB: "kein Duplikat")
         ├─ accounts (systemId, optional) ── accountAssignments (system | kind | subnet)
         ├─ deviceConfigVersions
         ├─ deviceErrorEvents
         ├─ monitorEvents
         └─ networkResources (ownerSystemId, optional; sourceAccountId → accounts)

docPages ── docPageVersions (über slug)
scans
chats ── chatMessages
```

## Entitäten

### users — Anmeldbare Personen
| Feld | Bedeutung |
|---|---|
| id, username (eindeutig) | |
| passwordHash, salt | Passwort nur als Hash **[Muss]** |
| role | `ADMIN` oder `MEMBER` (`backend/app/auth.py:22`) |
| displayName | Anzeigename |
| totpSecretEnc | TOTP-Geheimnis, verschlüsselt wie alle Secrets **[Muss]** |
| totpEnabled | wird erst 1, nachdem ein gültiger Code bestätigt wurde (halb fertige Einrichtung sperrt niemanden aus) **[Muss]** |
| totpLastCounter | Zeitschritt des zuletzt verwendeten TOTP-Codes; ältere und gleiche werden abgelehnt (Replay-Sperre) **[Muss]** |
| createdAt | |

### sessions — Login-Sitzungen
`token` (Primärschlüssel, Cookie-Wert), `userId`, `expiresAt`.

### accessLog — Zugriffsprotokoll
`at`, `userId` (optional), `username`, `action`, `detail`, `ip`, `userAgent`, `ok` (Erfolg/Fehlschlag).

### apiTokens — Tokens für den externen MCP-Endpunkt
`label`, `token` (eindeutig), `createdAt`, `lastUsedAt`. Der Rohwert wird nur beim Anlegen einmal
ausgegeben, Listen liefern ihn nie (`backend/app/db/users.py`) **[Muss]**.
> OFFEN: Der Token wird im Klartext gespeichert (nicht gehasht). Für eine Alternative Hashing erwägen.

### settings — Einstellungen
Schlüssel/Wert-Paare. Die Schlüssel und Defaults stehen in
[einstellungen-und-llm-provider](../capabilities/einstellungen-und-llm-provider/spec.md).

### systems — Inventar (Geräte, VMs, Container, Dienste)
| Feld | Bedeutung |
|---|---|
| kind | `router, network, server, nas, container, vm, pc, mobile, printer, camera, smarthome, climate, heating, energy, media, iot, other` (`backend/app/classify.py:29`) |
| name | Anzeigename, Herkunft nach fester Namenspräzedenz (siehe [discovery-und-scan](../capabilities/discovery-und-scan/spec.md)) |
| hostname, ip, mac, vendor, model, os | technische Eckdaten |
| location, purpose, descriptionMd, notes | vom Haushalt gepflegte Beschreibung |
| url | Weboberfläche des Geräts |
| docUrl | Herstellerhandbuch / Supportseite für das Modell |
| docLink | eigene Doku zu genau diesem Gerät (Wiki, Runbook); aus Proxmox-Notizen (`Doc:`/`URL:`) befüllt |
| importance | `critical`, `normal`, `low` |
| parentId | Host eines Containers/einer VM |
| status | z. B. `unknown`, `online`, `offline` |
| discovered | durch Scan gefunden (vs. von Hand angelegt) |
| confirmed | von Hand bearbeitet: danach dürfen Discovery, Klassifikation und Proxmox-Tags von Menschen gepflegte Felder nicht mehr überschreiben **[Muss]** (`backend/app/db/:1137`) |
| discoverySource | Quelle der Erkennung |
| discoveryKey | stabile Wiedererkennung: `mac:<mac>`; `ip:<addr>` (außerhalb des L2-Segments); `docker:<projekt>:<service>` bzw. `docker:<containername>` (Altschlüssel `docker:<id12>` wird übernommen, `backend/app/docker_probe.py:102`); `proxmox:<node>:<kind>:<vmid>` für Gäste ohne MAC (`backend/app/proxmox_probe.py:165`); leer bei manuellen Einträgen. Suchreihenfolge bei der Wiedererkennung: [discovery-und-scan](../capabilities/discovery-und-scan/spec.md) |
| identityKey | abgeleitet: `discoveryKey` oder `id:<id>`, eindeutig **[Muss: ein Gerät = eine Identität]** |
| monitored, monitorPorts | Dauerüberwachung an/aus und zu prüfende Ports |
| openPorts, services, tags, extra | JSON: offene Ports, erkannte Dienste, Tags, quellspezifische Zusatzdaten (Probing-Ergebnisse, Docker/Compose, UniFi …) |
| firstSeen, lastSeen, updatedAt | |

Standardsortierung: `importance` (critical → normal → low), dann Name ohne Groß/Klein
(`backend/app/db/systems.py`).

### systemAliases — Frühere Identitäten
`aliasKey` (z. B. alte `mac:`/`ip:`-Identität), `systemId`, `ip`, `mac`. Nach einem Merge
wird ein später wieder auftauchendes Duplikat über den Alias dem überlebenden System zugeordnet.

### duplicateDismissals
Paar `(idA, idB)`, das ein Mensch als „kein Duplikat“ markiert hat.

### accounts — Zugangsdaten
| Feld | Bedeutung |
|---|---|
| systemId | optional, zugehöriges Gerät |
| label | |
| category | `contract, login, sshkey, unifi, homeassistant, proxmox, wifi, apikey, other` (`frontend/src/pages/AccountsPage.tsx:5`) |
| username | |
| secretEnc | Passwort / privater Schlüssel / Token, verschlüsselt **[Muss]** |
| passphraseEnc | Passphrase eines SSH-Schlüssels, verschlüsselt |
| url, notes, port | Ziel-URL, Notizen, abweichender Port |
| allowProbe | Opt-in, Default aus: darf HomeAtlas sich damit lesend anmelden? **[Muss]** |

### accountAssignments — Wofür ein Zugang zusätzlich gilt
`accountId`, `targetType` (`system` → systems.id, `kind` → systems.kind, `subnet` → CIDR),
`targetValue`.

### networkResources — Netze, WLANs, WANs aus Controllern
`kind` (`network`, `wifi`, `wan`), `source` (Controller-Typ), `sourceKey` (eindeutig),
`sourceAccountId`, `ownerSystemId`, `siteExternalId`, `siteName`, `externalId`, `name`, `enabled`,
`active`, `emptyScans` (aufeinanderfolgende leere Abgleiche, #139), `facts` (JSON), `manualMd` (Notizen des Haushalts), `firstSeen`, `lastSeen`.

### deviceConfigVersions — Versionierte Gerätekonfiguration
`systemId`, `label`, `content`, `source`, `createdAt`.

### deviceErrorEvents — Fehlermeldungen je Gerät
`systemId`, `level` (Default `error`), `message`, `createdAt`, `acknowledgedAt` (`NULL` = offen; nur offene zählen im Fehler-Badge).

### monitorEvents — Statusübergänge der Überwachung
`systemId`, `at`, `status`, `detail`. Gespeichert werden nur Übergänge, nicht jede Abfrage **[Muss]**.

### docPages — Dokumentationskapitel
`slug` (eindeutig), `topic`, `title`, `bodyMd` (generiert oder manuell überschrieben),
`manualMd` (eigene Notizen, von der Generierung nie angefasst **[Muss]**), `intro`, `generated`
(0 = ganze Seite manuell überschrieben), `sortOrder`.

### docPageVersions — Versionen der Kapitel
`slug`, `title`, `bodyMd`, `manualMd`, `generated`, `reason`, `createdAt`.

### scans — Scan-Läufe
`startedAt`, `finishedAt`, `status` (Default `running`), `subnets`, `progress` (0–100), `phase`,
`summary` (JSON), `log`.

### chats / chatMessages — Unterhaltungen mit dem Assistenten
`chats`: `title` (Default „Neue Unterhaltung“), `userId` (Besitzer; leer bei Altdaten, dann nur
für ADMIN sichtbar), `createdAt`, `updatedAt`.
`chatMessages`: `role`, `content`, `toolCalls`, `providerRaw` (unveränderte Anbieterantwort, damit
signierte Thinking-Blöcke beim nächsten Zug exakt zurückgespielt werden können **[Impl]**),
`toolCallId`, `name`, `durationMs`, `createdAt`.

## Querschnittsregeln

- Secrets (`accounts.secretEnc`, `accounts.passphraseEnc`, `users.totpSecretEnc`) liegen nur
  verschlüsselt vor; der Schlüssel liegt getrennt von der Datenbank-Datei **[Muss]**.
- Eine Alternative braucht keine Migrationskompatibilität mit dieser Datenbank, es sei denn, sie
  soll bestehende Installationen übernehmen. > OFFEN: Datenübernahme gewünscht?
