# Firewall-Regeln

> Status: Teile A bis D umgesetzt (UniFi und nftables lesen und speichern, Pfadbewertung, Assistenten-Werkzeuge, #106). Das
> Doku-Kapitel `wer-darf-mit-wem` und die Firewall-Ergebnisse in den Erreichbarkeits-Ketten sind dabei.

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

### Requirement: Pfadbewertung durch HomeAtlas
Das System MUSS für einen Weg `von -> nach : port/protokoll` aus den gespeicherten Fakten je Station (UniFi-Gateway zwischen
den Zonen, Host-Firewall des Ziels eingehend, des Quell-Hosts ausgehend, sofern angebunden) „erlaubt“, „blockiert“ oder
„unklar“ bestimmen, mit Name, Quelle und Position der auslösenden Regel; die Auswertung steckt im reinen Modul
`firewall_eval.py` (kein Netz, keine DB), das LLM erklärt nur
([ADR-0017](../../../adr/0017-firewall-quellen-und-pfadbewertung.md)). Gesamturteil: „blockiert“, sobald eine Station sicher
blockiert; sonst „unklar“, wenn eine Station unklar ist; nur „erlaubt“, wenn jede Station bekannt ist und erlaubt. **[Muss]**

#### Szenario: Gesperrter Port
- **WENN** die Policies des Zonenpaars den Port nicht freigeben und die Standardregel blockiert
- **DANN** ist die Station „blockiert“ mit der auslösenden Regel (UniFi: Index, nftables: Kette und Regelnummer)

#### Szenario: Nicht auswertbar
- **WENN** die Quelle fehlt oder veraltet ist, die Zone nicht zuordenbar ist, eine Regel als `unsupported` vermerkt ist, eine Gruppe fehlt, ICMP/IPv6 gefragt ist, Schnittstellen-Treffer ohne Schnittstellenkenntnis oder gleiche Priorität/gleicher Index vorliegen
- **DANN** ist die Station „unklar“ mit Grund, nie „erlaubt“

Fest ausgewiesen und nicht ausgewertet: Proxmox-Firewall, nftables-`forward`, NAT/Portweiterleitung, IPv6.

Quelle: `backend/app/firewall_eval.py`, Test: `backend/tests/test_firewall_eval.py`, `backend/tests/test_firewall_boundaries.py::test_firewall_eval_is_pure`

### Requirement: Firewall-Werkzeuge des Assistenten
Das System MUSS dem Assistenten die lesenden Werkzeuge `check_firewall_path(von, nach, port, protokoll)` und
`list_firewall_rules(von, nach, system)` bereitstellen (auch über MCP): nur gespeicherte Fakten, kein Live-Zugriff, höchstens
15 Regeln bzw. 8 Stationen, Regelnamen von Steuerzeichen befreit und auf 80 Zeichen gekürzt, kein Roh- oder Kommentartext,
keine Zugangs-IDs. Ungültiger Port (nicht 1–65535), unbekanntes Protokoll, unbekannte Systeme oder `von == nach` ergeben eine
Fehlermeldung. Der Systemprompt weist an, die Bewertung mit `check_port`/`http_check` zu kombinieren. **[Muss]**

Quelle: `backend/app/tools.py`, `backend/app/prompts.py`, Test: `backend/tests/test_tools_firewall.py`

### Requirement: Fakten-Speicher
Das System MUSS Firewall-Fakten in `firewallFacts` ablegen; ein Lesefehler markiert sie als veraltet statt sie
zu löschen, `firstSeen` bleibt erhalten, beim Löschen eines Zugangs werden seine Fakten entfernt. **[Muss]**

Quelle: `backend/app/db/firewall.py`, Test: `backend/tests/test_db_firewall.py`

## Daten

`firewallFacts` (siehe [data-model](../../contracts/data-model.md)); Einstellungen `scanEnableFirewallUnifi`, `scanEnableFirewallNft`.

## Schnittstellen

Keine eigenen Routen; der Schalter läuft über die Einstellungs-API.

UI-Seite(n): `frontend/src/pages/SettingsPage.tsx` (Route `/einstellungen`).

### Requirement: Kapitel „Wer darf mit wem sprechen“
Das System MUSS aus den gespeicherten Fakten ein Kapitel `wer-darf-mit-wem` erzeugen: Zonenmatrix (Zellen „erlaubt“, „gesperrt“, „teilweise (n)“, „unklar“; „unklar“ bei fehlendem Standard oder nicht auswertbarer Regel), Ausnahmen je Zonenpaar, Freigaben je kritischem System, Host-Firewalls und Hinweise. Ohne Fakten erscheint ein Leerzustand. **[Muss]**

Quelle: `backend/app/docs.py` (`_firewall_section`), `backend/app/firewall_eval.py` (`zone_matrix`, `host_firewalls`), Test: `backend/tests/test_docs_firewall.py::test_matrix_exceptions_hints_and_escaping`

### Requirement: Firewall-Ergebnis je Kettenschritt
Das System MUSS jeden Schritt einer Erreichbarkeits-Kette (Schritt n-1 → Schritt n) mit „erlaubt“, „blockiert“ oder „unklar“ versehen; der erste Schritt (Internet, Portweiterleitung/Tunnel) ist „unklar“. Blockiert die Firewall einen als aktiv konfigurierten Pfad, steht ein Hinweis an der Kette. **[Muss]**

Quelle: `backend/app/firewall_eval.py` (`annotate_chains`), Test: `backend/tests/test_exposure_firewall.py::test_blocked_configured_path_gets_hint`

## Nicht-Ziele und Grenzen

Keine Änderung von Firewall-Regeln; keine Proxmox-Firewall in v1; keine Docker-iptables-Regeln; nftables nur `inet`/`ip`, kein IPv6.

## OFFEN

- > OFFEN: Die Zuordnung Netz -> Zone setzt voraus, dass `networkResources.externalId` der UniFi-Netz-ID in `zone.network_ids`
  > entspricht; am echten Gateway noch nicht bestätigt (sonst „unklar: Zone nicht zuordenbar“).
