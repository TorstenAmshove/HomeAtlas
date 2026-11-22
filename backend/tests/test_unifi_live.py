"""unifi_live.py: fixed allowlist, field allowlist, redaction, fixed error texts, import boundary."""
import ast
import asyncio
import logging
from pathlib import Path

import httpx
import pytest

from app import unifi_live

APP = Path(__file__).resolve().parent.parent / "app"
KEY = "sekret-api-key-12345"
URL = "https://unifi.lan"
WLAN = {"mac": "AA:BB:CC:DD:EE:01", "name": "Handy", "ip": "10.0.0.5", "is_wired": False, "signal": -71,
        "tx_retries": 12, "roam_count": 3, "ap_mac": "11:22:33:44:55:66", "essid": "Heim",
        "x_authkey": "GEHEIM1", "guest_token": "GEHEIM2", "unbekannt": "Zusatz", "inform_url": "http://x"}


def _transport(handler):
    return httpx.MockTransport(handler)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _reset():
    yield
    unifi_live._transport = None


def _client(**kw):
    args = dict(macs={"aa:bb:cc:dd:ee:01"}, ips=set(), names=set())
    args.update(kw)
    return run(unifi_live.client_status(URL, KEY, **args))


def test_only_allowlisted_get_paths():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, request.headers.get("x-api-key")))
        return httpx.Response(200, json={"data": [WLAN]})

    unifi_live._transport = _transport(handler)
    _client()
    assert seen == [("GET", "/proxy/network/api/s/default/stat/sta", KEY)]
    for bad in ("../etc", "stat/device", "events"):
        with pytest.raises(ValueError):
            run(unifi_live._request(bad, URL, KEY))
    for site in ("../x", "a b", "x" * 65, 5):
        with pytest.raises(unifi_live.UnifiLiveError):
            run(unifi_live._request("clients", URL, KEY, site))
    assert len(seen) == 1


def test_only_allowlisted_fields():
    unifi_live._transport = _transport(lambda r: httpx.Response(200, json={"data": [WLAN]}))
    result = _client()
    text = str(result)
    assert result["client"]["signal"] == -71 and result["client"]["roam_count"] == 3
    for leaked in ("GEHEIM1", "GEHEIM2", "Zusatz", "inform_url"):
        assert leaked not in text


def test_redaction_strips_key_and_control_chars(caplog):
    entry = {**WLAN, "name": f"Name {KEY}\nzwei"}
    unifi_live._transport = _transport(lambda r: httpx.Response(200, json={"data": [entry]}))
    with caplog.at_level(logging.DEBUG):
        result = _client()
    assert KEY not in str(result) and "\n" not in result["client"]["name"]
    assert KEY not in caplog.text


def test_wired_and_not_connected_hints():
    wired = {**WLAN, "is_wired": True}
    unifi_live._transport = _transport(lambda r: httpx.Response(200, json={"data": [wired]}))
    assert "keine Funkwerte" in _client()["hinweis"]
    unifi_live._transport = _transport(lambda r: httpx.Response(200, json={"data": []}))
    assert _client()["verbunden"] is False


def test_ambiguous_returns_candidates():
    other = {**WLAN, "mac": "aa:bb:cc:dd:ee:02"}
    unifi_live._transport = _transport(lambda r: httpx.Response(200, json={"data": [WLAN, other]}))
    result = _client(macs=set(), names={"handy"})
    assert result["mehrdeutig"] and len(result["kandidaten"]) == 2 and "client" not in result


@pytest.mark.parametrize("status", [401, 403, 404, 405, 429, 500])
def test_status_errors_have_fixed_message(status):
    unifi_live._transport = _transport(lambda r: httpx.Response(status, text=f"roh {KEY}"))
    with pytest.raises(unifi_live.UnifiLiveError) as exc:
        _client()
    assert KEY not in str(exc.value) and "roh" not in str(exc.value)


def test_unreachable_redirect_json_and_type():
    def boom(request):
        raise httpx.ConnectTimeout("timeout " + KEY)

    def refused(request):
        raise httpx.ConnectError("refused " + KEY)

    for handler, expected in [
        (boom, "nicht rechtzeitig"),
        (refused, "nicht erreichbar"),
        (lambda r: httpx.Response(302, headers={"location": "http://evil"}), "leitet weiter"),
        (lambda r: httpx.Response(200, text="kein json"), "Unerwartete"),
        (lambda r: httpx.Response(200, json=[1]), "Unerwartete"),
    ]:
        unifi_live._transport = _transport(handler)
        with pytest.raises(unifi_live.UnifiLiveError) as exc:
            _client()
        assert expected in str(exc.value) and KEY not in str(exc.value)


def test_size_limits_enforced(monkeypatch):
    nested = {**WLAN, "essid": "x" * 5000, "radio": {"a": "b" * 5000}, "bssid": ["c" * 5000] * 50}
    unifi_live._transport = _transport(lambda r: httpx.Response(200, json={"data": [nested]}))
    client = _client()["client"]
    assert len(client["essid"]) == unifi_live.MAX_TEXT
    assert "radio" not in client and "bssid" not in client  # non-scalar values never pass
    monkeypatch.setattr(unifi_live, "MAX_CHARS", 100)
    with pytest.raises(unifi_live.UnifiLiveError, match="zu groß"):
        _client()
    monkeypatch.setattr(unifi_live, "_MAX_BODY", 10)
    with pytest.raises(unifi_live.UnifiLiveError, match="zu groß"):
        _client()


def test_missing_or_short_key_makes_no_request():
    unifi_live._transport = _transport(lambda r: pytest.fail("no request expected"))
    for key in ("", "kurz"):
        with pytest.raises(unifi_live.UnifiLiveError):
            run(unifi_live.client_status(URL, key, macs=set(), ips=set(), names=set()))
    with pytest.raises(unifi_live.UnifiLiveError):
        run(unifi_live.client_status("", KEY, macs=set(), ips=set(), names=set()))


def test_normalize_mac():
    assert unifi_live.normalize_mac("AA-BB-CC-DD-EE-01") == "aa:bb:cc:dd:ee:01"
    assert unifi_live.normalize_mac("aabbccddee01") == "aa:bb:cc:dd:ee:01"
    assert unifi_live.normalize_mac("10.0.0.5") == "" and unifi_live.normalize_mac("Handy") == ""


def _imports(path):
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            found.add(node.module or "")
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
    return found


def test_unifi_live_import_boundary():
    names = _imports(APP / "unifi_live.py")
    assert not {n for n in names if n.endswith("_admin") or "remote_admin" in n or n.startswith("routes")}
    for scan in ("unifi_probe.py", "unifi_classic_probe.py", "pipeline.py"):
        assert "unifi_live" not in _imports(APP / scan)
