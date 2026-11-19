import inspect

from app import discovery

SSDP = [{"description": {"friendlyName": "Fritz Repeater"}}]
MDNS = [{"name": "Küche", "type": "_http._tcp"}]


def test_best_name_with_source_priority():
    f = discovery._best_name_with_source
    assert f("10.0.0.5", "host.lan", MDNS, SSDP, {"title": "T"}, "Acme") == ("Fritz Repeater", "upnp")
    assert f("10.0.0.5", "host.lan", MDNS, [], {"title": "T"}, "Acme") == ("Küche", "mdns")
    assert f("10.0.0.5", "host.lan", [], [], {"title": "T"}, "Acme") == ("host", "hostname")
    assert f("10.0.0.5", "", [], [], {"title": "T"}, "Acme") == ("T", "title")
    assert f("10.0.0.5", "", [], [], {}, "Acme Corp") == ("Acme (5)", "vendor")
    assert f("10.0.0.5", "", [], [], {}, "") == ("10.0.0.5", "ip")


def test_best_name_wrapper_unchanged():
    assert len(inspect.signature(discovery._best_name).parameters) == 6
    assert discovery._best_name("10.0.0.5", "", MDNS, [], {}, "") == "Küche"


def test_shelly_app_name_source():
    assert discovery._apply_shelly_name("x", "hostname", {"name": "Flur", "model": "Plus 1PM"}) == ("Flur", "shelly")


def test_shelly_model_fallback_not_self_reported():
    assert discovery._apply_shelly_name("x", "title", {"model": "Plus 1PM"}) == ("Shelly Plus 1PM", "title")
    assert discovery._apply_shelly_name("x", "title", {}) == ("x", "title")
