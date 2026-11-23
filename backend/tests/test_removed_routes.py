"""#217: HomeAtlas has no remote administration and no direct Shelly switching any more. The removed
HTTP routes answer 404, the console WebSockets are not served, and no module imports the deleted
write modules."""
import re
from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect
from fastapi.testclient import TestClient

from app import main

REMOVED_HTTP = [
    ("post", "/api/systems/s1/ssh-keys"),
    ("post", "/api/accounts/a1/deploy"),
    ("post", "/api/systems/s1/container/restart"),
    ("get", "/api/systems/s1/container/logs"),
    ("get", "/api/systems/s1/remote-containers"),
    ("post", "/api/systems/s1/remote-containers/c1/restart"),
    ("get", "/api/systems/s1/remote-containers/c1/logs"),
    ("post", "/api/systems/s1/reboot"),
    ("post", "/api/systems/s1/shelly-switch/on"),
    ("post", "/api/systems/s1/ha-switch/on"),
    ("get", "/api/systems/s1/ha-switchables"),
]
REMOVED_WS = ["ssh-console", "docker-console", "remote-docker-console"]


@pytest.fixture()
def admin(temp_db):
    user = {"id": "u1", "role": "ADMIN", "username": "admin", "totpEnabled": 1}
    main.app.dependency_overrides[main.current_user] = lambda: user
    main.app.dependency_overrides[main.require_admin] = lambda: user
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


@pytest.mark.parametrize("method, path", REMOVED_HTTP)
def test_removed_http_routes_404(admin, method, path):
    assert getattr(admin, method)(path).status_code in (404, 405)
    assert not any(getattr(r, "path", "") == path for r in main.app.routes)


@pytest.mark.parametrize("name", REMOVED_WS)
def test_removed_websockets_not_served(admin, name):
    with pytest.raises(WebSocketDisconnect):
        with admin.websocket_connect(f"/api/ws/systems/s1/{name}"):
            pass


def test_no_module_imports_removed_admin_modules():
    pattern = re.compile(r"remote_admin|docker_admin|proxmox_admin")
    app_dir = Path(__file__).resolve().parent.parent / "app"
    hits = [str(p.relative_to(app_dir)) for p in app_dir.rglob("*.py") if pattern.search(p.read_text())]
    assert hits == []
