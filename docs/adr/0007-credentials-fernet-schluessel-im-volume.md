# ADR-0007: Credentials mit Fernet, Schlüssel im selben Volume

- **Status:** Akzeptiert (nachträglich dokumentiert)
- **Datum:** 2026-11-14

## Kontext
HomeAtlas speichert absichtlich Router-, NAS- und WLAN-Zugänge, damit man im Störungsfall
drankommt. Der Dienst muss nach einem Neustart unbeaufsichtigt wieder hochkommen.

## Entscheidung
- Secrets werden mit Fernet (`crypto.py`) verschlüsselt in `accounts.secretEnc` gespeichert; der
  Schlüssel liegt neben der Datenbank im selben Volume.
- Schutzziel: eine abhandengekommene **Datenbankkopie**. Ausdrücklich nicht: root auf dem Host.
- Ein Secret verlässt den Server nur einzeln über `GET /api/accounts/{id}/secret` (nur ADMIN,
  protokolliert). Keine Route gibt Secrets gesammelt oder im Klartext zurück; API-Schlüssel kommen
  maskiert.

## Konsequenzen
- Neue Arten von Zugangsdaten (Tokens, SSH-Schlüssel) laufen über dasselbe verschlüsselte Feld und
  dieselben Regeln.
- Backups müssen `homeatlas.db` und `secret.key` gemeinsam sichern.
- Eine Passphrase beim Start wurde verworfen (kein unbeaufsichtigter Neustart möglich).
