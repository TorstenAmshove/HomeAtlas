# 3 · Zahlen-Audit (Numbers audit)

Stand: 2026-11-20. Ziel: Jede Zahl, die die neue Oberfläche zeigt, kommt aus **derselben
Abfrage** wie heute. Hier steht, woher jede Zahl kommt und ob sie stimmt.

## Methode

Die Produktions-DB (docker.lan) ist von hier nicht erreichbar. Geprüft wurde daher gegen eine
Wegwerf-SQLite mit 57 zufälligen Geräten (12 kritisch, 2 davon ohne IP), 5 Zugängen:
`docs/redesign/numbers_check.py` ruft die echte Route `routes/overview.dashboard()` auf und
vergleicht jede Zahl mit einem direkten `SELECT COUNT(*)`.

```
OK  counts.total       api= 57 sql= 57
OK  counts.online      api= 31 sql= 31
OK  counts.critical    api= 12 sql= 12
OK  counts.accounts    api=  5 sql=  5
OK  byKind matches GROUP BY kind; sum 57 = total 57
NOTE criticalSystems listed: 10 of critical 12
```

Auf der echten Instanz einmal laufen lassen (ohne Schreibzugriff) bestätigt das mit echten
Daten: gleiche SQL-Statements gegen eine **Kopie** von `homeatlas.db`.

## Zahlen je Seite

| Seite | Anzeige | Quelle | Stimmt? | Anmerkung |
|---|---|---|---|---|
| Übersicht | Geräte insgesamt | `dashboard.counts.total` = `len(db.list_systems())` | ✅ | |
| Übersicht | gerade erreichbar | `counts.online` (status='online') | ✅ | **doppelt** angezeigt (Untertitel + Kachel) |
| Übersicht | kritisch fürs Haus | `counts.critical` (importance='critical') | ✅ | Liste darunter max. 10 → siehe B1 |
| Übersicht | hinterlegte Zugänge | `counts.accounts` = `len(db.list_accounts())` | ✅ | auch für Mitglieder sichtbar (nur Anzahl, kein Secret – ok) |
| Übersicht | — | `counts.offline`, `counts.documented` | ✅ | entfernt (Issue #85), waren geliefert, **nie angezeigt** |
| Übersicht | „Was es im Netz gibt“ je Art | `dashboard.byKind` | ✅ | Summe = total |
| Übersicht | „live · alle N s“ | `settings.monitorIntervalSeconds` | ✅ | siehe B2 |
| Geräte | Treffer der Liste | clientseitig gefiltert aus `GET /api/systems` | ✅ | keine Zahl angezeigt außer „n ausgewählt“ und „(n Container)“ je Compose-Gruppe |
| Geräte | „n Verdachtsfälle“ | `GET /api/systems/duplicates` Länge | ✅ | |
| Gerät | „⚠ n Fehler protokolliert“ | `listSystemErrors` Länge | ✅ | begrenzt durch `_ERROR_EVENT_KEEP` – „n“ ist „n gespeicherte“, nicht „n insgesamt“ |
| Netzplan | „n überwachte Geräte nicht erreichbar“ | `GET /api/monitor` → `systems` mit status='offline' | ✅ | **andere Grundmenge** als das frühere `counts.offline` der Übersicht (inzwischen entfernt, #85) (nur `monitored=1` mit Adresse) – siehe B3 |
| Netzplan | Speedtest Mbit/s, DNS-Zeiten | Live-Messung, nicht gespeichert | n/a | |
| Scan | Fortschritt %, Zusammenfassung | `scans.progress`, `scans.summary` (Text vom Pipeline-Lauf) | ✅ | Zusammenfassung ist Freitext, keine separat gezählte Zahl |
| Doku | Tabellen in Kapiteln | `docs.py` aus `db.list_systems()` | ✅ | Snapshot zum Erzeugungszeitpunkt, nicht live – siehe B4 |

## Befunde

- **B1 Kappung ohne Hinweis.** `criticalSystems` ist `[:10]`, die Kachel sagt 12. Die neue
  Oberfläche zeigt „+2 weitere“ mit Link – **die Abfrage bleibt gleich**, nur die Darstellung
  ergänzt den Rest.
- **B2 „live“ gilt nicht für jedes kritische Gerät.** Überwacht wird nur, was `monitored=1` **und**
  eine IP oder einen Hostnamen hat (`db.list_monitored_systems`). Ein kritisches Gerät ohne Adresse
  steht unter dem „live“-Badge, sein Status stammt aber vom letzten Scan. Fix in der Darstellung:
  bei solchen Geräten „Stand letzter Scan“ statt Status-Chip.
- **B3 Zwei Arten von „nicht erreichbar“.** Übersicht (früher `counts.offline`, inzwischen entfernt, #85) = alle Geräte mit
  status='offline' (auch Handys, die schlafen). Netzplan = nur überwachte Geräte. Die neue
  Übersicht zeigt als Alarm **nur** die überwachten (wie der Netzplan) und die Gesamtzahl ruhig
  daneben, beide mit Beschriftung, damit niemand 9 vs. 2 als Widerspruch liest.
- **B4 Doku-Zahlen sind ein Schnappschuss.** Kapitel nennen „N Geräte“ zum Zeitpunkt der
  Erzeugung. Neue Oberfläche zeigt „Stand: <generatedAt>“ im Kapitelkopf.

## Regel für den Bau

Die neue Oberfläche ruft dieselben Endpunkte (`/api/dashboard`, `/api/monitor`, `/api/systems`)
auf und **rechnet nichts neu**, außer reiner Darstellung (z. B. `total - shown` für „+n weitere“).
Jede Zahl im neuen UI bekommt im PR einen Verweis auf ihr Feld in dieser Tabelle.
