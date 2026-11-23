"""diagnostics.py had no tests (#44). Covers the SSRF guard (loopback, link-local and friends are
refused, also after a redirect), the response-size cap, and input validation that used to surface
as HTTP 500."""
import asyncio
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from app import auth, diagnostics, main


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("address, forbidden", [
    ("127.0.0.1", True), ("127.8.9.10", True), ("::1", True), ("169.254.169.254", True),
    ("fe80::1", True), ("0.0.0.0", True), ("224.0.0.251", True), ("::ffff:127.0.0.1", True),
    ("192.168.1.1", False), ("10.0.0.2", False), ("172.16.5.4", False), ("fd00::1", False),
    ("8.8.8.8", False), ("not-an-ip", True),
])
def test_forbidden_addresses(address, forbidden):
    assert diagnostics._is_forbidden_address(address) is forbidden


@pytest.mark.parametrize("url", ["http://127.0.0.1:8281/api/health", "http://localhost/", "http://[::1]/",
                                 "http://169.254.169.254/latest/meta-data/"])
def test_http_check_refuses_host_and_metadata_targets(url):
    with pytest.raises(diagnostics.DiagnosticError):
        run(diagnostics.http_check(url))


def test_check_port_refuses_loopback():
    with pytest.raises(diagnostics.DiagnosticError):
        run(diagnostics.check_port("127.0.0.1", 8281))


@pytest.mark.parametrize("call", [
    lambda: diagnostics.ping("192.168.1.1", "abc"),
    lambda: diagnostics.traceroute("192.168.1.1", "x"),
    lambda: diagnostics.http_check("ftp://router/"),
    lambda: diagnostics.dns_check("heise.de"),
])
def test_invalid_input_is_a_diagnostic_error(call):
    with pytest.raises(diagnostics.DiagnosticError):
        run(call())


# --- against a real local HTTP server ----------------------------------------------------------
# The server listens on 127.0.0.1, which the guard forbids; these tests narrow the forbidden set
# to one fake LAN address so redirects and size limits can be exercised end to end.

class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 -- http.server API
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://10.255.255.1/")
            self.end_headers()
            return
        body = b"<html><head><title>Router  Login</title></head>" + b"x" * (2 * 1024 * 1024)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):
        pass


@pytest.fixture()
def local_server(monkeypatch):
    monkeypatch.setattr(diagnostics, "_is_forbidden_address", lambda a: a == "10.255.255.1")
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


def test_redirect_to_forbidden_target_is_refused(local_server):
    with pytest.raises(diagnostics.DiagnosticError):
        run(diagnostics.http_check(local_server + "/redirect"))


def test_large_page_is_read_only_up_to_the_cap(local_server):
    result = run(diagnostics.http_check(local_server + "/"))
    assert result["reachable"] and result["status"] == 200
    assert result["title"] == "Router Login"


# --- HTTP routes -----------------------------------------------------------------------------

@pytest.fixture()
def client(temp_db):
    main.app.dependency_overrides[main.current_user] = lambda: {
        "id": "m", "role": auth.ROLE_MEMBER, "username": "mia", "totpEnabled": 1}
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()


def test_routes_answer_400_not_500(client):
    assert client.post("/api/diagnostics", json={"tool": "ping", "args": {"host": "192.168.1.1", "count": "abc"}}).status_code == 400
    assert client.post("/api/diagnostics", json={"tool": "http_check", "args": {"url": "http://127.0.0.1:8281/"}}).status_code == 400
    assert client.post("/api/diagnostics/dns", json={"names": "heise.de"}).status_code == 400
    assert client.post("/api/diagnostics/dns", json={"names": ["bad host;"]}).status_code == 400


# --- #120: Speedtest-Sperre, Traceroute-Grenzen ---------------------------------------------------

def test_second_parallel_speedtest_rejected(monkeypatch):
    release = asyncio.Event()
    entered = asyncio.Event()

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            entered.set()
            await release.wait()
            return type("R", (), {"content": b"x"})()

        async def post(self, *a, **k):
            return None

    monkeypatch.setattr(diagnostics.httpx, "AsyncClient", FakeClient)

    async def scenario():
        first = asyncio.create_task(diagnostics.speedtest())
        await entered.wait()
        with pytest.raises(diagnostics.DiagnosticBusy):
            await diagnostics.speedtest()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        # lock was released by the cancellation: a new run starts again
        release.set()
        result = await diagnostics.speedtest()
        assert result["ok"] is True

    run(scenario())


def _latency_client(calls, fail_at=None):
    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, *a, **k):
            calls.append(url)
            if fail_at is not None and len(calls) == fail_at:
                raise diagnostics.httpx.ConnectError("boom")
            size = int(url.rsplit("=", 1)[1])
            return type("R", (), {"content": b"x" * size})()

        async def post(self, *a, **k):
            return None

    return FakeClient


def test_speedtest_latency_is_median_without_connection_setup(monkeypatch):
    calls = []
    monkeypatch.setattr(diagnostics.httpx, "AsyncClient", _latency_client(calls))
    # the warm-up request is not timed at all; only the samples feed the clock (start/stop pairs)
    durations = [0.020, 0.030, 0.025, 0.100, 0.022]
    assert len(durations) == diagnostics._SPEEDTEST_LATENCY_SAMPLES
    ticks = []
    now = 0.0
    for d in durations:  # start/stop pair per latency request
        ticks += [now, now + d]
        now += d + 1.0
    ticks_iter = iter(ticks)
    after = {"t": now}

    def fake_monotonic():
        try:
            return next(ticks_iter)
        except StopIteration:
            after["t"] += 1.0
            return after["t"]

    # replace the module reference, not time.monotonic itself (the event loop uses that too)
    monkeypatch.setattr(diagnostics, "time", types.SimpleNamespace(monotonic=fake_monotonic))
    result = run(diagnostics.speedtest())
    assert result["ok"] is True
    assert result["pingMs"] == 25
    zero = [u for u in calls if u.endswith("bytes=0")]
    assert len(zero) == 1 + diagnostics._SPEEDTEST_LATENCY_SAMPLES
    assert calls.index(next(u for u in calls if not u.endswith("bytes=0"))) == len(zero)


@pytest.mark.parametrize("fail_at", [1, 3])
def test_speedtest_latency_error_returns_not_ok(monkeypatch, fail_at):
    calls = []
    monkeypatch.setattr(diagnostics.httpx, "AsyncClient", _latency_client(calls, fail_at=fail_at))
    result = run(diagnostics.speedtest())
    assert result["ok"] is False and result["pingMs"] is None
    # lock released: a new run works
    monkeypatch.setattr(diagnostics.httpx, "AsyncClient", _latency_client([]))
    assert run(diagnostics.speedtest())["ok"] is True


def test_speedtest_route_returns_429_when_busy(monkeypatch):
    async def busy():
        raise diagnostics.DiagnosticBusy("Es läuft bereits ein Speedtest. Bitte kurz warten.")

    monkeypatch.setattr(diagnostics, "speedtest", busy)
    main.app.dependency_overrides[main.current_user] = lambda: {
        "id": "u1", "role": auth.ROLE_MEMBER, "username": "a", "totpEnabled": 1}
    try:
        response = TestClient(main.app).post("/api/diagnostics/speedtest")
    finally:
        main.app.dependency_overrides.clear()
    assert response.status_code == 429
    assert "Speedtest" in response.json()["detail"]


def test_traceroute_max_two_concurrent(monkeypatch):
    release = asyncio.Event()

    async def fake_run(args, timeout):
        await release.wait()
        return 0, "header\n"

    monkeypatch.setattr(diagnostics, "_run", fake_run)

    async def scenario():
        a = asyncio.create_task(diagnostics.traceroute("192.168.1.1"))
        b = asyncio.create_task(diagnostics.traceroute("192.168.1.2"))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        with pytest.raises(diagnostics.DiagnosticBusy):
            await diagnostics.traceroute("192.168.1.3")
        release.set()
        await asyncio.gather(a, b)
        assert (await diagnostics.traceroute("192.168.1.3"))["host"] == "192.168.1.3"

    run(scenario())


def test_traceroute_route_rate_limit_per_user(monkeypatch):
    from app.routes import diagnostics as route

    async def fake(host, hops=15):
        return {"host": host, "hops": [], "explanation": ""}

    monkeypatch.setattr(diagnostics, "traceroute", fake)
    now = [1000.0]
    monkeypatch.setattr(route, "_TRACEROUTE_LIMITER",
                        route.SlidingWindowLimiter(3, 60, clock=lambda: now[0]))
    user = {"id": "u1", "role": auth.ROLE_MEMBER, "username": "a", "totpEnabled": 1}
    holder = {"u": user}
    main.app.dependency_overrides[main.current_user] = lambda: holder["u"]
    client = TestClient(main.app)
    body = {"tool": "traceroute", "args": {"host": "192.168.1.1"}}
    try:
        for _ in range(3):
            assert client.post("/api/diagnostics", json=body).status_code == 200
        limited = client.post("/api/diagnostics", json=body)
        assert limited.status_code == 429
        assert int(limited.headers["Retry-After"]) >= 1
        holder["u"] = {**user, "id": "u2"}
        assert client.post("/api/diagnostics", json=body).status_code == 200
        # other tools are not limited
        assert client.post("/api/diagnostics", json={"tool": "nope"}).status_code == 400
    finally:
        main.app.dependency_overrides.clear()


def test_tool_dispatch_traceroute_busy_returns_error_text(monkeypatch):
    from app import tools

    async def busy(*a, **k):
        raise diagnostics.DiagnosticBusy("zu viele Traceroutes")

    monkeypatch.setattr(diagnostics, "traceroute", busy)
    result = run(tools.dispatch("traceroute", {"host": "192.168.1.1"}))
    assert "zu viele Traceroutes" in str(result)
