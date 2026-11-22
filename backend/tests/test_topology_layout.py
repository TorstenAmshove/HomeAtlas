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
