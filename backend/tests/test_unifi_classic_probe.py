import asyncio

import httpx

from app import unifi_classic_probe as probe_mod


def _run(handler, monkeypatch, **kw):
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr(probe_mod.httpx, "AsyncClient", lambda **k: real(transport=transport, **k))
    return asyncio.run(probe_mod.probe("https://gw", kw.get("user", "ro"), kw.get("pw", "pw-secret-1"), "acc", "sys"))


def _handler(requests, forwards, health):
    def handler(request):
        requests.append(request)
        path = request.url.path
        if path == "/api/auth/login":
            return httpx.Response(200, headers={"X-CSRF-Token": "csrf-secret"}, json={})
        if path.endswith("/self/sites"):
            return httpx.Response(200, json={"data": [{"name": "default", "desc": "Zuhause"}, {"name": "../x"}]})
        if path.endswith("/rest/portforward"):
            return httpx.Response(200, json={"data": forwards})
        if path.endswith("/stat/health"):
            return httpx.Response(200, json={"data": health})
        raise AssertionError(path)
    return handler


def test_reads_forwards_and_wan_with_login_as_only_post(monkeypatch):
    requests: list = []
    fw = [{"name": "Geheim", "enabled": True, "proto": "tcp", "dst_port": "443", "fwd": "192.0.2.20",
           "fwd_port": "8443", "src": "1.2.3.4", "_id": "x"},
          {"enabled": False, "proto": "tcp_udp", "dst_port": "1-5", "fwd": "nonsense", "fwd_port": "1"}]
    result = _run(_handler(requests, fw, [{"subsystem": "wan", "wan_ip": "203.0.113.7", "x_passphrase": "no"},
                                          {"subsystem": "lan"}]), monkeypatch)
    assert result["ok"]
    forwards = [f for f in result["forwards"] if f["kind"] == "portforward"]
    assert [f["data"] for f in forwards] == [
        {"proto": "TCP", "wanPort": "443", "destIp": "192.0.2.20", "destPort": "8443", "enabled": True}]
    assert result["forwards"][-1] == {"kind": "portforward_scan", "key": "scan", "data": {"count": 1}}
    assert result["resources"][0]["facts"] == {"ip": "203.0.113.7"}
    assert result["completeScopes"] == [("default", "wan")]
    assert [r.method for r in requests if r.method != "GET"] == ["POST"]
    assert [r.url.path for r in requests if r.method == "POST"] == ["/api/auth/login"]
    assert "Geheim" not in str(result) and "csrf-secret" not in str(result) and "pw-secret-1" not in str(result)
    assert all(r.headers.get("X-CSRF-Token") == "csrf-secret" for r in requests[1:])


def test_no_forwards_is_a_successful_empty_scan(monkeypatch):
    result = _run(_handler([], [], []), monkeypatch)
    assert result["ok"] and result["forwards"] == [{"kind": "portforward_scan", "key": "scan", "data": {"count": 0}}]


def test_login_rejected_does_not_leak(monkeypatch):
    result = _run(lambda r: httpx.Response(401, text="pw-secret-1"), monkeypatch)
    assert not result["ok"] and "pw-secret-1" not in result["error"]


def test_missing_credentials_make_no_request(monkeypatch):
    result = _run(lambda r: (_ for _ in ()).throw(AssertionError("no request")), monkeypatch, pw="")
    assert not result["ok"]
