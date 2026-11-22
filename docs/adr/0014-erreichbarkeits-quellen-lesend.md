# ADR-0014: Lesende Erreichbarkeits-Quellen (Forced-Command, Cloudflare, öffentliches DNS)

- **Status:** Akzeptiert, ersetzt ADR-0013
- **Datum:** 2026-11-22

## Kontext
Für die Erreichbarkeits-Ketten (#102: Router-Portweiterleitung, cloudflared, Caddy, Traefik, DynDNS)
muss HomeAtlas Konfigurationsdateien fremder Systeme lesen und zwei Außenkontakte nutzen
(Cloudflare-API, öffentliches DNS). ADR-0013 (und damit ADR-0011/0012) erlaubt SSH nur aus der festen
Befehlsliste von `probe_auth._SSH_COMMANDS` und kennt keinen Dienst außerhalb des LANs.
Die klassische UniFi-API verlangt für einen Portweiterleitungs-Abruf einen Login per POST.

## Entscheidung
Alles aus ADR-0013 gilt unverändert weiter (`tools.py` als vollständige Fähigkeitsgrenze, Secrets
erreichen kein Modell, Live-Diagnosen ohne Shell, Lese-/Schreib-Trennung, WebSocket nur
`trace/list`/`trace/get`, `set_switch`-Ausnahme samt Rollo-Allowlist). Neu:
- **Forced-Command-Dateilesen:** Ein neues Modul `exposure_files.py` liest cloudflared-, Caddy- und
  ddclient-Konfiguration per SSH. Je Quelltyp gibt es genau **eine** Befehlskonstante im Code
  (`_FILE_COMMANDS`), ohne Pfad-Parameter, Interpolation oder Einstellung. Welche Datei geliefert
  wird, bestimmt allein das Zielsystem (`authorized_keys`: `restrict,from="<HomeAtlas-IP>",command="cat <Datei>"`).
  `_SSH_COMMANDS` in `probe_auth.py` bleibt unverändert.
- **Parser behalten nur Allowlist-Felder.** Rohdateien werden nie gespeichert, angezeigt, geloggt
  oder einem Modell gegeben; Passwörter, Tokens, Hashes, Tunnel-Credentials werden verworfen. Dass
  ein Tunnel-Token kurzzeitig im Speicher liegt, wird bewusst hingenommen.
- **Außenkontakte** nur lesend und opt-in (Default aus): Cloudflare-API (nur GET, eigener
  Read-only-Token) und öffentliche DNS-Auflösung per DoH-GET an einen festen Resolver, nur für
  Hostnamen aus gespeicherten Fakten, mit Abfragelimit. Ohne beide funktioniert HomeAtlas voll; der
  Pfadstatus lautet dann „unklar“.
- **UniFi-Ausnahme (nur bei Bedarf):** Liefert die Integration-API keine Portweiterleitungen, darf die
  klassische API mit eigenem „View Only“-Nutzer über einen Login-POST abgefragt werden. Der POST dient
  ausschließlich der Anmeldung (kein Schreibzugriff auf Konfiguration); alle weiteren Aufrufe sind GET.
- Die neuen Quellmodule importieren kein `*_admin`-Modul und werden nicht von `tools.py` importiert;
  `list_exposure` liest nur aus der Datenbank.
- Jeder weitere SSH-Befehl, jedes weitere Außenziel oder jeder weitere nicht-GET-Aufruf braucht ein
  neues ADR.

## Konsequenzen
- Neue Systeme brauchen einen eigenen SSH-Nutzer mit Forced-Command (gehört in die IaC-Repos der
  Zielsysteme, nicht hierher).
- Ein Reviewer erkennt Verstöße an einem Befehl außerhalb der Konstanten, einem Pfad im Befehl, einem
  Nicht-GET-Aufruf außer dem UniFi-Login oder einem Import schreibender Module.
- ADR-0013 hat den Status „Ersetzt durch ADR-0014“.
