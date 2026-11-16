"""mDNS/SSDP-Fehler dürfen den Scan nicht abbrechen (Issue #17, ENOBUFS)."""
from __future__ import annotations

import asyncio
import sys
import types

import pytest

from app import discovery

IP_ADDR = """\
1: lo    inet 127.0.0.1/8 scope host lo
2: eth0    inet 192.168.42.5/24 brd 192.168.42.255 scope global eth0
2: eth0    inet 192.168.42.6/24 brd 192.168.42.255 scope global secondary eth0
3: eth1    inet 10.0.0.2/24 brd 10.0.0.255 scope global eth1
4: docker0    inet 172.17.0.1/16 scope global docker0
5: eth2    inet 169.254.1.1/16 scope link eth2
"""


def _fake_zeroconf(monkeypatch, create_error=None, find_error=None, captured=None):
    class FakeZeroconf:
        def __init__(self, *args, **kwargs):
            if captured is not None:
                captured.update(kwargs)
            if create_error:
                raise create_error

        def close(self):
            pass

    class FakeTypes:
        @staticmethod
        def find(zc=None, timeout=5):
            if find_error:
                raise find_error
            return []

    module = types.SimpleNamespace(
        Zeroconf=FakeZeroconf, ZeroconfServiceTypes=FakeTypes,
        ServiceBrowser=object, ServiceListener=object,
    )
    monkeypatch.setitem(sys.modules, "zeroconf", module)


@pytest.fixture(autouse=True)
def _no_host_probing(monkeypatch):
    monkeypatch.setattr(discovery, "_run", lambda cmd, timeout=8.0: IP_ADDR if "addr" in cmd else "")


def test_mdns_oserror_on_create_returns_empty_with_warning(monkeypatch):
    _fake_zeroconf(monkeypatch, create_error=OSError(105, "No buffer space available"))
    result, warnings = discovery._probe_mdns_blocking(0.1, ["192.168.42.0/24"])
    assert result == {}
    assert len(warnings) == 1
    assert "mDNS" in warnings[0] and "übersprungen" in warnings[0]


def test_mdns_oserror_in_browse_also_warns(monkeypatch):
    _fake_zeroconf(monkeypatch, find_error=OSError(105, "No buffer space available"))
    result, warnings = discovery._probe_mdns_blocking(0.1, ["192.168.42.0/24"])
    assert result == {}
    assert any("mDNS" in w for w in warnings)


def test_mdns_warning_contains_diagnosis(monkeypatch):
    monkeypatch.setattr(discovery, "_read_igmp_limit", lambda: "20")
    hint = discovery._mdns_error_hint(OSError(105, "No buffer space available"), 42)
    assert "42" in hint and "igmp_max_memberships" in hint and "20" in hint


def test_mdns_warning_tolerates_missing_or_garbled_igmp_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(discovery, "_IGMP_LIMIT_PATH", str(tmp_path / "missing"))
    assert discovery._read_igmp_limit() == ""
    garbled = tmp_path / "g"
    garbled.write_text("abc")
    monkeypatch.setattr(discovery, "_IGMP_LIMIT_PATH", str(garbled))
    assert discovery._read_igmp_limit() == ""
    assert "No buffer" in discovery._mdns_error_hint(OSError(105, "No buffer space available"), 3)


def test_mdns_warning_other_errno_is_not_called_enobufs():
    hint = discovery._mdns_error_hint(OSError(13, "Permission denied"), 3)
    assert "Permission denied" in hint
    assert "igmp_max_memberships" not in hint


def test_mdns_limits_interfaces_to_scanned_subnets(monkeypatch):
    captured: dict = {}
    _fake_zeroconf(monkeypatch, captured=captured)
    discovery._probe_mdns_blocking(0.1, ["192.168.42.0/24"])
    assert captured["interfaces"] == ["192.168.42.5", "192.168.42.6"]


def test_mdns_falls_back_to_default_with_warning_when_no_interface_matches(monkeypatch):
    captured: dict = {}
    _fake_zeroconf(monkeypatch, captured=captured)
    _, warnings = discovery._probe_mdns_blocking(0.1, ["10.9.9.0/24", "bogus"])
    assert "interfaces" not in captured
    assert any("alle Interfaces" in w for w in warnings)


def test_local_interface_ips_without_ip_binary(monkeypatch):
    monkeypatch.setattr(discovery, "_run", lambda cmd, timeout=8.0: "")
    assert discovery._local_interface_ips(["192.168.42.0/24"]) == []
    captured: dict = {}
    _fake_zeroconf(monkeypatch, captured=captured)
    discovery._probe_mdns_blocking(0.1, ["192.168.42.0/24"])
    assert "interfaces" not in captured


def test_local_subnets_still_filters(monkeypatch):
    assert discovery.local_subnets() == ["192.168.42.0/24", "10.0.0.0/24"]


def _patch_discover(monkeypatch, mdns, ssdp):
    async def sweep(addresses, *a, **k):
        return {"192.168.42.9": []}

    async def ports(*a, **k):
        return [80]

    async def rdns(ip):
        return "host"

    async def banner(ip, p):
        return {}

    monkeypatch.setattr(discovery, "sweep_hosts", sweep)
    monkeypatch.setattr(discovery, "arp_table", lambda: {})
    monkeypatch.setattr(discovery, "_scan_ports", ports)
    monkeypatch.setattr(discovery, "reverse_dns", rdns)
    monkeypatch.setattr(discovery, "http_banner", banner)
    monkeypatch.setattr(discovery, "probe_mdns", mdns)
    monkeypatch.setattr(discovery, "probe_ssdp", ssdp)


def _run_discover(settings):
    base = {"scanSubnets": ["192.168.42.0/24"]}
    return asyncio.run(discovery.discover({**base, **settings}, lambda *a, **k: None))


def test_discover_survives_mdns_and_ssdp_errors(monkeypatch):
    async def boom(*a, **k):
        raise OSError(105, "No buffer space available")

    _patch_discover(monkeypatch, boom, boom)
    result = _run_discover({})
    assert result["findings"]
    assert any("mDNS" in w for w in result["warnings"])
    assert any("SSDP" in w for w in result["warnings"])


def test_discover_only_one_source_fails(monkeypatch):
    async def ok_mdns(*a, **k):
        return {}, ["mDNS Hinweis"]

    async def boom(*a, **k):
        raise OSError("kaputt")

    _patch_discover(monkeypatch, ok_mdns, boom)
    result = _run_discover({})
    assert "mDNS Hinweis" in result["warnings"]
    assert any("SSDP" in w for w in result["warnings"])
    assert result["findings"]


def test_discover_sources_disabled(monkeypatch):
    async def never(*a, **k):
        raise AssertionError("darf nicht laufen")

    _patch_discover(monkeypatch, never, never)
    result = _run_discover({"scanEnableMdns": False, "scanEnableSsdp": False})
    assert result["findings"]
