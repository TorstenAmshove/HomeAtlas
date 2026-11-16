"""Subnet selection: checked controller networks + free text, with the host-interface fallback."""
import asyncio

from app import discovery


def _net(rid: str, cidr: str, active=1, enabled=1) -> dict:
    return {"id": rid, "kind": "network", "active": active, "enabled": enabled,
            "facts": {"cidr": cidr, "vlanId": 1}}


def test_merges_checked_controller_networks_and_free_text_without_duplicates():
    resources = [_net("a", "192.168.20.0/24"), _net("b", "10.0.0.0/24"), _net("c", "172.16.0.0/24")]
    settings = {"scanControllerNetworkIds": ["a", "b"], "scanSubnets": ["10.0.0.5/24", "192.168.99.0/24"]}
    assert discovery.effective_subnets(settings, resources) == [
        "192.168.20.0/24", "10.0.0.0/24", "192.168.99.0/24"]


def test_falls_back_to_local_subnets_when_nothing_selected(monkeypatch):
    monkeypatch.setattr(discovery, "local_subnets", lambda: ["192.168.1.0/24"])
    assert discovery.effective_subnets({}, [_net("a", "10.0.0.0/24")]) == ["192.168.1.0/24"]


def test_ignores_selected_networks_that_are_inactive_disabled_or_without_cidr(monkeypatch):
    monkeypatch.setattr(discovery, "local_subnets", lambda: ["192.168.1.0/24"])
    resources = [_net("a", "10.0.0.0/24", active=0), _net("b", "10.0.1.0/24", enabled=0),
                 _net("c", ""), _net("d", "fd00::/64"), _net("e", "garbage")]
    settings = {"scanControllerNetworkIds": ["a", "b", "c", "d", "e", "gone"]}
    assert discovery.effective_subnets(settings, resources) == ["192.168.1.0/24"]


def test_free_text_only_behaves_as_before():
    assert discovery.effective_subnets({"scanSubnets": ["192.168.5.0/24", " "]}, []) == ["192.168.5.0/24"]


def _run_discover(monkeypatch, settings, subnets, alive, arp=None):
    async def fake_sweep(addresses, *a, **k):
        return {ip: [] for ip in addresses if ip in alive}

    async def fake_scan(ip, *a, **k):
        return []

    async def fake_dns(ip):
        return ""

    monkeypatch.setattr(discovery, "sweep_hosts", fake_sweep)
    monkeypatch.setattr(discovery, "_scan_ports", fake_scan)
    monkeypatch.setattr(discovery, "reverse_dns", fake_dns)
    monkeypatch.setattr(discovery, "arp_table", lambda: arp or {})
    base = {"scanEnableMdns": False, "scanEnableSsdp": False, "scanEnableHttpBanner": False,
            "scanEnableDocker": False}
    return asyncio.run(discovery.discover({**base, **settings}, lambda *a: None, subnets=subnets))


def test_discover_uses_given_subnets_including_routed_network(monkeypatch):
    result = _run_discover(monkeypatch, {"scanSubnets": ["1.2.3.0/30"]},
                           ["10.99.0.0/29"], alive={"10.99.0.3"})
    assert any(f.get("ip") == "10.99.0.3" for f in result["findings"])


def test_warns_for_subnet_without_any_responding_host(monkeypatch):
    monkeypatch.setattr(discovery, "local_subnets", lambda: ["10.1.0.0/29"])
    result = _run_discover(monkeypatch, {"scanExcludeIps": ["10.2.0.1"]},
                           ["10.1.0.0/29", "10.2.0.0/29"], alive={"10.1.0.2", "10.2.0.1"})
    text = "\n".join(result["warnings"])
    assert "10.2.0.0/29" in text and "geantwortet" in text
    assert "10.1.0.0/29" not in text


def test_arp_hit_counts_as_responding(monkeypatch):
    result = _run_discover(monkeypatch, {}, ["10.3.0.0/29"], alive=set(), arp={"10.3.0.4": "aa:bb:cc:dd:ee:ff"})
    assert not any("geantwortet" in w for w in result["warnings"])


import ipaddress  # noqa: E402


def _nets(*cidrs):
    return [ipaddress.ip_network(c) for c in cidrs]


def test_routed_subnet_warnings_one_per_routed_subnet():
    out = discovery.routed_subnet_warnings(
        _nets("192.168.1.0/24", "10.20.0.0/24", "10.30.0.0/24"), ["192.168.1.0/24"])
    assert len(out) == 2
    assert "10.20.0.0/24" in out[0] and "docs/multi-vlan.md" in out[0]


def test_routed_subnet_warnings_local_none_duplicates_once_and_unknown_local_none():
    assert discovery.routed_subnet_warnings(_nets("192.168.1.0/24"), ["192.168.1.0/24"]) == []
    assert len(discovery.routed_subnet_warnings(_nets("10.9.0.0/24", "10.9.0.0/24"), ["192.168.1.0/24"])) == 1
    assert discovery.routed_subnet_warnings(_nets("10.9.0.0/24"), []) == []


def test_discover_warns_once_per_routed_subnet(monkeypatch):
    monkeypatch.setattr(discovery, "local_subnets", lambda: ["192.168.1.0/24"])
    result = _run_discover(monkeypatch, {}, ["192.168.1.0/30", "10.99.0.0/29", "10.98.0.0/29"],
                           alive={"192.168.1.1", "10.99.0.3"})
    routed = [w for w in result["warnings"] if "nur geroutet" in w]
    assert len(routed) == 2
    assert not any("geroutetes Netz?" in w and "10.99.0.0" in w for w in result["warnings"])
    assert sum("10.98.0.0/29" in w for w in result["warnings"]) == 1
    assert not any("192.168.1.0/30" in w for w in result["warnings"])


def _boom():
    raise AssertionError("local_subnets must not be called")


def test_selected_subnets_reports_source_name_and_vlan(monkeypatch):
    monkeypatch.setattr(discovery, "local_subnets", _boom)
    resources = [{**_net("a", "192.168.20.0/24"), "name": "IoT"}, _net("b", "10.0.0.0/24")]
    settings = {"scanControllerNetworkIds": ["a"], "scanSubnets": ["10.0.0.5/24", "192.168.20.7/24", "bad"]}
    assert discovery.selected_subnets(settings, resources) == [
        {"cidr": "192.168.20.0/24", "source": "controller", "name": "IoT", "vlan": 1},
        {"cidr": "10.0.0.0/24", "source": "freitext"},
        {"cidr": "bad", "source": "freitext"},
    ]


def test_selected_subnets_empty_and_stale_selection(monkeypatch):
    monkeypatch.setattr(discovery, "local_subnets", _boom)
    resources = [_net("a", "10.0.0.0/24", active=0), _net("b", "10.0.1.0/24", enabled=0), _net("c", "")]
    assert discovery.selected_subnets({}, resources) == []
    assert discovery.selected_subnets(
        {"scanControllerNetworkIds": "a", "scanSubnets": [" "]}, resources) == []
    assert discovery.selected_subnets(
        {"scanControllerNetworkIds": ["a", "b", "c", "gone"]}, resources) == []


def test_selected_subnets_duplicate_keeps_controller_position():
    resources = [_net("a", "10.0.0.0/24")]
    result = discovery.selected_subnets(
        {"scanControllerNetworkIds": ["a"], "scanSubnets": ["10.0.0.0/24"]}, resources)
    assert [e["source"] for e in result] == ["controller"]
