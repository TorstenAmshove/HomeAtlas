# ADR-0027: UniFi-Geräte-Uplinks und Gateway-Ports aus `stat/device` lesen

- **Status:** Akzeptiert, ergänzt ADR-0025 und ADR-0026
- **Datum:** 2026-11-26

## Kontext
Die Port-Tabelle eines UniFi-Switches zeigt „Angeschlossenes Gerät“ nur für Clients (`stat/sta`). APs, Switches
und der Uplink zum Gateway fehlen, obwohl gerade diese Ports beim Fehlersuchen interessant sind. Die Integration-API
liefert nur `uplinkDeviceId`, keinen Port. `stat/device` (Pfad aus ADR-0025) enthält je Gerät ein `uplink`-Objekt mit
`type`, `uplink_device_name`, `uplink_remote_port` und `port_idx`, steht aber nicht in der Feld-Positivliste.
Das Gateway (`udm`/`ugw`/`uxg`) hat ebenfalls LAN-Ports, wird aber bisher nicht als Port-Tabelle gelesen.

## Entscheidung
ADR-0025 und ADR-0026 gelten unverändert weiter. Kein neuer Pfad, kein neuer Schalter, nur GET. Zusätzlich darf der
Probe aus `stat/device` lesen:
- **`uplink`:** nur `type`, `uplink_device_name`, `uplink_remote_port`, `port_idx`. Zähler, IPs, MACs, WAN-Daten
  (`gateways`, `ip`, `uplink_mac` …) und alle übrigen Felder bleiben verworfen.
- **Zuordnung:** `uplink_device_name` wird nur im Probe verwendet und je Site exakt gegen den `name` der Geräte
  derselben Antwort aufgelöst. Nur ein eindeutiger Treffer zählt; der Name wird nicht gespeichert, nur die MAC des
  Gegenübers. Nur `type == "wire"` mit ganzzahligem `uplink_remote_port` (1 bis 999) erzeugt einen Eintrag; Funk-
  Uplinks, fehlerhafte Werte, Selbstverweise und mehrdeutige Namen ergeben nichts.
- **Speicherung:** gleiche Struktur wie bei Clients (`extra.unifi.connection`, `type: wired`, `port` = Port am
  Gegenüber). Ein Client-Eintrag aus `stat/sta` hat Vorrang und wird nie überschrieben.
- **Eigener Uplink-Port:** der Switch-Port mit `port_idx == uplink.port_idx` wird als `uplink: true` markiert und in
  der Anzeige „Uplink → <Name>“ gerendert.
- **Gateway-Ports:** `port_table` der Gateway-Typen wird wie beim Switch gelesen (`extra.unifi.ports`); der WAN-Port
  (`is_uplink` oder eigener Uplink-Port) wird ausgelassen.
- **Verwendung:** Anzeige im Gerätedetail und in der Doku. Die Daten gelangen nicht in LLM-Kontext (`tools.py`
  bleibt unberührt).
- **Obergrenzen:** wie ADR-0025 (128 Ports je Gerät) und höchstens 500 Geräte-Uplinks je Scan (eine Warnung).

## Konsequenzen
- Beim Fehlersuchen steht am Switch-Port, welcher AP oder Switch daran hängt.
- Die Geräte-Uplinks werden nur zusammen mit den Port-VLANs gelesen (`portsOk`); sind sie nicht lesbar, bleiben
  bestehende Verbindungen stehen, werden aber nicht entfernt.
- Reviewer erkennen Verstöße an Zählern, IPs, MACs oder Gerätenamen im gespeicherten Ergebnis.
