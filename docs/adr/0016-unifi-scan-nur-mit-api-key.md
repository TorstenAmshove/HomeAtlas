# ADR-0016: Scan der klassischen UniFi-API nur mit API-Key

- **Status:** Ersetzt durch ADR-0017; ersetzte ADR-0015
- **Datum:** 2026-11-22

## Kontext
ADR-0014 erlaubte für den Portweiterleitungs-/WAN-Scan (`unifi_classic_probe.py`) genau einen
Login-POST (`/api/auth/login`) mit einem eigenen lokalen „View Only“-Benutzer. ADR-0015 zeigte für den
Live-Zugriff (#104), dass die klassische API den Integrations-API-Key (`X-API-Key`) akzeptiert. Offen
war nur, ob das auch für `self/sites` und `rest/portforward` gilt (Issue #102).

Spike des Owners gegen UniFi Network 11.0.103 (nur GET mit `X-API-Key`, Basis `/proxy/network`):

| Endpunkt | Status | Nutzen |
|---|---|---|
| `api/self/sites` | 200 | Sitenamen |
| `api/s/<site>/rest/portforward` | 200 | Portweiterleitungen (u. a. `fwd`, `dst_port`, `fwd_port`, `proto`, `enabled`) |
| `api/s/<site>/stat/health` | 200 | WAN-Adresse |

## Entscheidung
Alles aus ADR-0015 gilt unverändert weiter (und damit ADR-0014/0013: Forced-Command-Dateilesen mit
fester Befehlskonstante, Parser mit Allowlist-Feldern, Außenkontakte nur lesend und opt-in, jeder
weitere SSH-Befehl, jedes weitere Außenziel oder jeder weitere nicht-GET-Aufruf braucht ein neues
ADR; `tools.py` als vollständige Fähigkeitsgrenze, `set_switch`-Ausnahme, WebSocket nur
`trace/list`/`trace/get`; `unifi_live.py` mit genau einem lesenden Event-POST). Geändert:
- **Die Login-POST-Ausnahme für den Scan entfällt.** `unifi_classic_probe.py` sendet nur GET mit
  `X-API-Key`, keinen Login, kein Cookie, kein CSRF-Token, folgt keinen Weiterleitungen.
- **Kein eigener Zugang mehr:** Der Scan nutzt die Zugänge der Kategorie `unifi` mit `allowProbe`
  (dieselben wie `unifi_probe.py`) und den Schalter `scanEnableUnifiClassic`. Die Kategorie
  `unifi_classic` entfällt; vorhandene Konten werden bei der Migration kommentarlos gelöscht (nie
  benutzt, gleiche Schritte wie `delete_account`).
- **WAN-Adresse** wird an die WAN-Zeilen der Integration-API desselben Zugangs gehängt (Zuordnung nach
  Reihenfolge, nur bei gleicher Anzahl), damit es eine Zeile je Anschluss gibt.
- **Bewusste Duplizierung:** Die kleine GET-Logik bleibt im Probe-Modul; `unifi_classic_probe.py`
  importiert `unifi_live.py` nicht (Scan und Live-Zugriff bleiben getrennt, ADR-0015).
- **Rechte-Abwägung:** Ein API-Key hat die Rechte seines Erstellers, also mehr als „View Only“. Dafür
  entfällt ein zweites gespeichertes Passwort. Der Code bleibt GET-only mit Feld-Allowlist, Fehlertexte
  enthalten weder Key noch Antwortkörper.

## Konsequenzen
- Ein Zugang „UniFi Network (API-Key)“ mit „Zum Auslesen verwenden“ genügt für Geräte, Portweiterleitungen
  und WAN-Adresse. Wer nur ein `unifi_classic`-Konto hatte, braucht dafür ein `unifi`-Konto.
- Ein Reviewer erkennt Verstöße an einem `post/put/delete/patch/request` in `unifi_classic_probe.py`,
  an `/api/auth/login` oder an einem Import aus `unifi_live`.
- Geltung nur für UniFi Network 11.0.103; 400/404 werden als „Endpunkt nicht verfügbar“ gemeldet.
- ADR-0015 hat den Status „Ersetzt durch ADR-0016“.
