from app import db


def _found(**kw):
    return {"discoveryKey": "ip:192.168.1.50", "ip": "192.168.1.50", "name": "Gerät",
            "kind": "other", "extra": {}, **kw}


def test_unknown_finding_has_no_match_and_no_side_effect(temp_db):
    assert db.find_existing_for_discovery(_found()) == (None, "")
    assert db.list_systems() == []


def test_exact_legacy_alias_mac_ip_hostname_matches(temp_db):
    row = db.create_system({"name": "A", "ip": "192.168.1.50", "hostname": "a",
                            "mac": "aa:bb:cc:dd:ee:01", "discoveryKey": "ip:192.168.1.50"})
    assert db.find_existing_for_discovery(_found())[0]["id"] == row["id"]
    legacy = _found(discoveryKey="new:key", ip="", legacyDiscoveryKeys=["ip:192.168.1.50"])
    assert db.find_existing_for_discovery(legacy)[0]["id"] == row["id"]
    by_mac = _found(discoveryKey="x:1", ip="", mac="aa:bb:cc:dd:ee:01")
    assert db.find_existing_for_discovery(by_mac)[0]["id"] == row["id"]
    other = db.create_system({"name": "B", "discoveryKey": "k:b"})
    db.merge_systems(row["id"], other["id"])
    found, via = db.find_existing_for_discovery(_found(discoveryKey="k:b", ip="", ))
    assert found["id"] == row["id"] and via == "k:b"


def test_ai_result_survives_next_scan(temp_db):
    first = _found(kind="router", purpose="KI-Zweck", docUrl="https://x.example/doc",
                   vendor="KI-Vendor", name="KI-Name", importance="critical",
                   extra={"aiConfidence": "high"})
    row, created = db.upsert_discovered_system(first)
    assert created
    rule = _found(kind="other", purpose="Regel", docUrl="https://r.example", vendor="Regel",
                  name="Regel-Name", importance="normal")
    row, created = db.upsert_discovered_system(rule)
    assert not created
    assert (row["kind"], row["purpose"], row["vendor"], row["name"], row["importance"]) == (
        "router", "KI-Zweck", "KI-Vendor", "KI-Name", "critical")
    assert row["docUrl"] == "https://x.example/doc"
    # a source name still wins
    row, _ = db.upsert_discovered_system(_found(name="UniFi-Name", kind="network",
                                                discoverySource="unifi", extra={"unifi": {}}))
    assert row["name"] == "UniFi-Name" and row["kind"] == "network"


def test_rows_without_ai_still_follow_rules(temp_db):
    db.upsert_discovered_system(_found(purpose="alt"))
    row, _ = db.upsert_discovered_system(_found(purpose="neu"))
    assert row["purpose"] == "neu"
