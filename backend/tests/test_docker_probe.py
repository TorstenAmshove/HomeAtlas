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
    assert res["ok"] is False and "nicht eingebunden" in res["error"]


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
