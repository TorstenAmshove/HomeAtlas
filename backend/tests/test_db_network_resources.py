"""Network-resource synchronization must preserve local notes and never treat partial API data as deletion."""


def _network(name: str, external_id: str = "network-1") -> dict:
    return {
        "kind": "network",
        "source": "unifi",
        "siteExternalId": "site-1",
        "siteName": "Zuhause",
        "externalId": external_id,
        "name": name,
        "enabled": True,
        "ownerSystemId": "gateway-1",
        "facts": {"vlanId": 20, "cidr": "192.168.20.0/24"},
    }


def test_sync_network_resources_preserves_manual_note_while_refreshing_facts(temp_db):
    first = temp_db.sync_network_resources("account-1", [_network("IoT")], [("site-1", "network")])
    resource_id = first[0]["id"]
    temp_db.update_network_resource_manual(resource_id, "Nur fuer Geraete ohne Vertrauen.")

    refreshed = temp_db.sync_network_resources(
        "account-1",
        [{**_network("IoT und Sensoren"), "facts": {"vlanId": 20, "cidr": "10.20.0.0/23"}}],
        [("site-1", "network")],
    )

    assert len(refreshed) == 1
    assert refreshed[0]["id"] == resource_id
    assert refreshed[0]["name"] == "IoT und Sensoren"
    assert refreshed[0]["facts"] == {"vlanId": 20, "cidr": "10.20.0.0/23"}
    assert refreshed[0]["manualMd"] == "Nur fuer Geraete ohne Vertrauen."
    assert refreshed[0]["active"] == 1


def test_sync_network_resources_only_marks_missing_resource_inactive_for_completed_scope(temp_db):
    networks = temp_db.sync_network_resources(
        "account-1", [_network("LAN"), _network("IoT", "network-2")], [("site-1", "network")]
    )

    temp_db.sync_network_resources("account-1", [_network("LAN")], [])
    assert all(resource["active"] == 1 for resource in temp_db.list_network_resources())

    temp_db.sync_network_resources("account-1", [_network("LAN")], [("site-1", "network")])
    by_name = {resource["name"]: resource for resource in temp_db.list_network_resources()}
    assert by_name["LAN"]["active"] == 1
    assert by_name["IoT"]["active"] == 0
    assert {resource["id"] for resource in networks} == {resource["id"] for resource in temp_db.list_network_resources()}


def test_delete_account_keeps_network_resource_and_marks_it_inactive(temp_db):
    account = temp_db.create_account({"label": "UCG", "category": "unifi"})
    resource = temp_db.sync_network_resources(account["id"], [_network("LAN")], [("site-1", "network")])[0]

    temp_db.delete_account(account["id"])

    stored = temp_db.get_network_resource(resource["id"])
    assert stored is not None
    assert stored["active"] == 0
    assert stored["manualMd"] == ""


def _active(temp_db) -> dict[str, int]:
    return {r["name"]: r["active"] for r in temp_db.list_network_resources()}


def test_empty_complete_scope_deactivates_only_after_two_scans(temp_db):
    temp_db.sync_network_resources("account-1", [_network("LAN")], [("site-1", "network")])
    temp_db.sync_network_resources("account-1", [], [("site-1", "network")])
    assert _active(temp_db) == {"LAN": 1}
    temp_db.sync_network_resources("account-1", [], [("site-1", "network")])
    assert _active(temp_db) == {"LAN": 0}


def test_non_empty_scan_resets_empty_counter(temp_db):
    temp_db.sync_network_resources("account-1", [_network("LAN")], [("site-1", "network")])
    temp_db.sync_network_resources("account-1", [], [("site-1", "network")])
    temp_db.sync_network_resources("account-1", [_network("LAN")], [("site-1", "network")])
    temp_db.sync_network_resources("account-1", [], [("site-1", "network")])
    assert _active(temp_db) == {"LAN": 1}


def test_failed_scope_between_empty_scans_keeps_counter(temp_db):
    temp_db.sync_network_resources("account-1", [_network("LAN")], [("site-1", "network")])
    temp_db.sync_network_resources("account-1", [], [("site-1", "network")])
    temp_db.sync_network_resources("account-1", [], [])
    assert _active(temp_db) == {"LAN": 1}
    temp_db.sync_network_resources("account-1", [], [("site-1", "network")])
    assert _active(temp_db) == {"LAN": 0}


def test_three_empty_scans_stay_inactive(temp_db):
    temp_db.sync_network_resources("account-1", [_network("LAN")], [("site-1", "network")])
    for _ in range(3):
        temp_db.sync_network_resources("account-1", [], [("site-1", "network")])
    assert _active(temp_db) == {"LAN": 0}


def test_only_empty_scope_is_counted_when_two_scopes_synced(temp_db):
    wlan = {**_network("WLAN", "wlan-1"), "kind": "wifi"}
    temp_db.sync_network_resources("account-1", [_network("LAN"), wlan],
                                   [("site-1", "network"), ("site-1", "wifi")])
    scopes = [("site-1", "network"), ("site-1", "wifi")]
    for _ in range(2):
        temp_db.sync_network_resources("account-1", [_network("LAN")], scopes)
    assert _active(temp_db) == {"LAN": 1, "WLAN": 0}


def test_reactivation_resets_counter(temp_db):
    temp_db.sync_network_resources("account-1", [_network("LAN")], [("site-1", "network")])
    for _ in range(2):
        temp_db.sync_network_resources("account-1", [], [("site-1", "network")])
    temp_db.sync_network_resources("account-1", [_network("LAN")], [("site-1", "network")])
    assert _active(temp_db) == {"LAN": 1}
    temp_db.sync_network_resources("account-1", [], [("site-1", "network")])
    assert _active(temp_db) == {"LAN": 1}


def test_existing_db_gets_empty_scans_column(temp_db):
    import sqlite3
    with sqlite3.connect(temp_db.DB_PATH) as conn:
        conn.execute("ALTER TABLE networkResources DROP COLUMN emptyScans")
    temp_db.init_db()
    with sqlite3.connect(temp_db.DB_PATH) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(networkResources)")}
    assert "emptyScans" in cols


_SCOPE = [("site-1", "network")]


def test_manual_empty_reads_never_deactivate(temp_db):
    temp_db.sync_network_resources("account-1", [_network("LAN")], _SCOPE)
    for _ in range(3):
        temp_db.sync_network_resources("account-1", [], _SCOPE, count_empty=False)
    assert _active(temp_db) == {"LAN": 1}


def test_manual_empty_read_does_not_advance_scan_counter(temp_db):
    temp_db.sync_network_resources("account-1", [_network("LAN")], _SCOPE)
    temp_db.sync_network_resources("account-1", [], _SCOPE)
    temp_db.sync_network_resources("account-1", [], _SCOPE, count_empty=False)
    assert _active(temp_db) == {"LAN": 1}
    temp_db.sync_network_resources("account-1", [], _SCOPE)
    assert _active(temp_db) == {"LAN": 0}


def test_manual_read_still_deactivates_missing_in_non_empty_scope(temp_db):
    temp_db.sync_network_resources("account-1", [_network("LAN"), _network("IoT", "network-2")], _SCOPE)
    temp_db.sync_network_resources("account-1", [_network("LAN")], _SCOPE, count_empty=False)
    assert _active(temp_db) == {"LAN": 1, "IoT": 0}


def test_manual_read_with_resources_resets_counter(temp_db):
    temp_db.sync_network_resources("account-1", [_network("LAN")], _SCOPE)
    temp_db.sync_network_resources("account-1", [], _SCOPE)
    temp_db.sync_network_resources("account-1", [_network("LAN")], _SCOPE, count_empty=False)
    temp_db.sync_network_resources("account-1", [], _SCOPE)
    assert _active(temp_db) == {"LAN": 1}


def test_manual_read_with_one_empty_and_one_filled_scope(temp_db):
    wlan = {**_network("WLAN", "wlan-1"), "kind": "wifi"}
    lan2 = _network("IoT", "network-2")
    scopes = [("site-1", "network"), ("site-1", "wifi")]
    temp_db.sync_network_resources("account-1", [_network("LAN"), lan2, wlan], scopes)
    for _ in range(2):
        temp_db.sync_network_resources("account-1", [_network("LAN")], scopes, count_empty=False)
    assert _active(temp_db) == {"LAN": 1, "IoT": 0, "WLAN": 1}
