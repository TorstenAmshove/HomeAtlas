"""Deep links to Portainer / Proxmox for a device (admin_links.build and the route)."""
import pytest
from fastapi.testclient import TestClient

from app import admin_links, auth, db, main

PORTAINER = {"portainerUrl": "https://p:9443", "portainerEnvId": "2", "proxmoxWebUrl": ""}
CONTAINER = {"kind": "container", "extra": {"docker": {"containerId": "abc123"}}}


def _build(system, settings=None, parent=None, urls=()):
    return admin_links.build(system, {**{"portainerUrl": "", "portainerEnvId": "", "proxmoxWebUrl": ""},
                                      **(settings or {})}, parent, list(urls))


def test_docker_container_link():
    assert _build(CONTAINER, PORTAINER) == [
        {"label": "In Portainer öffnen", "url": "https://p:9443/#!/2/docker/containers/abc123"}]


@pytest.mark.parametrize("settings", [{"portainerUrl": "https://p"}, {"portainerEnvId": "1"}, {}])
def test_docker_needs_url_and_env(settings):
    assert _build(CONTAINER, settings) == []


def test_docker_needs_container_id():
    assert _build({"kind": "container", "extra": {"docker": {"containerId": ""}}}, PORTAINER) == []
    assert _build({"kind": "device", "extra": {}}, PORTAINER) == []


def test_proxmox_vm_and_lxc():
    s = {"proxmoxWebUrl": "https://pve:8006"}
    vm = {"kind": "vm", "extra": {"proxmox": {"node": "n1", "vmid": 100}}}
    lxc = {"kind": "container", "extra": {"proxmox": {"node": "n1", "vmid": "101"}}}
    assert _build(vm, s)[0]["url"] == "https://pve:8006/#v1:0:=qemu%2F100"
    assert _build(lxc, s) == [{"label": "In Proxmox öffnen", "url": "https://pve:8006/#v1:0:=lxc%2F101"}]


def test_proxmox_missing_fields():
    s = {"proxmoxWebUrl": "https://pve:8006"}
    assert _build({"kind": "vm", "extra": {"proxmox": {"node": "n1"}}}, s) == []
    assert _build({"kind": "vm", "extra": {"proxmox": {"vmid": 1}}}, s) == []


def test_proxmox_base_fallback_order():
    vm = {"kind": "vm", "extra": {"proxmox": {"node": "n", "vmid": 5}}}
    parent = {"url": "https://parent:8006/x"}
    assert _build(vm, {"proxmoxWebUrl": "https://set"}, parent, ["https://acc:8006"])[0]["url"].startswith("https://set/")
    assert _build(vm, {}, parent, ["", "https://acc:8006/api2/json"])[0]["url"].startswith("https://acc:8006/#")
    assert _build(vm, {}, parent, [])[0]["url"].startswith("https://parent:8006/#")
    assert _build(vm, {}, None, []) == []
    assert _build(vm, {}, {"url": "javascript:x"}, []) == []


@pytest.fixture()
def client(temp_db):
    role = {"v": auth.ROLE_ADMIN}
    main.app.dependency_overrides[main.current_user] = lambda: {"role": role["v"]}
    c = TestClient(main.app)
    c.role = role
    try:
        yield c
    finally:
        main.app.dependency_overrides.clear()


def test_route(client):
    db.update_settings(PORTAINER)
    sysm = db.create_system({"name": "c", "kind": "container", "extra": {"docker": {"containerId": "x1"}}})
    plain = db.create_system({"name": "p", "kind": "server"})
    r = client.get(f"/api/systems/{sysm['id']}/admin-links")
    assert r.status_code == 200
    assert r.json()["links"][0]["url"] == "https://p:9443/#!/2/docker/containers/x1"
    assert client.get(f"/api/systems/{plain['id']}/admin-links").json() == {"links": []}
    assert client.get("/api/systems/missing/admin-links").status_code == 404
    client.role["v"] = auth.ROLE_MEMBER
    assert client.get(f"/api/systems/{sysm['id']}/admin-links").status_code == 403


PVE = {"proxmoxWebUrl": "https://pve:8006"}


def _guest(kind, **proxmox):
    return {"kind": kind, "extra": {"proxmox": {"node": "n1", "vmid": 101, **proxmox}}}


def test_proxmox_type_overrides_kind():
    assert _build(_guest("smarthome", type="qemu"), PVE)[0]["url"] == "https://pve:8006/#v1:0:=qemu%2F101"
    assert _build(_guest("smarthome", type="lxc"), PVE)[0]["url"] == "https://pve:8006/#v1:0:=lxc%2F101"
    assert _build(_guest("container", type="qemu"), PVE)[0]["url"].endswith("=qemu%2F101")


@pytest.mark.parametrize("bad", ["../x", "QEMU", " qemu", ["qemu"], 5, None, {"a": 1}])
def test_proxmox_invalid_type_falls_back(bad):
    assert _build(_guest("server", type=bad), PVE) == []
    links = _build(_guest("vm", type=bad), PVE)
    assert links[0]["url"] == "https://pve:8006/#v1:0:=qemu%2F101"


def test_proxmox_type_still_needs_node_vmid_base_and_no_docker():
    assert _build({"kind": "smarthome", "extra": {"proxmox": {"vmid": 1, "type": "qemu"}}}, PVE) == []
    assert _build(_guest("smarthome", type="qemu", vmid="x1"), PVE) == []
    assert _build(_guest("smarthome", type="qemu"), {}) == []
    g = _guest("smarthome", type="qemu")
    g["extra"]["docker"] = {"containerId": "abc"}
    assert _build(g, PVE) == []
