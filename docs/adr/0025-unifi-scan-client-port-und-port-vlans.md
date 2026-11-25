# ADR-0025: UniFi-Scan liest Client-Zuordnung und Port-VLANs aus der klassischen API

- **Status:** Akzeptiert, ersetzt ADR-0023
- **Datum:** 2026-11-25

## Kontext
Die offizielle UniFi-Integration-API nennt je Client nur `uplinkDeviceId`, keine Portnummer, und Ports haben keine
VLAN-Zuordnung. Für die geplanten Folge-Issues („Switchport bzw. AP je Client“, „VLAN je Switchport“) braucht der
Scan Felder der klassischen API. `unifi_classic_probe.py` liest bisher vier feste GET-Pfade (`self/sites`,
`rest/portforward`, `stat/device`, `rest/networkconf`, ADR-0016 bis ADR-0023). Ein Spike gegen UniFi Network 11.x
(nur GET mit `X-API-Key`, Basis `/proxy/network`, Issue #223) ergab:

| Pfad | Status | Befund |
|---|---|---|
| `stat/sta` | 200 | `mac`, `is_wired`, `network_id` immer; kabelgebunden mit `sw_mac` und `sw_port`; WLAN mit `ap_mac` und meist `essid`, ohne `sw_port`; einzelne WLAN-Clients ohne `ap_mac`/`essid` (offline) |
| `stat/device` | 200 | `port_table[]` mit `port_idx`, `name`; die Mehrzahl der Ports trägt nur `portconf_id`, andere `native_networkconf_id` (teils mit `excluded_networkconf_ids`); `port_overrides[]` trägt `portconf_id` oder `native_networkconf_id` plus `tagged_vlan_mgmt` |
| `rest/portconf` | 200 | Profile mit `_id`, `name`, `native_networkconf_id`, `tagged_vlan_mgmt` (`auto`, `block_all`); `excluded_networkconf_ids` kam nicht vor |

Weil die meisten Ports nur eine `portconf_id` tragen, ist `rest/portconf` zum Auflösen nötig.

## Entscheidung
Alles aus ADR-0023 gilt unverändert weiter (und damit ADR-0022 bis ADR-0013, soweit lesende Pfade betroffen sind).
ADR-0024 gilt weiter und ergänzt nun dieses ADR. Geändert: Die Scan-Allowlist von `unifi_classic_probe.py` wächst
um zwei Pfade und weitere Felder.
- **Neue Pfade, nur GET:** `api/s/<site>/stat/sta` und `api/s/<site>/rest/portconf`. Wie bisher: Auth allein per
  `X-API-Key`, keine Weiterleitungen, kein Cookie, kein CSRF-Token, gleicher Zugang (Kategorie `unifi` mit
  `allowProbe`), gleicher Schalter `scanEnableUnifiClassic`; kein neuer Schalter.
- **Feld-Positivliste:**
  - `stat/sta`: `mac`, `is_wired`, `sw_mac`, `sw_port`, `ap_mac`, `essid`, `network_id`
  - `stat/device` zusätzlich je Eintrag in `port_table[]` und `port_overrides[]`: `port_idx`, `name`, `portconf_id`,
    `native_networkconf_id`, `tagged_vlan_mgmt`, `excluded_networkconf_ids`
  - `rest/portconf`: `_id`, `name`, `native_networkconf_id`, `tagged_vlan_mgmt`, `excluded_networkconf_ids` (optional)
- **Ausgeschlossen:** Port-Statistiken und Zähler, IP, Hostname, Name, `oui` und Fingerprint der Clients, `x_*`-Felder,
  Tokens, Gast-Merkmale, Rohdaten außerhalb der Positivliste.
- **Obergrenzen je Site:** 2000 Clients, 128 Ports je Gerät, 200 Port-Profile. Überschreitung kürzt ohne Abbruch und
  wird einmal je Scan als Warnung geloggt. Antwortgröße und Timeout wie bei den bestehenden Pfaden.
- **Randfälle:** Client ohne `mac` wird verworfen; Client ohne `sw_port` und `ap_mac` bleibt ohne Zuordnung; Port ohne
  `portconf_id`; `native_networkconf_id` ohne `tagged_vlan_mgmt`; unbekannte Werte (z. B. `custom`) werden unverändert
  als Text übernommen, nicht interpretiert. Mehrere Sites werden je Site gelesen, `portconf_id` wird innerhalb
  derselben Site aufgelöst, gleiche MACs in mehreren Sites bleiben je Site getrennt.
- **Fehlerverhalten:** 400/401/403/404/429/5xx, kein JSON oder keine Liste: nur diese Quelle fällt weg, der Scan läuft
  weiter (wie bisher).
- **Datenschutz:** Client-MACs und Zuordnungen landen nur im Inventar. Ob und wie sie in Doku oder LLM-Kontext
  erscheinen, entscheiden die Folge-Issues.
- **Unberührt:** `unifi_live.py` (ADR-0017-Allowlist) und `tools.py` erhalten keinen neuen Pfad.
- **Vorratsbeschluss:** Code und Modul-Docstring („four fixed paths“) ändern sich erst mit den Folge-Issues.

## Konsequenzen
- Der Scan sieht Switchport bzw. AP je Client und VLAN je Switchport, ohne Schreibzugriff und ohne neue Zugangsart.
- Reviewer erkennen Verstöße an `post`/`put`/`delete`/`patch`/`request` in `unifi_classic_probe.py`, an einem Import
  aus `unifi_live`, an Pfaden oder Feldern außerhalb dieser Liste.
- Die Folge-Umsetzung im Probe-Modul ist `risk:high` zu bewerten und braucht Review durch einen Menschen.
- ADR-0023 hat den Status „Ersetzt durch ADR-0025“.
