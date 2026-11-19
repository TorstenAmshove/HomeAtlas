"""diagnostics.py had no tests (#44). Covers the SSRF guard (loopback, link-local and friends are
refused, also after a redirect), the response-size cap, and input validation that used to surface
as HTTP 500."""
import asyncio
import threading
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
