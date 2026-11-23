import asyncio

import httpx
import pytest

from app import netguard, vendor_docs


def run(c):
    return asyncio.run(c)


@pytest.fixture()
def fake_web(monkeypatch):
    """Routes: dict url -> (status, location). Resolution is mocked: hosts named in `bad` are blocked."""
    state = {"routes": {}, "bad": set(), "calls": []}

    async def ensure(host, **kw):
        state["calls"].append(host)
        if host in state["bad"] or netguard.is_forbidden_address(host, allow_lan=False) if _is_ip(host) else host in state["bad"]:
            raise netguard.BlockedTarget(host)

    def handler(request):
        status, loc = state["routes"].get(str(request.url), (200, None))
        return httpx.Response(status, headers={"location": loc} if loc else {})

    real = httpx.AsyncClient
    monkeypatch.setattr(netguard, "ensure_allowed_target", ensure)
    monkeypatch.setattr(vendor_docs.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return state


def _is_ip(h):
    import ipaddress
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        return False


def test_public_ok_returns_true(fake_web):
    assert run(vendor_docs.validate("https://docs.example.com/x")) is True


@pytest.mark.parametrize("url", ["http://127.0.0.1:8281/", "http://192.168.1.1/", "http://[::1]/",
                                 "ftp://example.com/", "file:///etc/passwd",
                                 "http://user:pw@127.0.0.1/", "http://169.254.169.254/"])
def test_internal_or_non_http_start_url_false(fake_web, url):
    assert run(vendor_docs.validate(url)) is False


def test_redirect_to_loopback_false(fake_web):
    fake_web["routes"] = {"https://a.example/": (302, "https://b.example/"),
                          "https://b.example/": (301, "http://127.0.0.1:8281/")}
    assert run(vendor_docs.validate("https://a.example/")) is False


def test_relative_redirect_followed(fake_web):
    fake_web["routes"] = {"https://a.example/x": (302, "/y")}
    assert run(vendor_docs.validate("https://a.example/x")) is True
    assert fake_web["calls"] == ["a.example", "a.example"]


def test_more_than_5_redirects_false(fake_web):
    fake_web["routes"] = {f"https://a.example/{i}": (302, f"/{i + 1}") for i in range(10)}
    assert run(vendor_docs.validate("https://a.example/0")) is False


def test_redirect_without_location_false(fake_web):
    fake_web["routes"] = {"https://a.example/": (302, None)}
    assert run(vendor_docs.validate("https://a.example/")) is False


def test_redirect_to_non_http_false(fake_web):
    fake_web["routes"] = {"https://a.example/": (302, "ftp://x.example/")}
    assert run(vendor_docs.validate("https://a.example/")) is False


def test_blocked_hostname_false(fake_web):
    fake_web["bad"].add("intern.example")
    assert run(vendor_docs.validate("https://intern.example/")) is False
