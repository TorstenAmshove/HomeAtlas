import asyncio

from app import monitor as monitor_module

SETTINGS = {"monitorTimeoutMs": 1500}


def _system(temp_db, status="online"):
    return temp_db.create_system({"kind": "server", "name": "NAS", "ip": "10.0.0.40", "monitored": 1, "status": status})


def _fake(monkeypatch, result, state=None):
    async def check(sys_arg, timeout_s):
        if state is not None:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        await asyncio.sleep(0.01)
        if state is not None:
            state["active"] -= 1
        return result["v"], "detail"

    monkeypatch.setattr(monitor_module, "check_system", check)


def test_rounds_do_not_overlap(temp_db, monkeypatch):
    _system(temp_db)
    state = {"active": 0, "peak": 0}
    _fake(monkeypatch, {"v": "online"}, state)
    mon = monitor_module.Monitor()

    async def run():
        await asyncio.gather(mon.run_once(SETTINGS), mon.run_once(SETTINGS, manual=True))

    asyncio.run(run())
    assert state["peak"] == 1


def test_manual_round_does_not_confirm_outage(temp_db, monkeypatch):
    system = _system(temp_db)
    result = {"v": "offline"}
    _fake(monkeypatch, result)
    mon = monitor_module.Monitor()
    asyncio.run(mon.run_once(SETTINGS))  # background miss -> 1
    assert mon._failures[system["id"]] == 1
    asyncio.run(mon.run_once(SETTINGS, manual=True))
    assert mon._failures[system["id"]] == 1
    assert temp_db.get_system(system["id"])["status"] == "online"


def test_manual_round_still_applies_online(temp_db, monkeypatch):
    system = _system(temp_db, status="offline")
    _fake(monkeypatch, {"v": "online"})
    mon = monitor_module.Monitor()
    mon._failures[system["id"]] = 1
    asyncio.run(mon.run_once(SETTINGS, manual=True))
    assert system["id"] not in mon._failures
    assert temp_db.get_system(system["id"])["status"] == "online"


def test_background_still_confirms_after_manual(temp_db, monkeypatch):
    system = _system(temp_db)
    _fake(monkeypatch, {"v": "offline"})
    mon = monitor_module.Monitor()
    asyncio.run(mon.run_once(SETTINGS, manual=True))
    asyncio.run(mon.run_once(SETTINGS, manual=True))
    assert temp_db.get_system(system["id"])["status"] == "online"
    asyncio.run(mon.run_once(SETTINGS))
    assert temp_db.get_system(system["id"])["status"] == "online"
    asyncio.run(mon.run_once(SETTINGS))
    assert temp_db.get_system(system["id"])["status"] == "offline"
