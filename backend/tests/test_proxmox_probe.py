import asyncio

import httpx

from app import proxmox_probe


def test_parse_notes_extracts_doc_link_and_leaves_purpose():
    notes = "Nextcloud fuer Fotos und Kalender.\nDoc: https://wiki.home.local/nextcloud\nBackup: taeglich 3 Uhr"
    purpose, doc_link = proxmox_probe.parse_notes(notes)
    assert purpose == "Nextcloud fuer Fotos und Kalender."
    assert doc_link == "https://wiki.home.local/nextcloud"


def test_parse_notes_accepts_url_label_case_insensitively():
    purpose, doc_link = proxmox_probe.parse_notes("url: HTTPS://example.com/runbook\nMehr Text")
    assert doc_link == "HTTPS://example.com/runbook"
    assert purpose == "Mehr Text"


def test_parse_notes_only_takes_the_first_doc_link():
    purpose, doc_link = proxmox_probe.parse_notes(
        "Doc: https://first.example\nDoc: https://second.example\nBeschreibung"
    )
    assert doc_link == "https://first.example"
    # The second Doc: line is left as plain prose since it wasn't consumed as *the* link, and
    # `purpose` is just the first remaining non-empty line.
    assert purpose == "Doc: https://second.example"


def test_parse_notes_does_not_match_url_mentioned_mid_sentence():
    purpose, doc_link = proxmox_probe.parse_notes("Migriert von https://old-host/vm3 letzten Monat.")
    assert doc_link == ""
    assert purpose == "Migriert von https://old-host/vm3 letzten Monat."


def test_parse_notes_empty_input():
    assert proxmox_probe.parse_notes("") == ("", "")
    assert proxmox_probe.parse_notes(None) == ("", "")  # type: ignore[arg-type]


def test_is_critical_tag_matches_semicolon_and_comma_separated():
    assert proxmox_probe.is_critical_tag("backup;critical;linux")
    assert proxmox_probe.is_critical_tag("backup,critical,linux")
    assert proxmox_probe.is_critical_tag("Critical")
    assert not proxmox_probe.is_critical_tag("backup;linux")
    assert not proxmox_probe.is_critical_tag("")
    assert not proxmox_probe.is_critical_tag("noncritical")  # substring, not a whole tag


def _handler(routes: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get(request.url.path, httpx.Response(404))
    return handler


def test_probe_sets_critical_importance_docs_and_purpose_from_notes(monkeypatch):
    routes = {
        "/api2/json/nodes": httpx.Response(200, json={"data": [{"node": "pve"}]}),
        "/api2/json/nodes/pve/qemu": httpx.Response(200, json={"data": [
            {"vmid": 101, "name": "nextcloud", "status": "running", "cpus": 2, "maxmem": 2147483648},
        ]}),
        "/api2/json/nodes/pve/lxc": httpx.Response(200, json={"data": []}),
        "/api2/json/nodes/pve/qemu/101/config": httpx.Response(200, json={"data": {
            "net0": "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,ip=192.168.1.50/24",
            "description": "Cloud-Speicher fuers Haus.\nDoc: https://wiki.local/nextcloud",
            "tags": "critical;linux",
        }}),
    }
    transport = httpx.MockTransport(_handler(routes))

    class _FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            kwargs.pop("verify", None)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(proxmox_probe.httpx, "AsyncClient", _FakeAsyncClient)

    result = asyncio.run(proxmox_probe.probe("https://pve.local:8006", "root@pam!token", "secret"))

    assert result["ok"]
    assert len(result["systems"]) == 1
    vm = result["systems"][0]
    assert vm["importance"] == "critical"
    assert vm["purpose"] == "Cloud-Speicher fuers Haus."
    assert vm["docLink"] == "https://wiki.local/nextcloud"
    assert vm["mac"] == "aa:bb:cc:dd:ee:ff"
    assert vm["discoveryKey"] == "mac:aa:bb:cc:dd:ee:ff"


def test_probe_leaves_importance_unset_when_not_tagged_critical(monkeypatch):
    routes = {
        "/api2/json/nodes": httpx.Response(200, json={"data": [{"node": "pve"}]}),
        "/api2/json/nodes/pve/qemu": httpx.Response(200, json={"data": [
            {"vmid": 102, "name": "test-vm", "status": "stopped", "cpus": 1, "maxmem": 1073741824},
        ]}),
        "/api2/json/nodes/pve/lxc": httpx.Response(200, json={"data": []}),
        "/api2/json/nodes/pve/qemu/102/config": httpx.Response(200, json={"data": {}}),
    }
    transport = httpx.MockTransport(_handler(routes))

    class _FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            kwargs.pop("verify", None)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(proxmox_probe.httpx, "AsyncClient", _FakeAsyncClient)

    result = asyncio.run(proxmox_probe.probe("https://pve.local:8006", "root@pam!token", "secret"))

    vm = result["systems"][0]
    assert "importance" not in vm
    assert vm["status"] == "offline"
    assert vm["discoveryKey"] == "proxmox:pve:vm:102"


def _template_routes() -> dict:
    """Two nodes: a template on pve1, a normal guest on pve2; qemu 100/103 and lxc 200 are
    templates (103 with the string form), the others are normal guests."""
    return {
        "/api2/json/nodes": httpx.Response(200, json={"data": [{"node": "pve1"}, {"node": "pve2"}]}),
        "/api2/json/nodes/pve1/qemu": httpx.Response(200, json={"data": [
            {"vmid": 100, "name": "tpl", "status": "stopped", "template": 1},
            {"vmid": 101, "name": "a", "status": "running", "template": 0},
            {"vmid": 102, "name": "b", "status": "running"},
        ]}),
        "/api2/json/nodes/pve1/lxc": httpx.Response(200, json={"data": [
            {"vmid": 200, "name": "lxc-tpl", "status": "stopped", "template": 1},
        ]}),
        "/api2/json/nodes/pve2/qemu": httpx.Response(200, json={"data": [
            {"vmid": 103, "name": "tpl2", "status": "stopped", "template": "1"},
        ]}),
        "/api2/json/nodes/pve2/lxc": httpx.Response(200, json={"data": [
            {"vmid": 201, "name": "c", "status": "running", "template": None},
        ]}),
        "/api2/json/nodes/pve1/qemu/101/config": httpx.Response(200, json={"data": {}}),
        "/api2/json/nodes/pve1/qemu/102/config": httpx.Response(200, json={"data": {}}),
        "/api2/json/nodes/pve2/lxc/201/config": httpx.Response(200, json={"data": {}}),
    }


def _dispatching(monkeypatch, routes: dict, config_calls: list) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/config") and path not in routes:
            config_calls.append(path)
        return routes.get(path, httpx.Response(404))

    transport = httpx.MockTransport(handler)

    class _Client(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            kwargs.pop("verify", None)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(proxmox_probe.httpx, "AsyncClient", _Client)


def test_probe_skips_templates(monkeypatch):
    calls: list = []
    _dispatching(monkeypatch, _template_routes(), calls)
    result = asyncio.run(proxmox_probe.probe("https://pve.local:8006", "root@pam!t", "s"))
    assert result["ok"]
    assert [s["extra"]["proxmox"]["vmid"] for s in result["systems"]] == [101, 102, 201]
    assert [s["discoveryKey"] for s in result["systems"]] == [
        "proxmox:pve1:vm:101", "proxmox:pve1:vm:102", "proxmox:pve2:container:201",
    ]
    assert calls == []  # no /config request for any template
