"""probe_system result bookkeeping (issue #133): every result is kept, a failure next to a working
credential of the same kind is marked `superseded`, HTTP failures and (FRITZ!) TR-064 failures are
stored, and the `login` port rule for SSH is pinned down."""
import asyncio

import pytest

from app import probe_auth
from app.routes import remote


def _ok():
    return {"ok": True, "error": "", "facts": {}}


def _fail(msg="kaputt"):
    return {"ok": False, "error": msg, "facts": {}}


def _acct(label, category, **kw):
    return {"label": label, "category": category, **kw}


def _patch(monkeypatch, *, ssh=None, snmp=None, ha=None, http=None, tr064=None):
    """Each argument maps account label -> result (tr064: a single result)."""
    async def fake_ssh(host, account, platform=""):
        return (ssh or {})[account["label"]]

    async def fake_snmp(host, account, kind=""):
        return (snmp or {})[account["label"]]

    async def fake_ha(url, account):
        return (ha or {})[account["label"]]

    async def fake_http(url, account):
        return (http or {})[account["label"]]

    async def fake_fritz(host, account):
        return tr064 if tr064 is not None else _fail("keine Antwort")

    monkeypatch.setattr(probe_auth, "probe_ssh", fake_ssh)
    monkeypatch.setattr(probe_auth, "probe_snmp", fake_snmp)
    monkeypatch.setattr(probe_auth, "probe_homeassistant", fake_ha)
    monkeypatch.setattr(probe_auth, "probe_http", fake_http)
    monkeypatch.setattr(probe_auth, "probe_fritzbox", fake_fritz)


def _run(system, accounts):
    base = {"ip": "10.0.0.5", "kind": "server", "name": "Host", "vendor": "", "model": ""}
    return asyncio.run(probe_auth.probe_system({**base, **system}, accounts))


def test_failed_ssh_marked_superseded_when_other_ssh_ok(monkeypatch):
    _patch(monkeypatch, ssh={"a": _fail(), "b": _ok()})
    out = _run({}, [_acct("a", "sshkey"), _acct("b", "sshkey")])
    assert out["results"]["ssh:a"]["superseded"] is True
    assert out["results"]["ssh:b"]["ok"] is True
    assert "superseded" not in out["results"]["ssh:b"]


def test_all_failed_kept_not_superseded(monkeypatch):
    _patch(monkeypatch, ssh={"a": _fail(), "b": _fail("anders")})
    out = _run({}, [_acct("a", "sshkey"), _acct("b", "sshkey")])
    assert set(out["results"]) == {"ssh:a", "ssh:b"}
    assert not any(r.get("superseded") for r in out["results"].values())
    assert out["ran"] is True


def test_snmp_superseded(monkeypatch):
    _patch(monkeypatch, snmp={"a": _fail(), "b": _ok()})
    out = _run({}, [_acct("a", "snmp"), _acct("b", "snmp")])
    assert out["results"]["snmp:a"]["superseded"] is True


def test_ha_superseded(monkeypatch):
    _patch(monkeypatch, ha={"old": _fail("Token abgelaufen"), "new": _ok()})
    out = _run({"url": "http://ha.lan:8123"}, [_acct("old", "homeassistant"), _acct("new", "homeassistant")])
    assert out["results"]["ha:old"]["superseded"] is True
    assert out["results"]["ha:old"]["error"] == "Token abgelaufen"


def test_mixed_kinds_http_failure_not_superseded(monkeypatch):
    _patch(monkeypatch, ssh={"s": _ok()}, http={"w": _fail("abgelehnt")})
    out = _run({"url": "http://x.lan"}, [_acct("s", "sshkey"), _acct("w", "login", port=8443)])
    assert "superseded" not in out["results"]["http:w"]
    assert out["results"]["http:w"]["ok"] is False


def test_two_ok_one_failed(monkeypatch):
    _patch(monkeypatch, snmp={"a": _ok(), "b": _ok(), "c": _fail()})
    out = _run({}, [_acct("a", "snmp"), _acct("b", "snmp"), _acct("c", "snmp")])
    assert out["results"]["snmp:c"]["superseded"] is True
    assert "superseded" not in out["results"]["snmp:a"]


def test_failure_without_error_field(monkeypatch):
    _patch(monkeypatch, snmp={"a": {"ok": False, "facts": {}}, "b": _ok()})
    out = _run({}, [_acct("a", "snmp"), _acct("b", "snmp")])
    assert out["results"]["snmp:a"]["superseded"] is True


def test_same_label_same_kind_overwrites(monkeypatch):
    _patch(monkeypatch, snmp={"a": _ok()})
    out = _run({}, [_acct("a", "snmp"), _acct("a", "snmp")])
    assert list(out["results"]) == ["snmp:a"]


@pytest.mark.parametrize("category", ["login", "apikey"])
def test_http_rejection_recorded(monkeypatch, category):
    _patch(monkeypatch, http={"w": _fail("abgelehnt")})
    out = _run({"url": "http://x.lan"}, [_acct("w", category, port=8443)])
    assert out["results"]["http:w"]["ok"] is False
    assert out["results"]["http:w"]["error"] == "abgelehnt"
    assert out["ran"] is True


def test_http_uses_account_url_over_system_url(monkeypatch):
    seen = []

    async def fake_http(url, account):
        seen.append(url)
        return _fail()

    _patch(monkeypatch)
    monkeypatch.setattr(probe_auth, "probe_http", fake_http)
    _run({"url": "http://sys.lan"}, [_acct("w", "apikey", url="http://acc.lan")])
    assert seen == ["http://acc.lan"]


def test_http_error_text_has_no_url_credentials(monkeypatch):
    _patch(monkeypatch, http={"w": _fail("http://admin:geheim@x.lan war nicht erreichbar")})
    out = _run({"url": "http://x.lan"}, [_acct("w", "login", port=8443)])
    assert "geheim" not in out["results"]["http:w"]["error"]
    assert "admin" not in out["results"]["http:w"]["error"]


@pytest.mark.parametrize("field", ["vendor", "model", "name"])
def test_tr064_failure_kept_for_fritz(monkeypatch, field):
    _patch(monkeypatch)
    out = _run({"kind": "router", "name": "Router", field: "FRITZ!Box 7590"}, [])
    assert out["results"]["tr064"]["ok"] is False
    assert "superseded" not in out["results"]["tr064"]


def test_tr064_failure_dropped_for_non_fritz_router(monkeypatch):
    _patch(monkeypatch)
    out = _run({"kind": "router", "name": "Mikrotik"}, [_acct("l", "login", port=8443)])
    assert "tr064" not in out["results"]
    assert out["ran"] is False


def test_tr064_ok_other_failure(monkeypatch):
    _patch(monkeypatch, tr064=_ok(), http={"w": _fail()})
    out = _run({"kind": "router", "name": "FRITZ!Box", "url": "http://fritz.box"}, [_acct("w", "login", port=80)])
    assert out["results"]["tr064"]["ok"] is True
    assert out["results"]["http:w"]["ok"] is False


def test_login_port_8443_not_tried_via_ssh(monkeypatch):
    _patch(monkeypatch, ssh={"l": _ok()})
    out = _run({}, [_acct("l", "login", port=8443)])
    assert out["results"] == {}


@pytest.mark.parametrize("port", [0, 22, None])
def test_login_port_0_and_22_tried(monkeypatch, port):
    _patch(monkeypatch, ssh={"l": _ok()})
    out = _run({}, [_acct("l", "login", port=port)])
    assert "ssh:l" in out["results"]


def test_sshkey_any_port_tried(monkeypatch):
    _patch(monkeypatch, ssh={"k": _ok()})
    out = _run({}, [_acct("k", "sshkey", port=2222)])
    assert "ssh:k" in out["results"]


@pytest.mark.parametrize("category,port,expected", [
    ("login", 8443, False), ("login", 22, True), ("login", 0, True), ("login", None, True),
    ("sshkey", 2222, True), ("sshkey", 22, True), ("apikey", 22, False),
])
def test_ssh_eligible_matches_probe_rule(category, port, expected):
    assert remote._ssh_eligible({"category": category, "port": port}) is expected


def test_derive_purpose_ignores_failures(monkeypatch):
    _patch(monkeypatch, ssh={"a": _fail()})
    out = _run({}, [_acct("a", "sshkey")])
    assert out["purpose"] == ""
