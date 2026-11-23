"""POST /api/setup validates scanSubnets before anything is written."""
import pytest

from app import crypto, db
from tests.test_main_settings_api import _admin_client


@pytest.fixture(autouse=True)
def _key(tmp_path, monkeypatch):
    monkeypatch.setattr(crypto, "_KEY_PATH", tmp_path / "k.key")
    monkeypatch.setattr(crypto, "_cached", None)


def _setup(body):
    client, main = _admin_client()
    try:
        return client.post("/api/setup", json=body)
    finally:
        main.app.dependency_overrides.clear()


def test_setup_invalid_subnet_422_no_side_effects(temp_db):
    home = db.get_settings()["homeName"]
    response = _setup({
        "homeName": "Neu",
        "systems": [{"name": "Router", "kind": "router", "ip": "192.168.1.1"}],
        "accounts": [{"label": "Konto", "secret": "x"}],
        "scanSubnets": ["bad"],
    })
    assert response.status_code == 422
    assert "bad" in response.text
    assert db.list_systems() == [] and db.list_accounts() == []
    settings = db.get_settings()
    assert settings["homeName"] == home and not settings["setupCompleted"]


def test_setup_subnets_trimmed_saved(temp_db):
    response = _setup({"scanSubnets": [" 192.168.1.0/24 ", ""]})
    assert response.status_code == 200
    assert db.get_settings()["scanSubnets"] == ["192.168.1.0/24"]
