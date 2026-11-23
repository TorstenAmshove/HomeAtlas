import asyncio

from app import diagnostics, monitor as monitor_module


def _patch(monkeypatch, reachable):
    async def fake_ping(host, count=1):
        return {"reachable": reachable}

    async def fake_port(host, port, timeout):
        return {"open": False}

    monkeypatch.setattr(diagnostics, "ping", fake_ping)
    monkeypatch.setattr(diagnostics, "check_port", fake_port)


def test_container_without_ports_is_host_only(monkeypatch):
    container = {"kind": "container", "ip": "10.0.0.5", "openPorts": []}
    assert monitor_module.is_host_only(container) is True
    _patch(monkeypatch, True)
    assert asyncio.run(monitor_module.check_system(container, 0.2)) == (
        "online", "Antwortet auf Ping (prüft nur den Host)")
    _patch(monkeypatch, False)
    assert asyncio.run(monitor_module.check_system(container, 0.2)) == (
        "offline", "Host antwortet nicht auf Ping (prüft nur den Host)")


def test_other_systems_are_not_host_only(monkeypatch):
    assert monitor_module.is_host_only({"kind": "container", "openPorts": [8080]}) is False
    assert monitor_module.is_host_only({"kind": "container", "monitorPorts": [9000]}) is False
    other = {"kind": "other", "ip": "10.0.0.6", "openPorts": []}
    assert monitor_module.is_host_only(other) is False
    _patch(monkeypatch, True)
    assert asyncio.run(monitor_module.check_system(other, 0.2)) == ("online", "Antwortet auf Ping")
    _patch(monkeypatch, False)
    assert asyncio.run(monitor_module.check_system(other, 0.2)) == ("offline", "Antwortet nicht auf Ping")
