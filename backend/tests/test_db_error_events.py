from app import db


def test_add_and_list_device_error_events(temp_db):
    system = temp_db.create_system({"kind": "network", "name": "Switch"})
    temp_db.add_device_error_event(system["id"], "error", "SSH-Verbindung zu 10.0.0.5:22 fehlgeschlagen: timeout")
    temp_db.add_device_error_event(system["id"], "warning", "Nicht mehr erreichbar: Weder Ping noch Port erreichbar")

    events = temp_db.list_device_error_events(system["id"])

    assert len(events) == 2
    # Most recent first.
    assert events[0]["level"] == "warning"
    assert events[1]["level"] == "error"
    assert "timeout" in events[1]["message"]


def test_add_device_error_event_is_a_noop_without_a_system_id(temp_db):
    assert temp_db.add_device_error_event("", "error", "irrelevant") is None
    assert temp_db.add_device_error_event(None, "error", "irrelevant") is None  # type: ignore[arg-type]


def test_error_events_are_capped_per_device(temp_db, monkeypatch):
    monkeypatch.setattr(db, "_ERROR_EVENT_KEEP", 3)
    system = temp_db.create_system({"kind": "server", "name": "Host"})
    for i in range(10):
        temp_db.add_device_error_event(system["id"], "error", f"Fehler {i}")

    events = temp_db.list_device_error_events(system["id"], limit=100)

    assert len(events) == 3
    assert events[0]["message"] == "Fehler 9"  # newest kept, oldest trimmed


def test_count_error_events_by_system_splits_levels(temp_db):
    a = temp_db.create_system({"kind": "server", "name": "A"})
    b = temp_db.create_system({"kind": "server", "name": "B"})
    c = temp_db.create_system({"kind": "server", "name": "C"})  # no events at all

    temp_db.add_device_error_event(a["id"], "error", "x")
    temp_db.add_device_error_event(a["id"], None, "y")  # normalised to error
    temp_db.add_device_error_event(a["id"], "warning", "w")
    temp_db.add_device_error_event(b["id"], "warning", "z")
    done = temp_db.add_device_error_event(b["id"], "warning", "erledigt")
    temp_db.acknowledge_device_error_events(b["id"], done["id"])

    counts = temp_db.count_error_events_by_system()

    assert counts[a["id"]] == {"error": 2, "warning": 1}
    assert counts[b["id"]] == {"error": 0, "warning": 1}  # acknowledged one counts nowhere
    assert c["id"] not in counts  # the caller defaults to 0


def test_acknowledge_offline_warnings_scopes_and_keeps_timestamp(temp_db):
    s = temp_db.create_system({"kind": "server", "name": "S"})
    other = temp_db.create_system({"kind": "server", "name": "O"})
    prefix = temp_db.OFFLINE_MESSAGE_PREFIX
    old = temp_db.add_device_error_event(s["id"], "warning", f"{prefix}: alt")
    temp_db.acknowledge_device_error_events(s["id"], old["id"])
    first = {e["id"]: e for e in temp_db.list_device_error_events(s["id"])}[old["id"]]["acknowledgedAt"]
    temp_db.add_device_error_event(s["id"], "warning", f"{prefix}: Ping")
    temp_db.add_device_error_event(s["id"], "warning", "SSH-Befehl Zeitüberschreitung")
    temp_db.add_device_error_event(s["id"], "error", f"{prefix}: als Fehler")
    temp_db.add_device_error_event(s["id"], "warning", "Nicht mehr erreichbar%")  # no LIKE widening
    temp_db.add_device_error_event(other["id"], "warning", f"{prefix}: anderes Gerät")

    assert temp_db.acknowledge_offline_warnings(s["id"]) == 2
    assert temp_db.count_error_events_by_system()[s["id"]] == {"error": 1, "warning": 1}
    assert temp_db.count_error_events_by_system()[other["id"]] == {"error": 0, "warning": 1}
    again = {e["id"]: e for e in temp_db.list_device_error_events(s["id"])}[old["id"]]["acknowledgedAt"]
    assert first == again
    assert temp_db.acknowledge_offline_warnings("gibt-es-nicht") == 0


def _two_events(temp_db):
    s = temp_db.create_system({"kind": "server", "name": "H"})
    a = temp_db.add_device_error_event(s["id"], "error", "a")
    b = temp_db.add_device_error_event(s["id"], "error", "b")
    return s, a, b


def test_acknowledge_single_event_sets_timestamp(temp_db):
    s, a, b = _two_events(temp_db)
    assert temp_db.acknowledge_device_error_events(s["id"], a["id"]) == 1
    by_id = {e["id"]: e for e in temp_db.list_device_error_events(s["id"])}
    assert by_id[a["id"]]["acknowledgedAt"]
    assert by_id[b["id"]]["acknowledgedAt"] is None


def test_acknowledge_is_idempotent_and_keeps_first_timestamp(temp_db):
    s, a, _ = _two_events(temp_db)
    temp_db.acknowledge_device_error_events(s["id"], a["id"])
    first = {e["id"]: e for e in temp_db.list_device_error_events(s["id"])}[a["id"]]["acknowledgedAt"]
    assert temp_db.acknowledge_device_error_events(s["id"], a["id"]) == 0
    again = {e["id"]: e for e in temp_db.list_device_error_events(s["id"])}[a["id"]]["acknowledgedAt"]
    assert first == again


def test_acknowledge_all_only_touches_that_device(temp_db):
    s, _, _ = _two_events(temp_db)
    other = temp_db.create_system({"kind": "server", "name": "O"})
    temp_db.add_device_error_event(other["id"], "error", "x")
    assert temp_db.acknowledge_device_error_events(s["id"]) == 2
    assert temp_db.count_error_events_by_system() == {other["id"]: {"error": 1, "warning": 0}}


def test_acknowledge_event_of_other_device_is_untouched(temp_db):
    s, a, _ = _two_events(temp_db)
    other = temp_db.create_system({"kind": "server", "name": "O"})
    assert temp_db.acknowledge_device_error_events(other["id"], a["id"]) == 0
    assert temp_db.count_error_events_by_system()[s["id"]]["error"] == 2


def test_count_ignores_acknowledged_and_new_event_counts_again(temp_db):
    s, a, _ = _two_events(temp_db)
    temp_db.acknowledge_device_error_events(s["id"], a["id"])
    assert temp_db.count_error_events_by_system()[s["id"]]["error"] == 1
    temp_db.acknowledge_device_error_events(s["id"])
    assert s["id"] not in temp_db.count_error_events_by_system()
    temp_db.add_device_error_event(s["id"], "error", "again")
    assert temp_db.count_error_events_by_system()[s["id"]]["error"] == 1


def test_cap_trims_regardless_of_acknowledged(temp_db, monkeypatch):
    monkeypatch.setattr(db, "_ERROR_EVENT_KEEP", 2)
    s = temp_db.create_system({"kind": "server", "name": "H"})
    first = temp_db.add_device_error_event(s["id"], "error", "0")
    temp_db.acknowledge_device_error_events(s["id"], first["id"])
    for i in range(1, 4):
        temp_db.add_device_error_event(s["id"], "error", str(i))
    events = temp_db.list_device_error_events(s["id"], limit=10)
    assert [e["message"] for e in events] == ["3", "2"]


def test_init_db_adds_column_to_legacy_table(temp_db):
    import sqlite3

    s = temp_db.create_system({"kind": "server", "name": "H"})
    con = sqlite3.connect(db.DB_PATH)
    con.execute("DROP TABLE deviceErrorEvents")
    con.execute("CREATE TABLE deviceErrorEvents (id TEXT PRIMARY KEY, systemId TEXT NOT NULL, "
                "level TEXT NOT NULL DEFAULT 'error', message TEXT NOT NULL, createdAt TEXT NOT NULL)")
    con.execute("INSERT INTO deviceErrorEvents VALUES('e1', ?, 'error', 'm', '2024-01-01')", (s["id"],))
    con.commit()
    con.close()
    temp_db.init_db()
    events = temp_db.list_device_error_events(s["id"])
    assert events[0]["acknowledgedAt"] is None
