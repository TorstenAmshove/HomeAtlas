"""probe_homeassistant reads automations as before and ignores printer sensors (issue #228)."""
import asyncio

import httpx

from app import probe_auth
from tests.test_probe_auth_homeassistant import _fake_client


def test_printer_sensors_ignored_automations_kept(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/":
            return httpx.Response(200, json={"message": "API running."})
        if request.url.path.endswith("/api/states"):
            return httpx.Response(200, json=[
                {"entity_id": "automation.a", "state": "on", "attributes": {"friendly_name": "A", "id": "1"}},
                {"entity_id": "sensor.printer_black_toner", "state": "42",
                 "attributes": {"friendly_name": "Toner", "unit_of_measurement": "%"}},
            ])
        return httpx.Response(404)

    _fake_client(monkeypatch, handler)
    result = asyncio.run(probe_auth.probe_homeassistant("http://ha.local:8123", {}))
    assert result["ok"]
    assert "A (ein)" in result["facts"]["automations"]["value"]
    assert "printerSupplies" not in result["facts"]
    assert "Toner" not in str(result["facts"])
