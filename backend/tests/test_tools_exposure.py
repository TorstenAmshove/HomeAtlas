import asyncio
import json

from app import db, tools


def _call(args=None):
    return json.loads(asyncio.run(tools.dispatch("list_exposure", args or {})))


def _facts():
    db.replace_exposure_facts("cloudflared", "a", [{"kind": "tunnel_ingress", "key": "x", "data": {
        "host": "app2.example.net", "origin": "http://192.0.2.20:8080", "via": "192.0.2.30"}}])


def test_empty(temp_db):
    out = _call()
    assert out["hasData"] is False and out["chains"] == []


def test_chain_and_host_filter_without_secrets(temp_db):
    _facts()
    out = _call({"host": "app2"})
    assert out["chains"][0]["host"] == "app2.example.net"
    text = json.dumps(out)
    assert "sourceAccountId" not in text and "\"a\"" not in text
    assert _call({"host": "nope"})["chains"] == []


def test_truncation_hint(temp_db):
    db.replace_exposure_facts("cloudflared", "a", [{"kind": "tunnel_ingress", "key": str(i), "data": {
        "host": f"h{i}.example.net", "origin": "http://192.0.2.20:80", "via": ""}} for i in range(20)])
    out = _call()
    assert len(out["chains"]) == 15 and "gekürzt" not in out and "truncated" in out


def test_system_route_rows(temp_db):
    from app import exposure
    data = {"chains": [{"host": "a.example.net", "paths": [{"sourceLabel": "Tunnel", "status": "aktiv", "mtls": False,
            "steps": [{"systems": [{"id": "s1"}]}]}]}], "internal": [], "portforwards": []}
    assert exposure.for_system(data, "s1")[0]["scope"] == "extern"
    assert exposure.for_system(data, "other") == []
