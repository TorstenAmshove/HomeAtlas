from app.pipeline import _make_names_unique


def _c(name, ip="192.168.1.20"):
    return {"name": name, "ip": ip, "extra": {"docker": {}}}


def _d(name, ip):
    return {"name": name, "ip": ip, "extra": {}}


def test_distinct_container_names_untouched():
    f = [_c("postgres · immich"), _c("postgres · paperless")]
    _make_names_unique(f)
    assert [x["name"] for x in f] == ["postgres · immich", "postgres · paperless"]


def test_non_containers_get_octet_suffix():
    f = [_d("Shelly", "192.168.1.5"), _d("Shelly", "192.168.1.6")]
    _make_names_unique(f)
    assert [x["name"] for x in f] == ["Shelly (5)", "Shelly (6)"]


def test_container_without_ip_does_not_crash():
    f = [_c("a", ip=""), _c("a", ip="")]
    _make_names_unique(f)
    assert [x["name"] for x in f] == ["a", "a (2)"]


def test_identical_container_names_get_counter_not_octet():
    f = [_c("web · app"), _c("web · app")]
    _make_names_unique(f)
    assert [x["name"] for x in f] == ["web · app", "web · app (2)"]


def test_non_container_without_ip_gets_counter():
    f = [_d("x", ""), _d("x", ""), _d("x", "")]
    _make_names_unique(f)
    assert [x["name"] for x in f] == ["x", "x (2)", "x (3)"]


def test_mixed_with_and_without_ip():
    f = [_d("x", "192.168.1.7"), _d("x", ""), _d("x", "")]
    _make_names_unique(f)
    assert [x["name"] for x in f] == ["x (7)", "x", "x (2)"]
