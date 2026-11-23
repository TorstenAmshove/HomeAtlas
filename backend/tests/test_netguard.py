import asyncio

import pytest

from app import netguard


@pytest.mark.parametrize("addr", ["10.0.0.1", "172.16.5.5", "192.168.1.1", "fd00::1", "100.64.0.1"])
def test_lan_allowed_by_default_and_blocked_when_disallowed(addr):
    assert netguard.is_forbidden_address(addr) is False
    assert netguard.is_forbidden_address(addr, allow_lan=False) is True


@pytest.mark.parametrize("addr", ["127.0.0.1", "::1", "::ffff:127.0.0.1", "169.254.169.254", "0.0.0.0",
                                  "224.0.0.1", "fe80::1%eth0"])
def test_always_blocked(addr):
    assert netguard.is_forbidden_address(addr)
    assert netguard.is_forbidden_address(addr, allow_lan=False)


def test_public_ok():
    assert not netguard.is_forbidden_address("93.184.216.34", allow_lan=False)


def test_all_resolved_addresses_checked(monkeypatch):
    async def fake(self, host, port, **kw):
        return [(2, 1, 6, "", ("93.184.216.34", 0)), (2, 1, 6, "", ("10.0.0.5", 0))]
    monkeypatch.setattr(asyncio.get_event_loop_policy().__class__, "_unused", None, raising=False)
    loop = asyncio.new_event_loop()
    monkeypatch.setattr(loop, "getaddrinfo", lambda h, p, **kw: _coro(fake(None, h, p)))
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: loop)
    with pytest.raises(netguard.BlockedTarget):
        loop.run_until_complete(netguard.ensure_allowed_target("multi.example", allow_lan=False))
    loop.run_until_complete(netguard.ensure_allowed_target("multi.example", allow_lan=True))
    loop.close()


async def _coro(c):
    return await c
