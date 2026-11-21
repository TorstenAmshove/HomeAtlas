import pytest
from fastapi.testclient import TestClient

from app import auth, classify, db, llm_providers, main


@pytest.fixture()
def client(temp_db):
    main.app.dependency_overrides[main.require_admin] = lambda: {"role": auth.ROLE_ADMIN, "username": "a"}
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()


def _mk(**kw):
    return db.create_system({"name": "X", "ip": "192.168.1.5", "kind": "other",
                             "discoveryKey": "ip:192.168.1.5", "openPorts": [80], **kw})


def _provider(monkeypatch, text=None, error=None):
    monkeypatch.setattr(llm_providers, "is_configured", lambda *a: True)

    async def chat(*a, **k):
        if error:
            raise llm_providers.ProviderError(error)
        return type("R", (), {"text": text})()

    monkeypatch.setattr(llm_providers, "chat", chat)

    async def valid(url):
        return True

    monkeypatch.setattr(classify.vendor_docs, "validate", valid)


ANSWER = ('[{"ip":"192.168.1.5","kind":"router","name":"KI","purpose":"Zweck","docUrl":"",'
          '"confidence":"high"}]')


def test_member_forbidden(temp_db):
    main.app.dependency_overrides[main.current_user] = lambda: {"role": auth.ROLE_MEMBER, "username": "m"}
    try:
        assert TestClient(main.app).post("/api/systems/x/classify").status_code == 403
    finally:
        main.app.dependency_overrides.clear()


def test_errors(client, monkeypatch):
    assert client.post("/api/systems/nope/classify").status_code == 404
    c = _mk(extra={"docker": {}}, discoveryKey="d1")
    assert client.post(f"/api/systems/{c['id']}/classify").status_code == 400
    no_ip = _mk(ip="", discoveryKey="d2")
    assert client.post(f"/api/systems/{no_ip['id']}/classify").status_code == 400
    bare = _mk(openPorts=[], discoveryKey="d3")
    assert client.post(f"/api/systems/{bare['id']}/classify").status_code == 400
    s = _mk(discoveryKey="d4")
    monkeypatch.setattr(llm_providers, "is_configured", lambda *a: False)
    r = client.post(f"/api/systems/{s['id']}/classify")
    assert r.status_code == 400 and "kein Zugang" in r.json()["detail"]
    assert db.get_system(s["id"])["kind"] == "other"


def test_provider_error_502(client, monkeypatch):
    s = _mk()
    _provider(monkeypatch, error="kaputt")
    r = client.post(f"/api/systems/{s['id']}/classify")
    assert r.status_code == 502 and db.get_system(s["id"])["kind"] == "other"


def test_low_confidence_unchanged(client, monkeypatch):
    s = _mk()
    _provider(monkeypatch, text='[{"ip":"192.168.1.5","kind":"router","confidence":"low"}]')
    r = client.post(f"/api/systems/{s['id']}/classify")
    assert r.status_code == 200 and r.json()["changed"] is False


def test_success_and_confirmed(client, monkeypatch):
    s = _mk()
    _provider(monkeypatch, text=ANSWER)
    r = client.post(f"/api/systems/{s['id']}/classify")
    assert r.json()["changed"] is True and r.json()["system"]["kind"] == "router"
    conf = _mk(discoveryKey="c1", ip="192.168.1.6", name="Mein Name", confirmed=1)
    _provider(monkeypatch, text=ANSWER.replace("192.168.1.5", "192.168.1.6"))
    r = client.post(f"/api/systems/{conf['id']}/classify").json()["system"]
    assert r["confirmed"] == 1 and r["name"] == "Mein Name" and r["kind"] == "other"
    assert r["purpose"] == "Zweck"
