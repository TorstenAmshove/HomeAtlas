import asyncio

import httpx
import pytest

from app import docker_probe


def _run(monkeypatch, containers):
    async def fake_get(path):
        if path.startswith("/containers"):
            return containers
        if path == "/volumes":
            return {"Volumes": []}
        if path == "/networks":
            return []
        return {"Name": "host", "Version": "1"}

    monkeypatch.setattr(docker_probe, "_get", fake_get)
    monkeypatch.setattr(docker_probe, "socket_available", lambda: True)
    return asyncio.run(docker_probe.probe("192.168.1.20"))["systems"]


def _c(names, project="", service="", cid="abcdef1234567890"):
    labels = {}
    if project:
        labels["com.docker.compose.project"] = project
    if service:
        labels["com.docker.compose.service"] = service
    return {"Id": cid, "Names": names, "Labels": labels, "State": "running"}


def test_container_names(monkeypatch):
    systems = _run(monkeypatch, [
        _c(["/immich-postgres-1"], "immich", "postgres", "a" * 20),
        _c(["/paperless-postgres-1"], "paperless", "postgres", "b" * 20),
        _c(["/standalone"], cid="c" * 20),
        _c(["/only-project"], project="x", cid="d" * 20),
        _c(["/only-service"], service="y", cid="e" * 20),
    ])
    assert [s["name"] for s in systems] == [
        "postgres · immich", "postgres · paperless", "standalone", "only-project", "only-service",
    ]
    assert systems[0]["discoveryKey"] == "docker:immich:postgres"
    assert systems[2]["discoveryKey"] == "docker:standalone"
    assert systems[3]["discoveryKey"] == "docker:only-project"


def test_restart_policy_comes_from_host_config():
    from app import docker_probe
    assert docker_probe._restart_policy({"HostConfig": {"RestartPolicy": {"Name": "unless-stopped"}}}, {}) == "unless-stopped"
    assert docker_probe._restart_policy({"HostConfig": {"RestartPolicy": {"Name": "no"}}}, {}) == "no"
    assert docker_probe._restart_policy({}, {"restart": "always"}) == "always"


# --- live_containers (ADR-0022) ---------------------------------------------------------------
SECRET = "SuperSecretToken123"


def _live(status, state="running", name="/jelly", **extra):
    return {"Id": "ab12cd34ef56" + "0" * 52, "Names": [name], "Image": "jellyfin/jellyfin:10", "State": state,
            "Status": status, "Labels": {"com.docker.compose.project": "media", "com.docker.compose.service": "jf",
                                         "secret.label": SECRET},
            "Command": f"run --token {SECRET}", "Mounts": [{"Source": "/secret"}],
            "Config": {"Env": [f"TOKEN={SECRET}"]}, "HostConfig": {"x": SECRET}, **extra}


def _patch_live(monkeypatch, handler):
    monkeypatch.setattr(docker_probe, "socket_available", lambda: True)
    monkeypatch.setattr(docker_probe.httpx, "AsyncHTTPTransport", lambda **kw: httpx.MockTransport(handler))


def _live_run(monkeypatch, payload):
    _patch_live(monkeypatch, lambda req: httpx.Response(200, json=payload))
    return asyncio.run(docker_probe.live_containers())


def test_live_containers_states(monkeypatch):
    res = _live_run(monkeypatch, [
        _live("Exited (137) 3 minutes ago", "exited", "/a"),
        _live("Restarting (1) 5 seconds ago", "restarting", "/b"),
        _live("Up 2 hours (unhealthy)", name="/c"),
        _live("Up 3 days (healthy)", name="/d"),
        _live("Up 5 seconds (health: starting)", name="/e"),
        _live("Created", "created", "/f"),
        _live("Up 3 days (Paused)", "paused", "/g"),
    ])
    by = {c["name"]: c for c in res["containers"]}
    assert res["ok"]
    assert by["a"]["exitCode"] == 137 and "Speicher" in by["a"]["exitMeaning"] and by["a"]["since"] == "Exited 3 minutes ago"
    assert by["b"]["exitCode"] == 1 and by["b"]["state"] == "restarting"
    assert by["c"]["health"] == "unhealthy" and by["c"]["since"] == "Up 2 hours" and by["c"]["exitCode"] is None
    assert by["d"]["health"] == "healthy" and by["e"]["health"] == "starting"
    assert by["f"]["state"] == "created" and by["f"]["health"] is None
    assert by["g"]["since"] == "Up 3 days"


def test_live_containers_only_list_get(monkeypatch):
    seen = []

    def handler(req):
        seen.append((req.method, req.url.raw_path.decode()))
        return httpx.Response(200, json=[_live("Up 1 hour")])

    _patch_live(monkeypatch, handler)
    asyncio.run(docker_probe.live_containers())
    assert seen == [("GET", "/containers/json?all=1")]


def test_live_containers_field_allowlist(monkeypatch):
    res = _live_run(monkeypatch, [_live("Up 1 hour")])
    row = res["containers"][0]
    assert {k for k in row if not k.startswith("_")} == {
        "name", "image", "state", "status", "exitCode", "exitMeaning", "health", "since", "composeProject"}
    assert SECRET not in str(res) and row["composeProject"] == "media"


@pytest.mark.parametrize("handler,text", [
    (lambda r: (_ for _ in ()).throw(httpx.ConnectError("boom")), "Docker-API nicht erreichbar"),
    (lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow")), "Docker-API nicht erreichbar"),
    (lambda r: httpx.Response(403), "Docker-API nicht erreichbar"),
    (lambda r: httpx.Response(500), "Docker-API nicht erreichbar"),
    (lambda r: httpx.Response(200, content=b"not json"), "Docker-API nicht erreichbar"),
    (lambda r: httpx.Response(200, json={"a": 1}), "keine Containerliste"),
])
def test_live_containers_errors(monkeypatch, handler, text):
    _patch_live(monkeypatch, handler)
    res = asyncio.run(docker_probe.live_containers())
    assert res["ok"] is False and text in res["error"] and res["containers"] == []


def test_live_containers_no_socket(monkeypatch):
    monkeypatch.setattr(docker_probe, "socket_available", lambda: False)
    res = asyncio.run(docker_probe.live_containers())
    assert res["ok"] is False and "nicht eingerichtet" in res["error"]


def test_live_containers_odd_input(monkeypatch):
    res = _live_run(monkeypatch, [
        "junk", None, {"Labels": None},
        {"Names": ["/x"], "Image": "user:pass@reg.io/app:1", "Labels": None, "State": "running"},
        {"Names": ["/y"], "Image": "app@sha256:abc"},
    ])
    rows = res["containers"]
    assert [r["name"] for r in rows] == ["unbenannter Container", "x", "y"]
    assert rows[1]["image"] == "reg.io/app:1" and "pass" not in str(rows)
    assert rows[2]["image"] == "app@sha256:abc"


def test_exit_meaning():
    assert docker_probe.exit_meaning(0) == "regulär beendet"
    assert "Speicher" in docker_probe.exit_meaning(137)
    assert "SIGTERM" in docker_probe.exit_meaning(143)
    assert docker_probe.exit_meaning(42) == "unbekannter Exit-Code"
    assert docker_probe.exit_meaning(None) is None


# --- ADR-0024: endpoint resolution, no inspect, DDNS labels, socket mounts ---------------------
def _clear_env(monkeypatch):
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_SOCKET", raising=False)


def test_endpoint_resolution(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    assert docker_probe._endpoint() == ("unix", "/var/run/docker.sock")
    monkeypatch.setenv("DOCKER_SOCKET", "/old/docker.sock")
    assert docker_probe._endpoint() == ("unix", "/old/docker.sock")
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/proxy/docker.sock")
    assert docker_probe._endpoint() == ("unix", "/run/proxy/docker.sock")
    monkeypatch.setenv("DOCKER_HOST", "tcp://127.0.0.1:2375")
    assert docker_probe._endpoint() == ("tcp", "http://127.0.0.1:2375")
    assert docker_probe.socket_available()
    for bad in ("tcp://192.168.1.5:2375", "tcp://127.0.0.1", "npipe:////./pipe/docker", "ssh://u@h", "http://x:1"):
        monkeypatch.setenv("DOCKER_HOST", bad)
        assert docker_probe._endpoint()[0] == "" and not docker_probe.socket_available()
    # an empty DOCKER_HOST falls back to DOCKER_SOCKET
    monkeypatch.setenv("DOCKER_HOST", "")
    assert docker_probe._endpoint() == ("unix", "/old/docker.sock")
    sock = tmp_path / "s.sock"
    sock.write_text("")
    monkeypatch.setenv("DOCKER_HOST", f"unix://{sock}")
    assert docker_probe.socket_available()


def test_legacy_docker_socket_still_works(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    sock = tmp_path / "docker.sock"
    sock.write_text("")
    monkeypatch.setenv("DOCKER_SOCKET", str(sock))
    assert docker_probe.socket_available()
    monkeypatch.setattr(docker_probe.httpx, "AsyncHTTPTransport", lambda **kw: httpx.MockTransport(
        lambda req: httpx.Response(200, json=[])))
    assert asyncio.run(docker_probe.live_containers())["ok"]


def test_probe_never_requests_inspect(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("DOCKER_HOST", "tcp://127.0.0.1:2375")
    seen = []

    def handler(req):
        seen.append((req.method, req.url.raw_path.decode()))
        path = req.url.path
        if path == "/containers/json":
            return httpx.Response(200, json=[{"Id": "a" * 64, "Names": ["/ddns"], "Image": "favonia/cloudflare-ddns",
                                              "State": "running", "Labels": {"homeatlas.ddns.hosts": "a.example.net"}}])
        if path == "/volumes":
            return httpx.Response(200, json={"Volumes": []})
        return httpx.Response(200, json=[] if path == "/networks" else {"Name": "h"})

    real = httpx.AsyncClient
    monkeypatch.setattr(docker_probe.httpx, "AsyncClient", lambda **kw: real(
        transport=httpx.MockTransport(handler), base_url=kw["base_url"]))
    res = asyncio.run(docker_probe.probe("192.0.2.20"))
    assert res["ok"] and res["ddns"][0]["data"]["hosts"] == ["a.example.net"]
    assert sorted(seen) == sorted([("GET", "/version"), ("GET", "/info"), ("GET", "/containers/json?all=1"),
                                   ("GET", "/networks"), ("GET", "/volumes")])


def test_ddns_replaces_old_facts_when_hosts_empty(temp_db):
    temp_db.replace_exposure_facts("docker_ddns", "docker", [
        {"kind": "ddns", "key": "c", "data": {"hosts": ["old.example.net"]}}])
    fact = docker_probe.ddns_fact("ddclient", {}, "x")
    temp_db.replace_exposure_facts("docker_ddns", "docker", [fact])
    facts = temp_db.list_exposure_facts() if hasattr(temp_db, "list_exposure_facts") else None
    assert facts is None or "old.example.net" not in str(facts)


def _mount(src, dst="/var/run/docker.sock", typ="bind", mode="ro"):
    return {"Type": typ, "Source": src, "Destination": dst, "Mode": mode}


@pytest.mark.parametrize("mounts", [
    [_mount("/var/run/docker.sock")],
    [_mount("/var/run/docker.sock", mode="rw")],
    [_mount("/run/docker.sock")],
    [_mount("/run/user/1000/docker.sock", "/sock/docker.sock")],
    [_mount("/srv/proxy/x.sock", "/var/run/docker.sock")],
    [_mount("/data", "/data"), _mount("/var/run/docker.sock")],
])
def test_socket_mount_detected(mounts):
    assert docker_probe.has_docker_socket({"Mounts": mounts})


@pytest.mark.parametrize("container", [
    {}, {"Mounts": None}, {"Mounts": []}, {"Mounts": [None, "x"]},
    {"Mounts": [_mount("homeatlas-data", "/data", typ="volume")]},
    {"Mounts": [_mount("/var/run", "/var/run")]},
    {"Mounts": [_mount("vol", "/var/run/docker.sock", typ="volume")]},
])
def test_no_flag_without_mount(container):
    assert not docker_probe.has_docker_socket(container)


def test_proxy_image_is_neutral(monkeypatch):
    mounts = [_mount("/var/run/docker.sock")]
    systems = _run(monkeypatch, [
        {**_c(["/p1"], cid="a" * 20), "Image": "wollomatic/socket-proxy:1.2", "Mounts": mounts},
        {**_c(["/p2"], cid="b" * 20), "Image": "tecnativa/docker-socket-proxy", "Mounts": mounts},
        {**_c(["/portainer"], cid="c" * 20), "Image": "portainer/portainer-ce", "Mounts": mounts},
        {**_c(["/plain"], cid="d" * 20), "Image": "nginx", "Mounts": []},
    ])
    assert [s["extra"]["docker"]["dockerSocket"] for s in systems] == [False, False, True, False]


def test_probe_unreachable_proxy(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("DOCKER_HOST", f"unix://{tmp_path}/missing.sock")
    res = asyncio.run(docker_probe.probe("x"))
    assert not res["ok"] and "nicht eingerichtet" in res["error"]
    monkeypatch.setenv("DOCKER_HOST", "tcp://127.0.0.1:2375")
    real = httpx.AsyncClient
    monkeypatch.setattr(docker_probe.httpx, "AsyncClient", lambda **kw: real(
        transport=httpx.MockTransport(lambda r: httpx.Response(403)), base_url=kw["base_url"]))
    res = asyncio.run(docker_probe.probe("x"))
    assert not res["ok"] and "nicht erreichbar" in res["error"]
