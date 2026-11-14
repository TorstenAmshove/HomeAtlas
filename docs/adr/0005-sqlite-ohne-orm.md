# ADR-0005: SQLite über ein flaches `db.py`, ohne ORM

- **Status:** Akzeptiert (nachträglich dokumentiert)
- **Datum:** 2026-11-14

## Kontext
Ein Haushalt, eine Instanz, wenige tausend Datensätze. Scans laufen in Worker-Threads
(`asyncio.to_thread`).

## Entscheidung
- SQLite (WAL) ist die einzige Datenhaltung. `db.py` ist der **einzige** Ort, der SQL ausführt –
  eine flache Sammlung von Funktionen, kein ORM.
- Eine kurzlebige Verbindung pro Aufruf statt eines geteilten Handles (Thread-Sicherheit).
- Spaltennamen in camelCase, damit Zeilen ohne Übersetzungsschicht ans Frontend gehen;
  JSON-Spalten werden zentral über `_JSON_COLUMNS` kodiert/dekodiert.
- Schema-Erweiterungen über `_ADDED_COLUMNS` in `init_db()` (idempotent), keine Migrationstools.

## Konsequenzen
- Kein SQL außerhalb von `db.py`. Neue Abfragen sind neue Funktionen dort.
- Tests nutzen die Fixture `temp_db` (eigene Datei pro Test).
