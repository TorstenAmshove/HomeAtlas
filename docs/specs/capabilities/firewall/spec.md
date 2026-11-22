# Firewall-Regeln

> Status: Teile A und B umgesetzt (UniFi und nftables lesen und speichern, #106). Pfadbewertung, Assistenten-Werkzeuge
> und das Doku-Kapitel folgen in weiteren Teilen; sie stehen unten unter OFFEN.

## Zweck

HomeAtlas liest die Firewall-Regeln des Heimnetzes rein lesend, damit später beantwortet werden kann,
wer mit wem sprechen darf und warum etwas nicht geht. Dieser Teil speichert Zonen, Regeln und Gruppen
des UniFi-Gateways sowie den live geladenen nftables-Regelsatz freigegebener Hosts im Inventar.

## Rollen und Rechte

| Aktion | ADMIN | MEMBER |
|---|---|---|
| Schalter `scanEnableFirewallUnifi` ändern | ja | nein |
| Schalter `scanEnableFirewallNft` ändern | ja | nein |
| Zugang der Kategorie `unifi` oder `firewall_nftables` zum Auslesen freigeben | ja | nein |

## Anforderungen

### Requirement: UniFi-Firewall lesen
Das System MUSS Firewall-Zonen, -Policies und Adress-/Port-Gruppen des UniFi-Gateways nur lesend
erfassen, nur mit einem Zugang der Kategorie `unifi` (API-Key) mit `allowProbe` und nur solange
`scanEnableFirewallUnifi` (Default **aus**) gesetzt ist
([ADR-0017](../../../adr/0017-firewall-quellen-und-pfadbewertung.md)). Je Site gibt es drei feste GET-Pfade
(`v2/api/site/<site>/firewall/zone`, `v2/api/site/<site>/firewall-policies`,
`api/s/<site>/rest/firewallgroup`) mit `X-API-Key`, ohne Login, Cookie, CSRF-Token und Weiterleitungen.
**[Muss]**

#### Szenario: Erfolgreicher Scan
- **WENN** der Abruf gelingt
- **DANN** ersetzen die gelesenen Fakten (`zone`, `policy`, `group`) die bisherigen dieses Zugangs

#### Szenario: Quelle nicht lesbar
- **WENN** der Abruf fehlschlägt (Key abgelehnt, Endpunkt nicht verfügbar, Timeout, mehr als 500 Regeln)
- **DANN** bleiben die alten Fakten als veraltet (`stale`) erhalten, ein Geräte-Fehler-Event entsteht am System des Zugangs und die übrigen Quellen laufen weiter

#### Szenario: Opt-in entfällt
- **WENN** `allowProbe` oder `scanEnableFirewallUnifi` abgeschaltet oder der Zugang gelöscht wird
- **DANN** werden die Firewall-Fakten beim nächsten Scan (bzw. sofort beim Löschen) entfernt

Quelle: `backend/app/firewall_unifi.py`, `backend/app/pipeline.py`, Test: `backend/tests/test_firewall_unifi.py`, `backend/tests/test_pipeline_firewall.py`, `backend/tests/test_firewall_boundaries.py`

### Requirement: nftables der Hosts per Forced-Command lesen
Das System MUSS den live geladenen nftables-Regelsatz eines Hosts per SSH lesen, nur mit einem Zugang der
Kategorie `firewall_nftables` mit `allowProbe` und nur solange `scanEnableFirewallNft` (Default **aus**)
gesetzt ist. Es gibt genau einen im Code festen Befehl (`nft -j list ruleset`, ohne Parameter); was auf dem
Host läuft, erzwingen `authorized_keys` (`command="sudo /usr/sbin/nft -j list ruleset"`) und ein sudoers-Eintrag
nur für diesen Befehl ([ADR-0017](../../../adr/0017-firewall-quellen-und-pfadbewertung.md)). Pro Basiskette
(Familie `inet`/`ip`, mit Hook) werden Hook, Priorität, Policy und die Regeln als normierte Treffer
(Quell-/Ziel-IP, Port, Verbindungsstatus, Schnittstelle) mit Urteil gespeichert, dazu ein Marker je Host.
Nicht sicher auswertbares (`jump`/`goto`, NAT, `limit`, Negation, nicht aufgelöste Sets, andere Familien)
wird als `unsupported` an der Regel vermerkt. **[Muss]**

#### Szenario: Host nicht lesbar
- **WENN** sudo verweigert, die Ausgabe leer, kein gültiges JSON, über 512 KiB oder mit mehr als 500 Regeln ist, oder die Verbindung scheitert
- **DANN** gilt der Host als nicht lesbar (nie als „keine Regeln“), seine alten Fakten werden `stale`, ein Geräte-Fehler-Event entsteht und die übrigen Hosts und Quellen laufen weiter

#### Szenario: Leerer, gültiger Regelsatz
- **WENN** der Host einen gültigen Regelsatz ohne Basisketten liefert
- **DANN** wird nur der Host-Marker gespeichert

Quelle: `backend/app/firewall_nft.py`, `backend/app/pipeline.py`, Test: `backend/tests/test_firewall_nft.py`, `backend/tests/test_pipeline_firewall.py`, `backend/tests/test_firewall_boundaries.py`

### Requirement: Nur Positivliste, keine Geheimnisse
Das System MUSS je Fakt nur eine Positivliste von Feldern speichern (Zonen-ID/-Name/Netz-IDs, Regel-ID,
Name, Index, aktiv, vordefiniert, Aktion, Protokoll, Zonen, IPs/Gruppen, Ports, Verbindungsstatus) und
nie Rohantworten, Kommentare, Trefferzähler oder Schlüssel (bei nftables ebenso keine Rohausgabe und keine Kommentare). Namen werden von Steuerzeichen befreit und auf
80 Zeichen gekürzt. Was die spätere Bewertung nicht sicher beurteilen kann (Zeitplan, IPsec, benutzerdefinierter
Verbindungsstatus, negierte Zuordnung, unbekannte Formate), wird als `unsupported` an der Regel vermerkt. **[Muss]**

#### Szenario: Zu viele Regeln
- **WENN** mehr als 500 Policies gelesen werden
- **DANN** gilt die Quelle als nicht lesbar (keine Teilmenge)

Quelle: `backend/app/firewall_unifi.py`, Test: `backend/tests/test_firewall_unifi.py::test_drops_unknown_and_secret_fields`, `::test_max_500_policies_is_unreadable_not_a_subset`

### Requirement: Fakten-Speicher
Das System MUSS Firewall-Fakten in `firewallFacts` ablegen; ein Lesefehler markiert sie als veraltet statt sie
zu löschen, `firstSeen` bleibt erhalten, beim Löschen eines Zugangs werden seine Fakten entfernt. **[Muss]**

Quelle: `backend/app/db/firewall.py`, Test: `backend/tests/test_db_firewall.py`

## Daten

`firewallFacts` (siehe [data-model](../../contracts/data-model.md)); Einstellungen `scanEnableFirewallUnifi`, `scanEnableFirewallNft`.

## Schnittstellen

Keine eigenen Routen; der Schalter läuft über die Einstellungs-API.

UI-Seite(n): `frontend/src/pages/SettingsPage.tsx` (Route `/einstellungen`).

## Nicht-Ziele und Grenzen

Keine Änderung von Firewall-Regeln; keine Proxmox-Firewall in v1; keine Docker-iptables-Regeln; nftables nur `inet`/`ip`, kein IPv6.

## OFFEN

- > OFFEN: Pfadbewertung (`firewall_eval.py`),
  > Werkzeuge `check_firewall_path`/`list_firewall_rules`, Kapitel „Wer darf mit wem sprechen“ und die
  > Verknüpfung mit den Erreichbarkeits-Ketten (Issue #106, Teile C–D).
