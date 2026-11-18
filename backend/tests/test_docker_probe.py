import asyncio

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
