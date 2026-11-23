"""A source that is off or could not be read must not turn its devices `offline` (#139)."""
import asyncio

import pytest

from app import docker_probe, pipeline


async def _no_discovery(settings, progress, extra_targets=None, subnets=None):
    return {"findings": [], "warnings": [], "gateway": "", "dnsServers": [], "hostIp": "",
            "routedTargets": [], "counts": {}}


def _device(temp_db, key: str, source: str) -> str:
    system, _ = temp_db.upsert_discovered_system({
        "discoveryKey": key, "kind": "vm", "name": key, "status": "online",
        "discovered": 1, "discoverySource": source,
    })
    return system["id"]


def _scan(temp_db, monkeypatch, **settings):
    monkeypatch.setattr(pipeline.discovery, "discover", _no_discovery)
    monkeypatch.setattr(pipeline.oui, "is_downloaded", lambda: True)
    temp_db.update_settings(settings)
    asyncio.run(pipeline.run_full_scan(temp_db.create_scan("test")))


def test_disabled_docker_keeps_container_status(temp_db, monkeypatch):
    sid = _device(temp_db, "docker:a", "docker")
    _scan(temp_db, monkeypatch, scanEnableDocker=False)
    assert temp_db.get_system(sid)["status"] == "online"
    assert "docker" in str(temp_db.latest_scan())


def test_failed_docker_probe_keeps_status(temp_db, monkeypatch):
    sid = _device(temp_db, "docker:a", "docker")

    async def failing(host_ip=""):
        return {"ok": False, "error": "boom", "systems": []}

    monkeypatch.setattr(docker_probe, "probe", failing)
    monkeypatch.setattr(docker_probe, "socket_available", lambda: True)
    _scan(temp_db, monkeypatch, scanEnableDocker=True)
    assert temp_db.get_system(sid)["status"] == "online"


def test_docker_socket_missing_keeps_status(temp_db, monkeypatch):
    sid = _device(temp_db, "docker:a", "docker")

    async def failing(host_ip=""):
        return {"ok": False, "error": "no socket", "systems": []}

    monkeypatch.setattr(docker_probe, "probe", failing)
    monkeypatch.setattr(docker_probe, "socket_available", lambda: False)
    _scan(temp_db, monkeypatch, scanEnableDocker=True)
    assert temp_db.get_system(sid)["status"] == "online"


def test_successful_docker_with_zero_containers_sets_offline(temp_db, monkeypatch):
    sid = _device(temp_db, "docker:a", "docker")

    async def empty(host_ip=""):
        return {"ok": True, "systems": [], "ddns": []}

    monkeypatch.setattr(docker_probe, "probe", empty)
    _scan(temp_db, monkeypatch, scanEnableDocker=True)
    assert temp_db.get_system(sid)["status"] == "offline"


@pytest.mark.parametrize("source,category,module", [
    ("unifi", "unifi", "unifi_probe"), ("omada", "omada", "omada_probe"),
    ("proxmox", "proxmox", "proxmox_probe"), ("adguard", "adguard", "adguard_probe"),
])
def test_failing_account_skips_source(temp_db, monkeypatch, source, category, module):
    sid = _device(temp_db, f"{source}:a", source)
    temp_db.create_account({"label": "Ctl", "category": category, "allowProbe": 1,
                            "url": "https://x.invalid"})

    async def failing(*args, **kwargs):
        return {"ok": False, "error": "down", "systems": [], "warnings": []}

    monkeypatch.setattr(getattr(pipeline, module), "probe", failing)
    _scan(temp_db, monkeypatch, scanEnableDocker=False)
    assert temp_db.get_system(sid)["status"] == "online"


def test_disabled_source_without_accounts_keeps_status(temp_db, monkeypatch):
    sid = _device(temp_db, "unifi:a", "unifi")
    _scan(temp_db, monkeypatch, scanEnableDocker=False, scanEnableUnifi=True)
    assert temp_db.get_system(sid)["status"] == "online"


@pytest.mark.parametrize("source,category,module", [
    ("unifi", "unifi", "unifi_probe"), ("omada", "omada", "omada_probe"),
    ("proxmox", "proxmox", "proxmox_probe"), ("adguard", "adguard", "adguard_probe"),
])
def test_unreadable_secret_skips_account_and_keeps_status(temp_db, monkeypatch, source, category, module):
    """#118 + #139: a secret the key cannot open is never sent as an empty password, the scan
    warns and goes on, and the controller's devices keep their status."""
    from app import crypto

    sid = _device(temp_db, f"{source}:a", source)
    temp_db.create_account({"label": "Ctl", "category": category, "allowProbe": 1,
                            "url": "https://x.invalid"})

    def unreadable(token):
        raise crypto.SecretUnreadable()

    async def must_not_run(*args, **kwargs):
        raise AssertionError("probe called with an unreadable secret")

    monkeypatch.setattr(pipeline.crypto, "decrypt_strict", unreadable)
    monkeypatch.setattr(getattr(pipeline, module), "probe", must_not_run)
    _scan(temp_db, monkeypatch, scanEnableDocker=False)
    assert temp_db.get_system(sid)["status"] == "online"
    assert "Secret nicht lesbar" in str(temp_db.latest_scan())
