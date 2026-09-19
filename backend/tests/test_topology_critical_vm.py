"""Regression test: a VM/LXC marked critical used to be excluded from topology.render()'s
"Wichtige Geraete" row (`critical = [... and s["kind"] not in ("container", "vm")]`) and only ever
showed up folded into its host's collapsed "N Container/VM" count -- exactly the opposite of what
marking something critical is supposed to do. See the fix in topology.py's render()."""
from app import topology


def _host(temp_db, name="Proxmox-Host"):
    return temp_db.create_system({
        "kind": "server", "name": name, "ip": "10.0.0.5", "mac": "aa:aa:aa:aa:aa:01",
        "discoveryKey": "mac:aa:aa:aa:aa:aa:01", "importance": "critical",
    })


def test_critical_vm_gets_its_own_box_instead_of_only_a_host_summary(temp_db):
    host = _host(temp_db)
    critical_vm = temp_db.create_system({
        "kind": "vm", "name": "Wichtige VM", "ip": "10.0.0.51",
        "discoveryKey": "proxmox:pve:vm:101", "importance": "critical",
        "parentId": host["id"], "status": "online",
    })
    other_vm = temp_db.create_system({
        "kind": "vm", "name": "Nebensaechliche VM", "ip": "10.0.0.52",
        "discoveryKey": "proxmox:pve:vm:102", "importance": "normal",
        "parentId": host["id"], "status": "online",
    })

    svg = topology.render({})

    assert f'data-system-id="{critical_vm["id"]}"' in svg
    assert "Wichtige VM" in svg
    # The non-critical VM stays folded into the host's collapsed count, not drawn on its own.
    assert f'data-system-id="{other_vm["id"]}"' not in svg
    assert "Nebensaechliche VM" not in svg
    # Its host's subtitle now only counts the still-nested (non-critical) VM.
    assert "1 Container/VM" in svg


def test_non_critical_vm_still_folds_into_host_summary(temp_db):
    host = _host(temp_db)
    vm = temp_db.create_system({
        "kind": "vm", "name": "Normale VM", "ip": "10.0.0.60",
        "discoveryKey": "proxmox:pve:vm:200", "importance": "normal",
        "parentId": host["id"], "status": "online",
    })

    svg = topology.render({})

    assert f'data-system-id="{vm["id"]}"' not in svg
    assert "1 Container/VM" in svg


def test_layer3_plan_uses_controller_cidr_instead_of_assuming_a_24(temp_db):
    router = temp_db.create_system({"kind": "router", "name": "UCG", "ip": "192.168.20.1"})
    account = temp_db.create_account({"systemId": router["id"], "label": "UCG", "category": "unifi"})
    temp_db.sync_network_resources(account["id"], [{
        "source": "unifi", "ownerSystemId": router["id"], "siteExternalId": "default", "siteName": "Haus",
        "kind": "network", "externalId": "vlan-20", "name": "IoT",
        "facts": {"cidr": "192.168.20.0/26", "vlanId": 20},
    }], [("default", "network")])
    for index in (2, 3):
        temp_db.create_system({"kind": "iot", "name": f"Sensor {index}", "ip": f"192.168.20.{index}"})

    svg = topology.render_layer3({})

    assert "192.168.20.0/26" in svg
    assert "192.168.20.0/24" not in svg
