# ADR-0013: Rollos per `set_switch`, Tore bleiben gesperrt

- **Status:** Akzeptiert, ersetzt ADR-0012 und ADR-0004
- **Datum:** 2026-11-22

## Kontext
Der Owner möchte den Assistenten Rollos fahren lassen (#99). Die bisherige Ausnahme (ADR-0004,
ADR-0012) erlaubte nur Ein/Aus für Shelly sowie Home-Assistant `switch`/`light`. `cover` umfasst in
Home Assistant aber auch Garagen- und Hoftore; ein per Prompt-Injection ausgelöstes „Garagentor auf“
wäre ein Einbruchsrisiko.

## Entscheidung
Alles aus ADR-0004 und ADR-0012 gilt unverändert weiter (`tools.py` ist die vollständige
Fähigkeitsgrenze, Secrets erreichen nie ein Modell, Live-Diagnosen ohne Shell, Lese-/Schreib-Trennung,
WebSocket nur `trace/list`/`trace/get`). Neu:
- `set_switch` darf zusätzlich Home-Assistant-`cover` mit `open`, `close`, `stop` bewegen
  (`switch_admin.ha_set_cover`). Keine Positionsangabe.
- Zugelassen ist per **Allowlist** nur `device_class` `blind`, `shade`, `shutter`, `curtain`,
  `awning`, `window` (exakter Vergleich nach `strip().lower()`). `garage`, `gate`, `door` und
  Entities ohne `device_class` bleiben gesperrt, auch bei direktem Aufruf mit bekannter `entity_id`.
- Die `device_class` wird unmittelbar vor dem POST live per `GET /api/states/{id}` gelesen. Die Lücke
  zwischen Prüfung und POST wird bewusst hingenommen.
- Alle anderen Domänen (`lock`, `climate`, `alarm_control_panel` …) bleiben gesperrt. `on` gilt nur
  für switch/light/Shelly, `action` nur für `cover`.
- Die Allowlist steht in `switch_admin.py` und, dupliziert (die Leseseite importiert die
  Schreibseite nicht), in `probe_auth.py` für `list_ha_switchables`; ein Test hält beide gleich.
- Die UI-Route `/api/systems/{id}/ha-switch` bleibt bei switch/light.

## Konsequenzen
- Eine weitere Domäne, eine weitere `device_class` oder eine Position braucht ein neues ADR.
- ADR-0004 und ADR-0012 haben den Status „Ersetzt durch ADR-0013“.
