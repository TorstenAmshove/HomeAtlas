# Firewall-Regeln

> Status: Teil A umgesetzt (UniFi lesen und speichern, #106). nftables, Pfadbewertung, Assistenten-Werkzeuge
> und das Doku-Kapitel folgen in weiteren Teilen; sie stehen unten unter OFFEN.

## Zweck

HomeAtlas liest die Firewall-Regeln des Heimnetzes rein lesend, damit später beantwortet werden kann,
wer mit wem sprechen darf und warum etwas nicht geht. Dieser Teil speichert Zonen, Regeln und Gruppen
des UniFi-Gateways im Inventar.

## Rollen und Rechte

| Aktion | ADMIN | MEMBER |
|---|---|---|
| Schalter `scanEnableFirewallUnifi` ändern | ja | nein |
| Zugang der Kategorie `unifi` zum Auslesen freigeben | ja | nein |

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

### Requirement: Nur Positivliste, keine Geheimnisse
Das System MUSS je Fakt nur eine Positivliste von Feldern speichern (Zonen-ID/-Name/Netz-IDs, Regel-ID,
Name, Index, aktiv, vordefiniert, Aktion, Protokoll, Zonen, IPs/Gruppen, Ports, Verbindungsstatus) und
nie Rohantworten, Kommentare, Trefferzähler oder Schlüssel. Namen werden von Steuerzeichen befreit und auf
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

`firewallFacts` (siehe [data-model](../../contracts/data-model.md)); Einstellung `scanEnableFirewallUnifi`.

## Schnittstellen

Keine eigenen Routen; der Schalter läuft über die Einstellungs-API.

UI-Seite(n): `frontend/src/pages/SettingsPage.tsx` (Route `/einstellungen`).

## Nicht-Ziele und Grenzen

Keine Änderung von Firewall-Regeln; keine Proxmox-Firewall in v1; keine Docker-iptables-Regeln.

## OFFEN

- > OFFEN: nftables der Hosts (Forced-Command `nft -j list ruleset`), Pfadbewertung (`firewall_eval.py`),
  > Werkzeuge `check_firewall_path`/`list_firewall_rules`, Kapitel „Wer darf mit wem sprechen“ und die
  > Verknüpfung mit den Erreichbarkeits-Ketten (Issue #106, Teile B–D).
