"""POST /api/setup: runs once, needs a homeName, counts accounts, merges by IP (issue #149)."""
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


def test_setup_second_call_409_no_side_effects(temp_db):
    first = _setup({"homeName": "Erst", "systems": [{"name": "R", "kind": "router", "ip": "10.0.0.1"}],
                    "accounts": [{"label": "K", "secret": "x"}], "scanSubnets": ["192.168.1.0/24"]})
    assert first.status_code == 200
    systems, accounts = db.list_systems(), db.list_accounts()
    second = _setup({"homeName": "Zweit", "systems": [{"name": "S", "ip": "10.0.0.2"}],
                     "accounts": [{"label": "K2", "secret": "y"}], "scanSubnets": ["10.0.0.0/24"]})
    assert second.status_code == 409
    assert db.list_systems() == systems and db.list_accounts() == accounts
    settings = db.get_settings()
    assert settings["homeName"] == "Erst" and settings["scanSubnets"] == ["192.168.1.0/24"]


@pytest.mark.parametrize("name", ["", "   "])
def test_setup_empty_home_name_422(temp_db, name):
    response = _setup({"homeName": name, "systems": [{"name": "R"}]})
    assert response.status_code == 422
    assert db.list_systems() == [] and not db.get_settings()["setupCompleted"]


def test_setup_home_name_trimmed(temp_db):
    assert _setup({"homeName": "  Villa  "}).status_code == 200
    assert db.get_settings()["homeName"] == "Villa"


def test_setup_counts_device_accounts(temp_db):
    response = _setup({
        "systems": [{"name": "A", "username": "u", "password": "p"}, {"name": "B"}],
        "accounts": [{"label": "Frei", "secret": "x"}, {"label": " "}],
    })
    assert response.json()["systems"] == 2
    assert response.json()["accounts"] == 2


def _scanned(ip="192.168.1.5", **extra):
    return db.create_system({"name": "scan-name", "kind": "other", "ip": ip, "discovered": 1,
                             "confirmed": 0, "importance": "normal", **extra})


def test_setup_merges_existing_ip(temp_db):
    row = _scanned()
    response = _setup({"systems": [{"name": "Wizard", "kind": "nas", "ip": "192.168.1.5",
                                    "username": "u", "password": "p"}]})
    body = response.json()
    assert (body["systems"], body["merged"], body["accounts"]) == (0, 1, 1)
    rows = db.list_systems()
    assert len(rows) == 1 and rows[0]["id"] == row["id"]
    assert rows[0]["confirmed"] == 1 and rows[0]["discovered"] == 1
    assert rows[0]["name"] == "Wizard" and rows[0]["importance"] == "critical"
    assert db.list_accounts()[0]["systemId"] == row["id"]


def test_setup_merge_keeps_confirmed_name_and_importance(temp_db):
    _scanned(confirmed=1, importance="critical", name="Mein Name")
    _setup({"systems": [{"name": "Wizard", "kind": "pc", "ip": "192.168.1.5"}]})
    (row,) = db.list_systems()
    assert row["name"] == "Mein Name" and row["importance"] == "critical"


def test_setup_no_merge_for_docker_or_ambiguous_ip(temp_db):
    _scanned("10.0.0.7", kind="container")
    _scanned("10.0.0.8")
    _scanned("10.0.0.8")
    response = _setup({"systems": [{"name": "A", "ip": "10.0.0.7"}, {"name": "B", "ip": "10.0.0.8"},
                                   {"name": "C", "ip": " "}]})
    assert response.json()["systems"] == 3 and response.json()["merged"] == 0


def test_setup_same_ip_twice_one_row(temp_db):
    response = _setup({"systems": [{"name": "A", "ip": "10.1.1.1"}, {"name": "B", "ip": "10.1.1.1"}]})
    assert (response.json()["systems"], response.json()["merged"]) == (1, 1)
    assert len(db.list_systems()) == 1


@pytest.mark.parametrize("kind,importance", [
    ("router", "critical"), ("server", "critical"), ("nas", "critical"), ("heating", "critical"),
    ("network", "normal"), ("pc", "normal"), ("other", "normal"), ("xyz", "normal"),
])
def test_setup_critical_kinds(temp_db, kind, importance):
    _setup({"systems": [{"name": "X", "kind": kind}]})
    assert db.list_systems()[0]["importance"] == importance
