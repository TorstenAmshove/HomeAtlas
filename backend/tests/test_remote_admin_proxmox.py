"""Regression tests for the Proxmox "Container laden" bug: a Proxmox host has no Docker CLI at
all, so `docker ps` over SSH failed with "bash: line 1: docker: command not found". These cover
the native `pct list`/`qm list` SSH fallback (remote_admin.list_remote_proxmox_guests) -- see
proxmox_probe.list_guests / test_proxmox_probe.py for the REST-API path that is tried first."""
import asyncio

import asyncssh

from app import remote_admin


def test_parse_pct_list_reads_vmid_status_and_name():
    text = (
        "VMID       Status     Lock         Name\n"
        "100        running                 nextcloud\n"
        "101        stopped                 pihole\n"
    )
    containers = remote_admin._parse_pct_list(text)
    assert containers == [
        {"id": "lxc:100", "name": "nextcloud", "image": "LXC-Container", "state": "running", "status": "running",
         "ip": "", "node": "", "vmid": "100", "kind": "container"},
        {"id": "lxc:101", "name": "pihole", "image": "LXC-Container", "state": "stopped", "status": "stopped",
         "ip": "", "node": "", "vmid": "101", "kind": "container"},
    ]


def test_parse_pct_list_handles_a_locked_row_with_extra_column():
    text = (
        "VMID       Status     Lock         Name\n"
        "100        running    backup       nextcloud\n"
    )
    containers = remote_admin._parse_pct_list(text)
    assert containers == [
        {"id": "lxc:100", "name": "nextcloud", "image": "LXC-Container", "state": "running", "status": "running",
         "ip": "", "node": "", "vmid": "100", "kind": "container"},
    ]


def test_parse_pct_list_ignores_empty_output():
    assert remote_admin._parse_pct_list("") == []
    assert remote_admin._parse_pct_list("VMID       Status     Lock         Name\n") == []


def test_parse_qm_list_reads_vmid_name_and_status():
    text = (
        "      VMID NAME                 STATUS     MEM(MB)    BOOTDISK(GB) PID\n"
        "       100 nextcloud-vm         running    2048              32.00 12345\n"
        "       101 test-vm              stopped    1024              20.00 0\n"
    )
    containers = remote_admin._parse_qm_list(text)
    assert containers == [
        {"id": "qemu:100", "name": "nextcloud-vm", "image": "VM (QEMU/KVM)", "state": "running", "status": "running",
         "ip": "", "node": "", "vmid": "100", "kind": "vm"},
        {"id": "qemu:101", "name": "test-vm", "image": "VM (QEMU/KVM)", "state": "stopped", "status": "stopped",
         "ip": "", "node": "", "vmid": "101", "kind": "vm"},
    ]


def test_parse_qm_list_ignores_empty_output():
    assert remote_admin._parse_qm_list("") == []


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
    return {"category": "login", "username": "root", "secretEnc": "", "port": 22}


def test_list_remote_proxmox_guests_never_runs_docker(monkeypatch):
    connection = _FakeConnection({
        "pct list": _FakeRunResult("VMID       Status     Lock         Name\n100        running                 pihole\n"),
        "qm list": _FakeRunResult(
            "      VMID NAME                 STATUS     MEM(MB)    BOOTDISK(GB) PID\n"
            "       200 nextcloud-vm         running    2048              32.00 12345\n"
        ),
    })
    monkeypatch.setattr(asyncssh, "connect", lambda **kwargs: _FakeConnectContextManager(connection))
    monkeypatch.setattr(remote_admin, "_decode_secret", lambda account: ("hunter2", ""))

    result = asyncio.run(remote_admin.list_remote_proxmox_guests("10.0.0.20", _account()))

    assert result["ok"]
    names = {c["name"] for c in result["containers"]}
    assert names == {"pihole", "nextcloud-vm"}
    assert connection.commands == ["pct list", "qm list"]
    assert not any("docker" in c for c in connection.commands)


def test_list_remote_proxmox_guests_reports_a_clear_error_when_both_commands_fail(monkeypatch):
    connection = _FakeConnection({})  # every command falls through to the "not found" default
    monkeypatch.setattr(asyncssh, "connect", lambda **kwargs: _FakeConnectContextManager(connection))
    monkeypatch.setattr(remote_admin, "_decode_secret", lambda account: ("hunter2", ""))

    result = asyncio.run(remote_admin.list_remote_proxmox_guests("10.0.0.21", _account()))

    assert not result["ok"]
    assert "command not found" in result["error"]
    assert result["containers"] == []


def test_list_remote_proxmox_guests_survives_qm_missing_when_pct_works(monkeypatch):
    """A container-only Proxmox node (no VMs configured) is a normal case, not a failure -- one
    command's clean success must not be discarded because the other returned nothing useful."""
    connection = _FakeConnection({
        "pct list": _FakeRunResult("VMID       Status     Lock         Name\n100        running                 pihole\n"),
    })
    monkeypatch.setattr(asyncssh, "connect", lambda **kwargs: _FakeConnectContextManager(connection))
    monkeypatch.setattr(remote_admin, "_decode_secret", lambda account: ("hunter2", ""))

    result = asyncio.run(remote_admin.list_remote_proxmox_guests("10.0.0.22", _account()))

    assert result["ok"]
    assert [c["name"] for c in result["containers"]] == ["pihole"]


def test_run_remote_proxmox_guest_command_uses_pct_for_containers_and_never_docker(monkeypatch):
    connection = _FakeConnection({"pct reboot 101": _FakeRunResult("")})
    monkeypatch.setattr(asyncssh, "connect", lambda **kwargs: _FakeConnectContextManager(connection))
    monkeypatch.setattr(remote_admin, "_decode_secret", lambda account: ("hunter2", ""))

    result = asyncio.run(remote_admin.run_remote_proxmox_guest_command("10.0.0.20", _account(), "container", "101", "restart"))

    assert result["ok"]
    assert connection.commands == ["pct reboot 101"]


def test_run_remote_proxmox_guest_command_uses_qm_for_vms_and_maps_stop_to_shutdown(monkeypatch):
    connection = _FakeConnection({"qm shutdown 202": _FakeRunResult("")})
    monkeypatch.setattr(asyncssh, "connect", lambda **kwargs: _FakeConnectContextManager(connection))
    monkeypatch.setattr(remote_admin, "_decode_secret", lambda account: ("hunter2", ""))

    result = asyncio.run(remote_admin.run_remote_proxmox_guest_command("10.0.0.20", _account(), "vm", "202", "stop"))

    assert result["ok"]
    assert connection.commands == ["qm shutdown 202"]


def test_run_remote_proxmox_guest_command_rejects_unknown_action(monkeypatch):
    result = asyncio.run(remote_admin.run_remote_proxmox_guest_command("10.0.0.20", _account(), "vm", "202", "delete"))
    assert not result["ok"]
    assert "Unbekannte Aktion" in result["error"]


def test_run_remote_proxmox_guest_command_reports_failure(monkeypatch):
    connection = _FakeConnection({"pct start 101": _FakeRunResult("", 1, "unable to start")})
    monkeypatch.setattr(asyncssh, "connect", lambda **kwargs: _FakeConnectContextManager(connection))
    monkeypatch.setattr(remote_admin, "_decode_secret", lambda account: ("hunter2", ""))

    result = asyncio.run(remote_admin.run_remote_proxmox_guest_command("10.0.0.20", _account(), "container", "101", "start"))

    assert not result["ok"]
    assert "unable to start" in result["error"]


def test_run_remote_lxc_journalctl_uses_pct_exec_never_docker(monkeypatch):
    connection = _FakeConnection({
        "pct exec 101 -- journalctl -n 200 --no-pager": _FakeRunResult("Jan 01 12:00:00 host systemd[1]: Started."),
    })
    monkeypatch.setattr(asyncssh, "connect", lambda **kwargs: _FakeConnectContextManager(connection))
    monkeypatch.setattr(remote_admin, "_decode_secret", lambda account: ("hunter2", ""))

    result = asyncio.run(remote_admin.run_remote_lxc_journalctl("10.0.0.20", _account(), "101"))

    assert result["ok"]
    assert "Started." in result["text"]
    assert connection.commands == ["pct exec 101 -- journalctl -n 200 --no-pager"]
    assert not any("docker" in c for c in connection.commands)


def test_run_remote_lxc_journalctl_reports_failure(monkeypatch):
    connection = _FakeConnection({})  # falls through to the "not found" default -> exit 127
    monkeypatch.setattr(asyncssh, "connect", lambda **kwargs: _FakeConnectContextManager(connection))
    monkeypatch.setattr(remote_admin, "_decode_secret", lambda account: ("hunter2", ""))

    result = asyncio.run(remote_admin.run_remote_lxc_journalctl("10.0.0.20", _account(), "999"))

    assert not result["ok"]


def test_reboot_host_tries_passwordless_sudo_then_plain_reboot(monkeypatch):
    connection = _FakeConnection({"sudo -n reboot 2>/dev/null || reboot": _FakeRunResult("")})
    monkeypatch.setattr(asyncssh, "connect", lambda **kwargs: _FakeConnectContextManager(connection))
    monkeypatch.setattr(remote_admin, "_decode_secret", lambda account: ("hunter2", ""))

    result = asyncio.run(remote_admin.reboot_host("10.0.0.30", _account()))

    assert result["ok"]
    assert connection.commands == ["sudo -n reboot 2>/dev/null || reboot"]


def test_reboot_host_reports_failure(monkeypatch):
    connection = _FakeConnection({
        "sudo -n reboot 2>/dev/null || reboot": _FakeRunResult("", 1, "Permission denied"),
    })
    monkeypatch.setattr(asyncssh, "connect", lambda **kwargs: _FakeConnectContextManager(connection))
    monkeypatch.setattr(remote_admin, "_decode_secret", lambda account: ("hunter2", ""))

    result = asyncio.run(remote_admin.reboot_host("10.0.0.30", _account()))

    assert not result["ok"]
    assert "Permission denied" in result["error"]


# --- reboot_host: a dropped connection after the command is success ---------------------------



class _RebootConnection:
    def __init__(self, behaviour):
        self.behaviour = behaviour

    async def run(self, command, check=False):
        return await self.behaviour()


class _RebootContext:
    def __init__(self, connection, exit_error=None):
        self._connection = connection
        self._exit_error = exit_error

    async def __aenter__(self):
        return self._connection

    async def __aexit__(self, *exc_info):
        if self._exit_error:
            raise self._exit_error
        return False


def _reboot(monkeypatch, behaviour, exit_error=None):
    import asyncio

    from app import remote_admin
    monkeypatch.setattr(asyncssh, "connect",
                        lambda **kw: _RebootContext(_RebootConnection(behaviour), exit_error))
    monkeypatch.setattr(remote_admin, "_decode_secret", lambda account: ("pw", ""))
    monkeypatch.setattr(remote_admin, "_SSH_REBOOT_TIMEOUT", 0.05)
    account = {"category": "login", "username": "root", "secretEnc": "", "port": 22}
    return asyncio.run(remote_admin.reboot_host("10.0.0.5", account))


class _Result:
    def __init__(self, exit_status, stderr=""):
        self.exit_status, self.stderr, self.stdout = exit_status, stderr, ""


def test_reboot_host_treats_connection_loss_after_command_as_success(monkeypatch):
    async def lost():
        raise asyncssh.ConnectionLost("gone")
    assert _reboot(monkeypatch, lost) == {"ok": True, "error": ""}


def test_reboot_host_treats_missing_exit_status_as_success(monkeypatch):
    async def none():
        return _Result(None)
    assert _reboot(monkeypatch, none)["ok"]


def test_reboot_host_treats_timeout_after_command_as_success(monkeypatch):
    import asyncio

    async def hang():
        await asyncio.sleep(3600)
    assert _reboot(monkeypatch, hang)["ok"]


def test_reboot_host_ignores_error_on_connection_close(monkeypatch):
    async def ok():
        return _Result(0)
    assert _reboot(monkeypatch, ok, exit_error=OSError("reset"))["ok"]


def test_reboot_host_still_fails_on_connect_error(monkeypatch):
    import asyncio

    from app import remote_admin

    def boom(**kw):
        raise OSError("no route")
    monkeypatch.setattr(asyncssh, "connect", boom)
    monkeypatch.setattr(remote_admin, "_decode_secret", lambda account: ("pw", ""))
    account = {"category": "login", "username": "root", "secretEnc": "", "port": 22}
    result = asyncio.run(remote_admin.reboot_host("10.0.0.5", account))
    assert not result["ok"] and "fehlgeschlagen" in result["error"]


def test_reboot_host_still_fails_on_nonzero_exit(monkeypatch):
    async def bad():
        return _Result(1, "permission denied")
    result = _reboot(monkeypatch, bad)
    assert not result["ok"] and "permission denied" in result["error"]
