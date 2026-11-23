"""remote_admin.reboot_fritzbox (TR-064 SOAP over HTTP) and remote_admin.remote_container_logs
(one-shot `docker logs` over SSH) -- the two write-capable additions that let devices restartable
over SSH/TR-064 also be restarted from the GUI, and remote Docker containers show their logs the
same way the local container card already can."""
import asyncio

import asyncssh
import httpx

from app import remote_admin


class _FakeRunResult:
    def __init__(self, stdout: str, exit_status: int = 0, stderr: str = ""):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_status = exit_status


class _FakeConnection:
    def __init__(self, responses: dict[str, _FakeRunResult]):
        self.responses = responses
        self.commands: list[str] = []

    async def run(self, command: str, check: bool = False):
        self.commands.append(command)
        return self.responses.get(command, _FakeRunResult("", 127, "command not found"))


class _FakeConnectContextManager:
    def __init__(self, connection: _FakeConnection):
        self._connection = connection

    async def __aenter__(self):
        return self._connection

    async def __aexit__(self, *exc_info):
        return False


def _account() -> dict:
    # category "login" (not "sshkey") -- _connect_args only treats an account as a private key
    # when the category says so or the decoded secret text itself looks like a PEM key, and the
    # fake secret below ("hunter2") is neither.
    return {"category": "login", "username": "root", "secretEnc": "", "port": 22}


def test_remote_container_logs_returns_last_lines(monkeypatch):
    connection = _FakeConnection({
        "docker logs --tail 200 abc123 2>&1": _FakeRunResult("line one\nline two\n"),
    })
    monkeypatch.setattr(asyncssh, "connect", lambda **kwargs: _FakeConnectContextManager(connection))
    monkeypatch.setattr(remote_admin, "_decode_secret", lambda account: ("hunter2", ""))

    result = asyncio.run(remote_admin.remote_container_logs("10.0.0.40", _account(), "abc123"))

    assert result["ok"]
    assert "line one" in result["text"]
    assert connection.commands == ["docker logs --tail 200 abc123 2>&1"]


def test_remote_container_logs_reports_docker_group_permission_error(monkeypatch):
    connection = _FakeConnection({
        "docker logs --tail 200 abc123 2>&1": _FakeRunResult(
            "permission denied while trying to connect to the Docker daemon socket ... docker.sock", 1,
        ),
    })
    monkeypatch.setattr(asyncssh, "connect", lambda **kwargs: _FakeConnectContextManager(connection))
    monkeypatch.setattr(remote_admin, "_decode_secret", lambda account: ("hunter2", ""))

    result = asyncio.run(remote_admin.remote_container_logs("10.0.0.40", _account(), "abc123"))

    assert not result["ok"]
    assert "usermod -aG docker" in result["error"]


def _tr064_client(monkeypatch, handler) -> None:
    transport = httpx.MockTransport(handler)

    class _FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(remote_admin.httpx, "AsyncClient", _FakeAsyncClient)


def test_reboot_fritzbox_posts_the_reboot_soap_action(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["soap_action"] = request.headers.get("soapaction")
        seen["body"] = request.content.decode()
        return httpx.Response(200, text="<Envelope/>")

    _tr064_client(monkeypatch, handler)

    result = asyncio.run(remote_admin.reboot_fritzbox("192.168.1.1", {
        "category": "login", "username": "admin", "secretEnc": "",
    }))

    assert result["ok"]
    assert seen["path"] == "/upnp/control/deviceconfig"
    assert seen["soap_action"] == "urn:dslforum-org:service:DeviceConfig:1#Reboot"
    assert "u:Reboot" in seen["body"]
    assert "DeviceConfig:1" in seen["body"]


def test_reboot_fritzbox_reports_http_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    _tr064_client(monkeypatch, handler)

    result = asyncio.run(remote_admin.reboot_fritzbox("192.168.1.1", {
        "category": "login", "username": "admin", "secretEnc": "",
    }))

    assert not result["ok"]
    assert "401" in result["error"]


def test_reboot_fritzbox_reports_unreachable_host(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    _tr064_client(monkeypatch, handler)

    result = asyncio.run(remote_admin.reboot_fritzbox("192.168.1.1", {
        "category": "login", "username": "admin", "secretEnc": "",
    }))

    assert not result["ok"]
    assert "fehlgeschlagen" in result["error"]


# --- SSH command timeout --------------------------------------------------------------------

import pytest  # noqa: E402


class _HangingConnection:
    def __init__(self):
        self.commands: list[str] = []

    async def run(self, command: str, check: bool = False):
        self.commands.append(command)
        await asyncio.sleep(3600)


def _patch_ssh(monkeypatch, connection) -> None:
    monkeypatch.setattr(asyncssh, "connect", lambda **kwargs: _FakeConnectContextManager(connection))
    monkeypatch.setattr(remote_admin, "_decode_secret", lambda account: ("hunter2", ""))


_TIMEOUT_CALLS = [
    lambda: remote_admin.list_remote_containers("h", _account()),
    lambda: remote_admin.remote_container_logs("h", _account(), "abc"),
    lambda: remote_admin.list_remote_proxmox_guests("h", _account()),
    lambda: remote_admin.run_remote_proxmox_guest_command("h", _account(), "vm", "100", "stop"),
    lambda: remote_admin.run_remote_lxc_journalctl("h", _account(), "101"),
    lambda: remote_admin.run_remote_docker_command("h", _account(), "stop", "abc"),
]


@pytest.mark.parametrize("call", _TIMEOUT_CALLS)
def test_ssh_commands_time_out(monkeypatch, call):
    _patch_ssh(monkeypatch, _HangingConnection())
    monkeypatch.setattr(remote_admin, "_SSH_COMMAND_TIMEOUT", 0.05)
    monkeypatch.setattr(remote_admin, "_SSH_LOG_TIMEOUT", 0.05)

    result = asyncio.run(call())

    assert result["ok"] is False
    assert "Zeitüberschreitung" in result["error"]


def test_log_commands_use_longer_timeout(monkeypatch):
    seen = []

    async def fake_run(connection, command, timeout=None):
        seen.append(timeout)
        return _FakeRunResult("x")

    _patch_ssh(monkeypatch, _FakeConnection({}))
    monkeypatch.setattr(remote_admin, "_run", fake_run)

    asyncio.run(remote_admin.remote_container_logs("h", _account(), "abc"))
    asyncio.run(remote_admin.run_remote_lxc_journalctl("h", _account(), "101"))
    asyncio.run(remote_admin.run_remote_docker_command("h", _account(), "stop", "abc"))

    assert seen == [remote_admin._SSH_LOG_TIMEOUT, remote_admin._SSH_LOG_TIMEOUT, None]
