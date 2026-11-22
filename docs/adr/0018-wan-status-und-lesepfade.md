# ADR-0018: WAN-Status lesen, HA-Systemprotokoll, Dachfenster gesperrt

- **Status:** Ersetzt durch ADR-0019; ersetzte ADR-0017
- **Datum:** 2026-11-22

## Kontext
Der Abnahmetest gegen die echte Instanz zeigte drei Lücken:
- `stat/health` liefert hinter einem vorgeschalteten Router nur die private Adresse der UCG und eine
  Adresse für alle WAN-Zeilen. Dadurch blieb die WAN-IP leer, und direkt per DNS/DynDNS erreichbare
  Hostnamen fehlten in der Doku. Die FRITZ!Box vor der UCG fällt bald weg, die Lösung darf nicht von
  ihr abhängen.
- `/api/error_log` antwortet auf dieser Home-Assistant-Installation mit 404.
- Die Allowlist für Rollos enthielt `window`. Damit konnte der Assistent echte Dachfenster öffnen.

Prüfung gegen die Instanz des Owners (UniFi Network 11.0.103, nur GET mit `X-API-Key`): `api/s/<site>/stat/device` liefert am
Gateway `geo_info.<WAN>.address` (öffentliche Adresse), `last_wan_interfaces`, `last_wan_status` und
`uplink`; `api/s/<site>/rest/networkconf` ordnet `name` und `wan_networkgroup` zu.

## Entscheidung
Alles aus ADR-0017 gilt unverändert weiter (und damit ADR-0016/0015/0014/0013: Forced-Command mit fester
Befehlskonstante, Parser mit Positivliste, Außenkontakte nur lesend und opt-in, jeder weitere
SSH-Befehl, jedes weitere Außenziel oder jeder weitere nicht-GET-Aufruf braucht ein neues ADR;
`tools.py` als vollständige Fähigkeitsgrenze, `set_switch`-Ausnahme; `unifi_live.py` mit genau einem
lesenden Event-POST). Geändert:
- **WAN aus UniFi:** `unifi_classic_probe.py` liest zusätzlich per GET `stat/device` und
  `rest/networkconf`. Aus `networkconf` bleiben nur `name`, `purpose`, `wan_networkgroup` und `wan_type`;
  Zugangsdaten eines WAN (etwa PPPoE) werden nie übernommen. Nur der aktive Anschluss bekommt eine Adresse.
  Die Zuordnung läuft über den Namen, nicht mehr über die Reihenfolge.
- **Rangfolge der öffentlichen Adresse:** öffentliche Adresse der WAN-Schnittstelle, dann FRITZ!Box, zuletzt
  `geo_info`. Im Test war `geo_info` veraltet (weder Ausgangsadresse noch DNS passten), die FRITZ!Box stimmte.
- **FRITZ!Box optional** (`fritz_wan.py`): genau ein lesender SOAP-POST `GetExternalIPAddress` an den festen
  IGD-Pfad `/igdupnp/control/WANIPConn1`, ohne Zugangsdaten. Nur für Geräte mit FRITZ!Box-Kennung, einem
  Zugang mit `allowProbe` und solange `scanUseCredentials` an ist. Ohne FRITZ!Box entfällt die Quelle.
- **Home-Assistant-WebSocket** erlaubt zusätzlich `system_log/list`, nur als Rückfall, wenn `/api/error_log`
  mit 404 antwortet. Die Ausgabe wird wie das Fehlerlog geschwärzt und begrenzt.
- **`window` ist gesperrt:** `set_switch` bewegt keine Fenster mehr. Erlaubt bleiben `blind`, `shade`,
  `shutter`, `curtain` und `awning`. Ein offenes Fenster ist ein Einbruchs- und Wetterrisiko.

## Konsequenzen
- Die öffentliche Adresse ist auch hinter einem vorgeschalteten Router bekannt, und Hostnamen, die direkt auf
  den Anschluss zeigen, erscheinen in der Doku.
- Ohne vorgeschalteten Router steht die öffentliche Adresse direkt an der Schnittstelle. Bleibt nur `geo_info`,
  erscheint ein Hinweis, dass sie veraltet sein kann; widersprechen sich die Quellen, ebenfalls.
- Reviewer erkennen Verstöße an übernommenen `x_*`-/Passwort-Feldern aus `networkconf`, an einem zweiten
  Aufruf in `fritz_wan.py`, an weiteren WebSocket-Typen oder an `window` in der Rollo-Allowlist.
- ADR-0017 hat den Status „Ersetzt durch ADR-0018“.
