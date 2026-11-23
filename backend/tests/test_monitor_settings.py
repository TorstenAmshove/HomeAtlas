import asyncio

import pytest
from fastapi.testclient import TestClient

from app import monitor as monitor_module


@pytest.mark.parametrize("raw,expected", [
    (4, 5), (5, 5), (600, 600), (601, 600), (0, 5), (-3, 5), (None, 10), ("abc", 10), ("30", 30),
])
def test_effective_interval(raw, expected):
    assert monitor_module.effective_interval({"monitorIntervalSeconds": raw}) == expected


def test_effective_interval_default():
    assert monitor_module.effective_interval({}) == 10


@pytest.mark.parametrize("raw,expected", [
    (199, 0.2), (200, 0.2), (10000, 10.0), (10001, 10.0), (0, 0.2), (-5, 0.2),
    (None, 1.5), ("x", 1.5), (1500, 1.5),
])
def test_effective_timeout(raw, expected):
    assert monitor_module.effective_timeout_s({"monitorTimeoutMs": raw}) == expected


def test_run_round_passes_clamped_timeout(temp_db, monkeypatch):
    temp_db.create_system({"kind": "server", "name": "N", "ip": "10.0.0.40", "monitored": 1})
    seen: list[float] = []

    async def fake_check_system(system, timeout_s):
        seen.append(timeout_s)
        return "online", "x"

    monkeypatch.setattr(monitor_module, "check_system", fake_check_system)
    asyncio.run(monitor_module.Monitor().run_once({"monitorTimeoutMs": 9999999}))
    assert seen == [10.0]


def test_monitor_api_returns_clamped_interval(temp_db):
    from app.main import app
    from app import deps

    app.dependency_overrides[deps.current_user] = lambda: {"id": "u", "role": "ADMIN"}
    try:
        temp_db.update_settings({"monitorIntervalSeconds": 5000})
        client = TestClient(app)
        assert client.get("/api/monitor").json()["intervalSeconds"] == 600
        assert client.get("/api/dashboard").json()["monitorIntervalSeconds"] == 600
    finally:
        app.dependency_overrides.clear()
