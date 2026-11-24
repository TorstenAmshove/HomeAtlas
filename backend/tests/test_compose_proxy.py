"""ADR-0024: only the proxy service mounts docker.sock, and its allowlist is exactly HomeAtlas's GET paths.

This mirrors the proxy's regex semantics (anchored full match on the path); it cannot prove the
proxy's behaviour, which is verified by hand (see the PR description).
"""
import re
from pathlib import Path

import pytest
import yaml

COMPOSE = yaml.safe_load((Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text())
SERVICES = COMPOSE["services"]


def _socket_mounts(service: dict) -> list[str]:
    return [v for v in service.get("volumes", []) if "docker.sock" in str(v)]


def test_only_proxy_mounts_the_socket():
    assert {n for n, s in SERVICES.items() if _socket_mounts(s)} == {"docker-proxy"}
    assert _socket_mounts(SERVICES["docker-proxy"])[0].endswith(":ro")


def test_proxy_has_no_network_and_no_tcp_listener():
    proxy = SERVICES["docker-proxy"]
    assert proxy.get("network_mode") == "none" and "ports" not in proxy
    flags = [str(c) for c in proxy["command"]]
    assert any(f.startswith("-proxysocketendpoint=") for f in flags)
    assert not any(f.startswith("-listenip") for f in flags)


def test_backend_uses_proxy_endpoint():
    env = SERVICES["backend"]["environment"]
    assert "DOCKER_HOST=unix:///docker-proxy/proxy.sock" in env
    assert any(str(v).startswith("docker-proxy-sock:/docker-proxy") for v in SERVICES["backend"]["volumes"])


def _allow():
    flags = [str(c) for c in SERVICES["docker-proxy"]["command"] if str(c).startswith("-allow")]
    assert [f.split("=", 1)[0] for f in flags if f.startswith("-allow") and not f.startswith("-allowfrom")] == ["-allowGET"]
    return re.compile(next(f for f in flags if f.startswith("-allowGET=")).split("=", 1)[1])


@pytest.mark.parametrize("path", ["/version", "/info", "/containers/json", "/networks", "/volumes",
                                  "/v1.43/version", "/v1.4/containers/json", "/v1.51/volumes"])
def test_allowlist_permits_the_probe_paths(path):
    assert _allow().fullmatch(path)


@pytest.mark.parametrize("path", [
    "/containers/" + "a" * 64 + "/json", "/containers/abc/logs", "/containers/abc/archive", "/containers/abc/export",
    "/containers/abc/exec", "/containers/json/x", "/containers/", "/images/json", "/networks/abc", "/volumes/x",
    "/version/x", "/x/version", "/v1.43/containers/abc/json", "/v1./version", "/v1.43", "/info/../containers/abc/json",
    "/events", "/system/df", "/swarm", "/secrets",
])
def test_allowlist_blocks_everything_else(path):
    assert not _allow().fullmatch(path)
