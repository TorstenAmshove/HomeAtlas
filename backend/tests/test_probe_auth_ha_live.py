"""Live read helpers for Home Assistant (state, history, logbook, error log): GET-only, bounded,
redacted. Nothing here may raise -- every failure comes back as {ok: False, error}."""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import probe_auth

URL = "http://ha.local:8123"
_REAL_CLIENT = httpx.AsyncClient


def _fake_client(monkeypatch, handler, methods: list | None = None) -> None:
    def wrapped(request: httpx.Request) -> httpx.Response:
        if methods is not None:
            methods.append(request.method)
        if request.url.path == "/api/":
            return httpx.Response(200, json={"message": "API running."})
        return handler(request)

    transport = httpx.MockTransport(wrapped)

    real_client = _REAL_CLIENT

    class _FakeAsyncClient(real_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            kwargs.pop("verify", None)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(probe_auth.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(probe_auth, "_decode_secret", lambda account: ("fake-token-123", ""))


def _run(coro):
    return asyncio.run(coro)


# --- Task 1: error mapping ---------------------------------------------------------------------

@pytest.mark.parametrize("status", [401, 404, 500])
def test_ha_get_errors(monkeypatch, status):
    _fake_client(monkeypatch, lambda r: httpx.Response(status, text="boom"))
    result = _run(probe_auth.ha_error_log(URL, {}))
    assert result["ok"] is False and result["error"]
    assert "fake-token-123" not in result["error"]


def test_ha_get_no_url_no_token_bad_json_timeout(monkeypatch):
    assert _run(probe_auth.ha_error_log("", {}))["ok"] is False
    monkeypatch.setattr(probe_auth, "_decode_secret", lambda account: ("", ""))
    assert "Zugriffstoken" in _run(probe_auth.ha_error_log(URL, {}))["error"]

    _fake_client(monkeypatch, lambda r: httpx.Response(200, text="not json"))
    result = _run(probe_auth.ha_get_states(URL, {}))
    assert result["ok"] is False

    def boom(request):
        raise httpx.ConnectTimeout("timeout talking to http://u:secretpw@ha.local with fake-token-123")

    _fake_client(monkeypatch, boom)
    result = _run(probe_auth.ha_get_states(URL, {}))
    assert result["ok"] is False
    assert "secretpw" not in result["error"] and "fake-token-123" not in result["error"]


# --- Task 2: redaction -------------------------------------------------------------------------

def test_redact_patterns():
    r = probe_auth.ha_redact
    assert "abc123" not in r("Authorization: Bearer abc123XYZ")
    assert "abc123" not in r("authorization: bearer abc123XYZ")
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJ4In0.sig-nature_1"
    assert jwt not in r(f"token was {jwt} here")
    assert "hunter2" not in r('{"password": "hunter2"}')
    assert "hunter2" not in r("PASSWORD=hunter2 next")
    assert "hunter2" not in r("api_key: hunter2")
    assert "pass" not in r("http://user:pass@host/x").split("@")[0].replace("http://", "")
    assert "tok123" not in r("http://h/x?access_token=tok123&a=1")
    assert "tok123" not in r("http://h/x?token=tok123")
    assert "[geschwärzt]" in r("password=abc")
    # counter-check: ordinary content survives
    assert r("light.wohnzimmer changed to 21.5") == "light.wohnzimmer changed to 21.5"
    # truncating after redaction leaves no token remainder
    assert "secretvalue" not in r("x" * 50 + " token=secretvalue")[:200]


# --- Task 3: states ----------------------------------------------------------------------------

def test_states_filter_and_attributes(monkeypatch):
    states = [
        {"entity_id": "light.a", "state": "on", "last_changed": "2026-01-01T00:00:00+00:00",
         "attributes": {"friendly_name": "Licht A", "entity_picture": "/x?token=1", "access_token": "z",
                        "brightness": 5}},
        {"entity_id": "sensor.temp", "state": "21", "attributes": {"friendly_name": "Temperatur"}},
    ] + [{"entity_id": f"switch.s{i}", "state": "off", "attributes": {}} for i in range(80)]
    _fake_client(monkeypatch, lambda r: httpx.Response(200, json=states))

    by_id = _run(probe_auth.ha_get_states(URL, {}, entity_ids=["light.a"]))
    assert by_id["ok"] and by_id["count"] == 1
    attrs = by_id["entities"][0]["attributes"]
    assert "entity_picture" not in attrs and "access_token" not in attrs
    assert attrs["brightness"] == 5

    assert _run(probe_auth.ha_get_states(URL, {}, domain="sensor"))["count"] == 1
    assert _run(probe_auth.ha_get_states(URL, {}, query="temperatur"))["count"] == 1
    big = _run(probe_auth.ha_get_states(URL, {}, domain="switch"))
    assert len(big["entities"]) == 50 and big["truncated"] is True and big["count"] == 80


# --- Task 4: history ---------------------------------------------------------------------------

def _hist(now, spec):
    """spec: [(minutes_ago, state)] oldest first."""
    return [{"entity_id": "light.a", "state": s, "last_changed": (now - timedelta(minutes=m)).isoformat(),
             "attributes": {}} for m, s in spec]


def test_history_summary(monkeypatch):
    now = datetime(2026, 1, 8, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(probe_auth, "_utcnow", lambda: now)
    spec = [(60, "off"), (50, "on"), (40, "off"), (30, "on"), (20, "unavailable"), (10, "on")]
    _fake_client(monkeypatch, lambda r: httpx.Response(200, json=[_hist(now, spec)]))
    result = _run(probe_auth.ha_history(URL, {}, "light.a", days=1))
    assert result["ok"]
    summary = result["summary"]
    assert summary["onCount"] == 3  # off->on, off->on, unavailable->on
    assert summary["changes"] == 5
    assert summary["secondsByState"]["on"] == 10 * 60 + 10 * 60 + 10 * 60  # 50-40, 30-20, 10-0
    assert summary["secondsByState"]["unavailable"] == 600
    assert summary["currentState"] == "on"


def test_history_single_and_empty(monkeypatch):
    now = datetime(2026, 1, 8, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(probe_auth, "_utcnow", lambda: now)
    _fake_client(monkeypatch, lambda r: httpx.Response(200, json=[_hist(now, [(30, "on")])]))
    result = _run(probe_auth.ha_history(URL, {}, "light.a", days=1))
    assert result["summary"]["changes"] == 0 and result["summary"]["onCount"] == 0
    assert result["summary"]["secondsByState"]["on"] == 30 * 60  # running phase ends at "now"
    _fake_client(monkeypatch, lambda r: httpx.Response(200, json=[]))
    empty = _run(probe_auth.ha_history(URL, {}, "light.a"))
    assert empty["ok"] and empty["changes"] == []


@pytest.mark.parametrize("days,expected,noted", [(0, 1, False), (-1, 1, False), (8, 7, True),
                                                 ("abc", 7, False), (None, 7, False)])
def test_history_clamps_days_and_limit(monkeypatch, days, expected, noted):
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        return httpx.Response(200, json=[[]])

    _fake_client(monkeypatch, handler)
    result = _run(probe_auth.ha_history(URL, {}, "light.a", days=days, limit=100000))
    assert result["days"] == expected
    assert bool(result.get("truncated")) is noted
    if noted:
        assert "7 Tage" in result["note"]


def test_history_limit_truncates_listing(monkeypatch):
    now = datetime(2026, 1, 8, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(probe_auth, "_utcnow", lambda: now)
    spec = [(100 - i, "on" if i % 2 else "off") for i in range(60)]
    _fake_client(monkeypatch, lambda r: httpx.Response(200, json=[_hist(now, spec)]))
    result = _run(probe_auth.ha_history(URL, {}, "light.a", days=1, limit=5))
    assert len(result["changes"]) == 5 and result["truncated"] is True
    assert "5 von" in result["note"]
    assert result["summary"]["changes"] == 59  # summary covers everything, not just the listing


def test_history_get_only(monkeypatch):
    methods: list = []
    _fake_client(monkeypatch, lambda r: httpx.Response(200, json=[[]]), methods)
    _run(probe_auth.ha_history(URL, {}, "light.a"))
    _run(probe_auth.ha_logbook(URL, {}, "light.a"))
    _run(probe_auth.ha_error_log(URL, {}))
    assert methods and set(methods) == {"GET"}


# --- Task 5: logbook ---------------------------------------------------------------------------

def test_logbook_context_and_limit(monkeypatch):
    entries = [{"when": f"2026-01-0{1 + i % 9}T10:00:00+00:00", "name": "Garage", "message": f"closed {i} token=abc",
                "entity_id": "cover.garage", "context_entity_id": "automation.nachts",
                "context_domain": "automation", "context_service": "trigger", "state": "closed"}
               for i in range(150)]
    _fake_client(monkeypatch, lambda r: httpx.Response(200, json=entries))
    result = _run(probe_auth.ha_logbook(URL, {}, "cover.garage", days=3, limit=1000))
    assert result["ok"] and len(result["entries"]) == 100 and result["truncated"] is True
    first = result["entries"][0]
    assert first["context_entity_id"] == "automation.nachts" and first["context_domain"] == "automation"
    assert "token=abc" not in first["message"]
    assert "100 von 150" in result["note"]


# --- Task 6: error log -------------------------------------------------------------------------

def test_error_log_redacted_and_truncated(monkeypatch):
    lines = [f"2026-01-01 ERROR line {i} " + "x" * 200 for i in range(300)]
    lines[-1] += " Authorization: Bearer topsecrettoken"
    _fake_client(monkeypatch, lambda r: httpx.Response(200, text="\n".join(lines)))
    result = _run(probe_auth.ha_error_log(URL, {}))
    assert result["ok"] and result["truncated"] is True and result["note"]
    assert "topsecrettoken" not in result["text"]
    assert len(result["text"]) <= 20000
    assert "line 299" in result["text"]  # the tail is kept, not the head

    _fake_client(monkeypatch, lambda r: httpx.Response(404, text="no"))
    err = _run(probe_auth.ha_error_log(URL, {}))
    assert err["ok"] is False and "Fehlerlog" in err["error"]
