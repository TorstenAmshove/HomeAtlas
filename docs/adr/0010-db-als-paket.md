# ADR-0010: `db` als Paket je Entität, SQL weiterhin nur dort

- **Status:** Akzeptiert, ersetzt ADR-0005
- **Datum:** 2026-11-19

## Kontext
`db.py` war auf ~2.100 Zeilen gewachsen (alle Tabellen in einem Modul). ADR-0005 nannte es
ausdrücklich eine flache Sammlung von Funktionen. Tests patchen Modulattribute
(`db.DB_PATH`, `db._ERROR_EVENT_KEEP`); bei einer bloßen Aufteilung würden solche Patches nicht mehr
auf die Funktionen wirken, die die Werte lesen.

## Entscheidung
Übernommen aus ADR-0005: SQLite (WAL) ist die einzige Datenhaltung, SQL steht nur im Paket `db/`,
kein ORM, eine kurzlebige Verbindung pro Aufruf, camelCase-Spalten, JSON-Spalten zentral über
`_JSON_COLUMNS`, Schema-Erweiterungen über `_ADDED_COLUMNS` in `init_db()`, Tests nutzen `temp_db`.

Neu:
- `backend/app/db/` mit `_core.py` (Verbindung, JSON-Spalten, Schema, `init_db`) und je einem Modul pro
  Entitätsgruppe (`settings`, `users`, `systems`, `network_resources`, `accounts`, `docs`,
  `config_versions`, `error_events`, `scans`, `access_log`, `monitor`, `chats`).
- `db/__init__.py` re-exportiert alle Namen; Aufrufer bleiben `from app import db` / `db.get_system(...)`.
- Importrichtung: Submodule importieren nur aus `_core`; Querverweise nur einseitig
  (`accounts` → `systems`, `config_versions` → `settings`), nie zyklisch.
- `DB_PATH` und `_ERROR_EVENT_KEEP` werden in `db/__init__.py` definiert und zur Laufzeit über das Paket
  gelesen (`_core` in `_conn()`/`init_db()`, `error_events` je Aufruf). Es gibt kein `_core.DB_PATH`.
  Das ist die einzige Abweichung von einem rein mechanischen Verschieben.

## Konsequenzen
- Kein SQL außerhalb von `db/`. Neue Abfragen sind neue Funktionen im Modul ihrer Entität und werden in
  `__init__` exportiert (`tests/test_db_package_api.py` prüft Namen, Pfad-Patch und Duplikate).
- Neue Konstanten, die Tests patchen sollen, gehören nach `db/__init__.py` und werden dort gelesen,
  nicht ins Submodul kopiert. Verstoß im Review: `from .x import DB_PATH` oder ein eigenes `DB_PATH` in `_core`.
