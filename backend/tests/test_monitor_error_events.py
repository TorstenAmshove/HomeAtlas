import asyncio

from app import db, monitor as monitor_module


def test_confirmed_down_transition_logs_a_device_error_event(temp_db, monkeypatch):
    system = temp_db.create_system({
        "kind": "server", "name": "NAS", "ip": "10.0.0.30", "monitored": 1, "status": "online",
    })

    async def fake_check_system(sys_arg, timeout_s):
        return "offline", "Weder Ping noch Port 445 erreichbar"

    monkeypatch.setattr(monitor_module, "check_system", fake_check_system)

    mon = monitor_module.Monitor()
    settings = {"monitorTimeoutMs": 1500}
    # First poll only counts a failure (_FAILURES_BEFORE_DOWN = 2) -- not yet a confirmed change.
    asyncio.run(mon.run_once(settings))
    assert db.list_device_error_events(system["id"]) == []

    asyncio.run(mon.run_once(settings))

    events = db.list_device_error_events(system["id"])
    assert len(events) == 1
    assert events[0]["level"] == "warning"
    assert "Weder Ping noch Port 445" in events[0]["message"]
    assert db.get_system(system["id"])["status"] == "offline"


def test_flapping_back_online_does_not_log_an_error_event(temp_db, monkeypatch):
    system = temp_db.create_system({
        "kind": "server", "name": "NAS", "ip": "10.0.0.31", "monitored": 1, "status": "unknown",
    })

    async def fake_check_system(sys_arg, timeout_s):
        return "online", "Antwortet auf Ping"

    monkeypatch.setattr(monitor_module, "check_system", fake_check_system)

    mon = monitor_module.Monitor()
    asyncio.run(mon.run_once({"monitorTimeoutMs": 1500}))

    assert db.list_device_error_events(system["id"]) == []
    assert db.get_system(system["id"])["status"] == "online"


def _status_sequence(monkeypatch, statuses):
    it = iter(statuses)

    async def fake_check_system(sys_arg, timeout_s):
        return next(it), "detail"

    monkeypatch.setattr(monitor_module, "check_system", fake_check_system)


def test_unknown_is_skipped_and_keeps_failure_counter(temp_db, monkeypatch):
    system = temp_db.create_system({
        "kind": "server", "name": "NAS", "ip": "10.0.0.32", "monitored": 1, "status": "online",
    })
    _status_sequence(monkeypatch, ["offline", "unknown", "offline"])
    mon = monitor_module.Monitor()
    settings = {"monitorTimeoutMs": 1500}

    asyncio.run(mon.run_once(settings))
    assert mon.status()["pendingFailures"] == {system["id"]: 1}
    asyncio.run(mon.run_once(settings))
    # unknown neither resets the counter nor flips the status.
    assert mon.status()["pendingFailures"] == {system["id"]: 1}
    assert db.get_system(system["id"])["status"] == "online"
    asyncio.run(mon.run_once(settings))

    assert db.get_system(system["id"])["status"] == "offline"
    assert len(db.list_monitor_events(system["id"])) == 1
    assert len(db.list_device_error_events(system["id"])) == 1


def test_unknown_is_skipped_in_manual_round(temp_db, monkeypatch):
    system = temp_db.create_system({
        "kind": "server", "name": "NAS", "ip": "10.0.0.33", "monitored": 1, "status": "online",
    })
    _status_sequence(monkeypatch, ["unknown"])
    mon = monitor_module.Monitor()

    changes = asyncio.run(mon.run_once({"monitorTimeoutMs": 1500}, manual=True))

    assert changes == []
    assert db.get_system(system["id"])["status"] == "online"
    assert db.list_monitor_events(system["id"]) == []


def test_recovery_logs_no_error_event(temp_db, monkeypatch):
    system = temp_db.create_system({
        "kind": "server", "name": "NAS", "ip": "10.0.0.34", "monitored": 1, "status": "online",
    })
    _status_sequence(monkeypatch, ["offline", "offline", "online"])
    mon = monitor_module.Monitor()
    settings = {"monitorTimeoutMs": 1500}
    for _ in range(2):
        asyncio.run(mon.run_once(settings))
    assert len(db.list_monitor_events(system["id"])) == 1
    assert len(db.list_device_error_events(system["id"])) == 1

    asyncio.run(mon.run_once(settings))

    assert len(db.list_monitor_events(system["id"])) == 2
    assert len(db.list_device_error_events(system["id"])) == 1


def _open(system_id):
    return [e for e in db.list_device_error_events(system_id) if not e["acknowledgedAt"]]


def test_back_online_acknowledges_offline_warnings(temp_db, monkeypatch):
    # #254: the outage warning resolves itself once the device answers again; other events stay open.
    system = temp_db.create_system({
        "kind": "server", "name": "NAS", "ip": "10.0.0.40", "monitored": 1, "status": "online",
    })
    db.add_device_error_event(system["id"], "error", "SSH-Login fehlgeschlagen")
    db.add_device_error_event(system["id"], "warning", "SSH-Befehl Zeitüberschreitung")
    _status_sequence(monkeypatch, ["offline", "offline", "online"])
    mon = monitor_module.Monitor()
    settings = {"monitorTimeoutMs": 1500}
    asyncio.run(mon.run_once(settings))
    asyncio.run(mon.run_once(settings))
    assert db.count_error_events_by_system()[system["id"]] == {"error": 1, "warning": 2}
    asyncio.run(mon.run_once(settings))
    assert db.get_system(system["id"])["status"] == "online"
    assert db.count_error_events_by_system()[system["id"]] == {"error": 1, "warning": 1}
    assert {e["message"] for e in _open(system["id"])} == {"SSH-Login fehlgeschlagen", "SSH-Befehl Zeitüberschreitung"}


def test_online_without_status_change_still_acknowledges(temp_db, monkeypatch):
    system = temp_db.create_system({
        "kind": "server", "name": "NAS", "ip": "10.0.0.41", "monitored": 1, "status": "online",
    })
    db.add_device_error_event(system["id"], "warning", f"{db.OFFLINE_MESSAGE_PREFIX}: alt")
    _status_sequence(monkeypatch, ["online"])
    asyncio.run(monitor_module.Monitor().run_once({"monitorTimeoutMs": 1500}))
    assert _open(system["id"]) == []


def test_unknown_does_not_acknowledge(temp_db, monkeypatch):
    system = temp_db.create_system({
        "kind": "server", "name": "NAS", "ip": "10.0.0.42", "monitored": 1, "status": "offline",
    })
    db.add_device_error_event(system["id"], "warning", f"{db.OFFLINE_MESSAGE_PREFIX}: alt")
    _status_sequence(monkeypatch, ["unknown"])
    asyncio.run(monitor_module.Monitor().run_once({"monitorTimeoutMs": 1500}))
    assert len(_open(system["id"])) == 1


def test_manual_round_online_acknowledges(temp_db, monkeypatch):
    system = temp_db.create_system({
        "kind": "server", "name": "NAS", "ip": "10.0.0.43", "monitored": 1, "status": "offline",
    })
    db.add_device_error_event(system["id"], "warning", f"{db.OFFLINE_MESSAGE_PREFIX}: alt")
    _status_sequence(monkeypatch, ["online"])
    asyncio.run(monitor_module.Monitor().run_once({"monitorTimeoutMs": 1500}, manual=True))
    assert _open(system["id"]) == []
