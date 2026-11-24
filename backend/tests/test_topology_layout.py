"""Topology plan (#143): status word, legend, overflow/duplicates, stable subnet order, min width."""
import re
import subprocess
import sys

from app import topology


def _mk(db, kind, name, ip, n, **extra):
    return db.create_system({"kind": kind, "name": name, "ip": ip,
                             "discoveryKey": f"k:{n}", **extra})


def _widths(svg):
    return [float(w) for w in re.findall(r'<rect x="[\d.-]+" y="[\d.]+" width="([\d.]+)" height="64"', svg)]


def _viewbox_w(svg):
    return int(re.search(r'viewBox="0 0 (\d+) ', svg).group(1))


def _subnet_plan(db, subnets, reverse=False):
    n = 0
    for base in (reversed(subnets) if reverse else subnets):
        for host in range(10, 13):
            n += 1
            _mk(db, "pc", f"pc{n}", f"{base}.{host}", n)


def test_subnet_sort_key_orders_prefix_after_address():
    keys = sorted(["192.168.10.0/24", "10.0.0.0/26", "unbekanntes Netz", "10.0.0.0/24", "192.168.2.0/24"],
                  key=topology._subnet_sort_key)
    assert keys == ["10.0.0.0/24", "10.0.0.0/26", "192.168.2.0/24", "192.168.10.0/24", "unbekanntes Netz"]


def test_layer3_subnets_sorted_numerically(temp_db):
    for reverse in (False, True):
        for s in temp_db.list_systems():
            temp_db.delete_system(s["id"])
        _subnet_plan(temp_db, ["192.168.10", "10.0.0", "192.168.2"], reverse)
        svg = topology.render_layer3({})
        order = [m for m in re.findall(r"(\d+\.\d+\.\d+\.0/24)", svg)]
        assert order == ["10.0.0.0/24", "192.168.2.0/24", "192.168.10.0/24"]


def test_layer3_order_independent_of_hash_seed():
    code = (
        "import sys, re; from app import topology as t\n"
        "subs = {'192.168.10.0/24','10.0.0.0/24','192.168.2.0/24','172.16.0.0/24'}\n"
        "print(sorted(subs, key=t._subnet_sort_key))"
    )
    outs = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           env={"PYTHONHASHSEED": seed, "PATH": ""}, check=True).stdout
            for seed in ("1", "2", "3")}
    assert len(outs) == 1


def test_layer3_subnet_boxes_have_no_system_id(temp_db):
    _mk(temp_db, "router", "Router", "10.0.0.1", 0)
    _subnet_plan(temp_db, ["10.0.0"])
    svg = topology.render_layer3({})
    assert "10.0.0.0/24" in svg
    assert 'data-system-id="subnet:' not in svg
    assert svg.count("data-system-id=") == 1


def test_box_shows_status_word(temp_db):
    _mk(temp_db, "router", "R-On", "10.0.0.1", 1, status="online")
    _mk(temp_db, "network", "SW-Off", "10.0.0.2", 2, status="offline")
    _mk(temp_db, "network", "SW-Unk", "10.0.0.3", 3, status="unknown")
    svg = topology.render({})
    assert "● erreichbar" in svg and "● nicht erreichbar" in svg and "● unbekannt" in svg
    assert "● unbekannt" in topology.render_layer3({}) or "● erreichbar" in topology.render_layer3({})


def test_layer3_has_legend_and_status(temp_db):
    _mk(temp_db, "router", "Router", "10.0.0.1", 0, status="offline")
    svg = topology.render_layer3({})
    assert "● nicht erreichbar" in svg
    assert 'r="5"' in svg  # legend dots


def test_internet_and_subnet_boxes_have_no_status_word(temp_db):
    _subnet_plan(temp_db, ["10.0.0"])
    assert "●" not in topology.render_layer3({})


def test_critical_router_drawn_once(temp_db):
    r = _mk(temp_db, "router", "Kritischer Router", "10.0.0.1", 1, importance="critical")
    sw = _mk(temp_db, "network", "Kritischer Switch", "10.0.0.2", 2, importance="critical")
    svg = topology.render({})
    assert svg.count(f'data-system-id="{r["id"]}"') == 1
    assert svg.count(f'data-system-id="{sw["id"]}"') == 1


def test_overflow_devices_not_drawn_are_not_in_svg(temp_db):
    for i in range(7):
        _mk(temp_db, "router", f"R{i}", f"10.0.{i}.1", i)
    for i in range(11):
        _mk(temp_db, "network", f"N{i}", f"10.1.{i}.2", 100 + i)
    svg = topology.render({})
    assert svg.count("data-system-id=") == 6 + 10


def test_boundary_counts_fully_drawn(temp_db):
    for i in range(6):
        _mk(temp_db, "router", f"R{i}", f"10.0.{i}.1", i)
    for i in range(10):
        _mk(temp_db, "network", f"N{i}", f"10.1.{i}.2", 100 + i)
    assert topology.render({}).count("data-system-id=") == 16


def test_critical_overflow_beyond_cap(temp_db):
    for i in range(12):
        _mk(temp_db, "server", f"S{i}", f"10.0.0.{10 + i}", i, importance="critical")
    assert topology.render({}).count("data-system-id=") == 10


def test_critical_router_beyond_router_cap_is_drawn_as_critical(temp_db):
    for i in range(6):
        _mk(temp_db, "router", f"A{i}", f"10.0.{i}.1", i)
    extra = _mk(temp_db, "router", "Z-Extra", "10.9.9.1", 50, importance="critical")
    svg = topology.render({})
    assert svg.count(f'data-system-id="{extra["id"]}"') == 1


def test_row_never_narrower_than_min_box_width(temp_db):
    for i in range(14):
        _subnet_plan_n = i * 3
        for host in range(10, 13):
            _mk(temp_db, "pc", f"pc{i}-{host}", f"10.{i}.0.{host}", _subnet_plan_n + host)
    svg = topology.render_layer3({})
    assert min(_widths(svg)) >= 90
    assert _viewbox_w(svg) > 1000


def test_physical_row_min_width_and_small_plan_keeps_width(temp_db):
    _mk(temp_db, "router", "R", "10.0.0.1", 1)
    assert _viewbox_w(topology.render({})) == 1000
    for i in range(10):
        _mk(temp_db, "server", f"S{i}", f"10.0.0.{10 + i}", 10 + i, importance="critical")
    svg = topology.render({})
    assert min(_widths(svg)) >= 90


def test_long_title_truncated_at_min_width(temp_db):
    _mk(temp_db, "router", "Ein-sehr-langer-Routername-der-nicht-passt", "10.0.0.1", 1)
    for i in range(14):
        for host in range(10, 13):
            _mk(temp_db, "pc", f"p{i}{host}", f"10.{i}.0.{host}", i * 20 + host)
    assert "…" in topology.render_layer3({})


def _fill(db, base, count, start=0, **extra):
    for i in range(count):
        _mk(db, "pc", f"{base}-{i}", f"{base}.{20 + i}", f"{base}{start + i}", **extra)


def test_layer3_router_without_gateway_ending(temp_db):
    r = _mk(temp_db, "router", "Router5", "192.168.1.5", "r")
    _fill(temp_db, "192.168.1", 3)
    assert f'data-system-id="{r["id"]}"' in topology.render_layer3({})


def test_layer3_router_without_ip_is_skipped(temp_db):
    r = temp_db.create_system({"kind": "router", "name": "NoIp", "discoveryKey": "k:r"})
    _fill(temp_db, "192.168.1", 3)
    assert f'data-system-id="{r["id"]}"' not in topology.render_layer3({})


def test_layer3_counts_exclude_docker_containers(temp_db):
    _fill(temp_db, "192.168.1", 2)
    _mk(temp_db, "container", "c1", "192.168.1.30", "c1", discoverySource="docker")
    _mk(temp_db, "container", "c2", "192.168.1.30", "c2", discoverySource="unifi+docker")
    assert "192.168.1.0/24" not in topology.render_layer3({})  # only 2 counted -> below threshold
    _mk(temp_db, "pc", "dockerish", "192.168.1.31", "dk", discoverySource="dockerhub")
    assert "3 Geräte" in topology.render_layer3({})


def _days_ago(days):
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_layer3_counts_exclude_long_offline(temp_db):
    _fill(temp_db, "192.168.1", 2)
    old = _mk(temp_db, "pc", "old", "192.168.1.40", "old", discovered=1, status="offline")
    temp_db.update_system(old["id"], {"lastSeen": _days_ago(31)})
    assert "192.168.1.0/24" not in topology.render_layer3({})
    recent = _mk(temp_db, "pc", "recent", "192.168.1.41", "rec", discovered=1, status="offline")
    temp_db.update_system(recent["id"], {"lastSeen": _days_ago(29)})
    assert "3 Geräte" in topology.render_layer3({})


def test_layer3_exact_cidr_beats_24_approximation(temp_db, monkeypatch):
    r = _mk(temp_db, "router", "R", "192.168.1.1", "r")
    _fill(temp_db, "192.168.1", 3)
    monkeypatch.setattr(topology.db, "list_network_resources", lambda **kw: [
        {"ownerSystemId": r["id"], "facts": {"cidr": "192.168.1.0/26"}}])
    svg = topology.render_layer3({})
    assert "192.168.1.0/26" in svg and "192.168.1.0/24" not in svg


# --- edges only from parentId; router subnets from the Linux `ip` fact (#229) ------------------

def _probe(ip_text):
    return {"probe": {"ssh:x": {"ok": True, "facts": {"ip": {"label": "Netzwerkadressen", "value": ip_text}}}}}


def test_router_subnets_from_linux_ip_fact_and_fallback():
    multi = {"ip": "10.0.0.1", "extra": _probe("eth0 10.0.0.1/24\neth1 192.168.5.1/24\nlo 127.0.0.1/8")}
    assert topology._router_subnets(multi) == {"10.0.0.0/24", "192.168.5.0/24"}
    assert topology._router_subnets({"ip": "10.9.9.9", "extra": {}}) == {"10.9.9.0/24"}


def test_router_subnets_ignore_legacy_platform_facts():
    legacy = {"ip": "10.0.0.1", "extra": {"probe": {"ssh:x": {"ok": True, "facts": {
        "ip_addresses": {"label": "x", "value": "172.16.1.1/24"},
        "neighbors": {"label": "x", "value": "identity=sw"},
        "vlan": {"label": "x", "value": "vlan-id=10"},
    }}}}}
    assert topology._router_subnets(legacy) == {"10.0.0.0/24"}


def test_important_device_edge_from_parent_id_and_unknown_parent_falls_back(temp_db):
    router = _mk(temp_db, "router", "GW", "10.0.0.1", 1)
    switch = _mk(temp_db, "network", "SW", "10.0.0.2", 2, parentId=router["id"])
    known = _mk(temp_db, "server", "Srv", "10.0.0.3", 3, parentId=switch["id"], importance="critical")
    orphan = _mk(temp_db, "server", "Orphan", "10.0.0.4", 4, parentId="does-not-exist", importance="critical")
    svg = topology.render()
    assert known["name"] in svg and orphan["name"] in svg
