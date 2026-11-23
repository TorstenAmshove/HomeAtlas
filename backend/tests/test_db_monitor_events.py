from app import db


def test_monitor_events_capped_per_system(temp_db, monkeypatch):
    monkeypatch.setattr(db, "_MONITOR_EVENT_KEEP", 3)
    a = temp_db.create_system({"kind": "server", "name": "A", "ip": "10.0.0.1"})
    b = temp_db.create_system({"kind": "server", "name": "B", "ip": "10.0.0.2"})
    for i in range(4):  # 4 changes: online, offline, online, offline
        temp_db.record_monitor_state(a["id"], "online" if i % 2 == 0 else "offline", f"A{i}")
    for i in range(3):  # exactly the limit stays untouched
        temp_db.record_monitor_state(b["id"], "online" if i % 2 == 0 else "offline", f"B{i}")

    events_a = temp_db.list_monitor_events(a["id"])
    events_b = temp_db.list_monitor_events(b["id"])

    assert [e["detail"] for e in events_a] == ["A3", "A2", "A1"]
    assert [e["detail"] for e in events_b] == ["B2", "B1", "B0"]
