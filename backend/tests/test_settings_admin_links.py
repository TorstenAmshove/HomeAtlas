"""Validation of the deep-link settings (portainerUrl, portainerEnvId, proxmoxWebUrl)."""
import pytest
from fastapi.testclient import TestClient

from app import auth, db, main


@pytest.fixture()
def client(temp_db):
    role = {"v": auth.ROLE_ADMIN}
    main.app.dependency_overrides[main.current_user] = lambda: {"role": role["v"]}
    c = TestClient(main.app)
    c.role = role
    try:
        yield c
    finally:
        main.app.dependency_overrides.clear()


def _patch(client, **body):
    return client.patch("/api/settings", json=body)


@pytest.mark.parametrize("field", ["portainerUrl", "proxmoxWebUrl"])
@pytest.mark.parametrize("raw,stored", [
    ("https://h:9443/", "https://h:9443"),
    ("HTTP://h", "http://h"),
    ("  https://h///  ", "https://h"),
    ("https://h/pve/", "https://h/pve"),
    ("", ""),
])
def test_url_is_normalized(client, field, raw, stored):
    r = _patch(client, **{field: raw})
    assert r.status_code == 200
    assert r.json()["settings"][field] == stored


@pytest.mark.parametrize("field", ["portainerUrl", "proxmoxWebUrl"])
@pytest.mark.parametrize("bad", [
    "ftp://h", "javascript:alert(1)", "data:text/html,x", "file:///etc/passwd", "h:9443", "h",
    "https://user:pw@h", "https://h?x=1", "https://h#frag", "https://h x", "https://",
])
def test_bad_url_rejected(client, field, bad):
    assert _patch(client, **{field: bad}).status_code == 422


@pytest.mark.parametrize("value,ok", [("1", True), ("12", True), ("", True), ("-1", False),
                                      ("1.5", False), ("²", False), ("a", False), (" 1", False)])
def test_env_id_digits_only(client, value, ok):
    r = _patch(client, portainerEnvId=value)
    assert (r.status_code == 200) is ok


def test_unknown_key_still_rejected_and_round_trip_unchanged(client):
    assert _patch(client, nope="x").status_code == 422
    first = client.get("/api/settings").json()["settings"]
    assert client.patch("/api/settings", json={k: first[k] for k in
                        ("portainerUrl", "portainerEnvId", "proxmoxWebUrl")}).status_code == 200
    assert client.get("/api/settings").json()["settings"] == first


def test_member_cannot_read_or_write(client):
    db.update_settings({"portainerUrl": "https://p"})
    client.role["v"] = auth.ROLE_MEMBER
    settings = client.get("/api/settings").json()["settings"]
    assert not {"portainerUrl", "portainerEnvId", "proxmoxWebUrl"} & settings.keys()
    assert _patch(client, portainerUrl="https://x").status_code == 403
