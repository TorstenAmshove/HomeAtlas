"""Channel range validation of the Shelly switch route: out-of-range channels are rejected with
422 before any device access or access-log entry."""
import pytest
from fastapi.testclient import TestClient

from app import auth, crypto, db, main, switch_admin


@pytest.fixture()
def client(temp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(crypto, "_KEY_PATH", tmp_path / "secret.key")
    monkeypatch.setattr(crypto, "_cached", None)
    main.app.dependency_overrides[main.require_admin] = lambda: {"role": auth.ROLE_ADMIN, "username": "admin"}
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()


@pytest.fixture()
def shelly(client, monkeypatch):
    system = db.create_system({"name": "Shelly Flur", "ip": "192.168.1.50", "vendor": "Shelly"})
    calls: list[int] = []
    logged: list[str] = []

    async def fake_set(host, on, channel=0):
        calls.append(channel)
        return {"ok": True}

    monkeypatch.setattr(switch_admin, "shelly_set_switch", fake_set)
    monkeypatch.setattr(db, "log_access", lambda *a, **k: logged.append(a[0] if a else ""))
    return system, calls, logged


@pytest.mark.parametrize("channel", ["-1", "4", "abc"])
def test_invalid_channel_is_422_without_device_access(client, shelly, channel):
    system, calls, logged = shelly
    response = client.post(f"/api/systems/{system['id']}/shelly-switch/on?channel={channel}")
    assert response.status_code == 422
    assert calls == []
    assert logged == []


@pytest.mark.parametrize("channel", [0, 3])
def test_boundary_channels_work(client, shelly, channel):
    system, calls, _ = shelly
    response = client.post(f"/api/systems/{system['id']}/shelly-switch/on?channel={channel}")
    assert response.status_code == 200
    assert calls == [channel]


def test_default_channel_is_zero(client, shelly):
    system, calls, _ = shelly
    assert client.post(f"/api/systems/{system['id']}/shelly-switch/off").status_code == 200
    assert calls == [0]


def test_validation_wins_over_unknown_action(client, shelly):
    system, calls, _ = shelly
    assert client.post(f"/api/systems/{system['id']}/shelly-switch/bogus?channel=9").status_code == 422
    assert calls == []
