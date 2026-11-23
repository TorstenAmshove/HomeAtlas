"""Wiring of get_proxmox_guest / get_proxmox_node in tools.py: account selection (incl. the
allowProbe opt-in), fixed messages, no secret in results, chat/MCP exposure, character limit."""
import asyncio
import json

import httpx
import pytest

from app import crypto, db, mcp_server, prompts, proxmox_live, tools

SECRET = "11111111-2222-3333-4444-555555555555"
TOOLS = ("get_proxmox_guest", "get_proxmox_node")


@pytest.fixture(autouse=True)
def _key(tmp_path, monkeypatch):
    monkeypatch.setattr(crypto, "_KEY_PATH", tmp_path / "secret.key")
    monkeypatch.setattr(crypto, "_cached", None)
    yield
    proxmox_live._transport = None


def _account(label="PVE", category="proxmox", secret=SECRET, username="root@pam!ha", url="https://pve.lan:8006",
             allow_probe=True):
    return db.create_account({"label": label, "category": category, "url": url, "username": username,
                              "allowProbe": 1 if allow_probe else 0,
                              "secretEnc": crypto.encrypt(secret) if secret else "", "systemId": None})


def _call(args, name="get_proxmox_guest"):
    return json.loads(asyncio.run(tools.dispatch(name, args)))


def _handler(request):
    rest = request.url.path.removeprefix("/api2/json")
    if rest == "/nodes":
        return httpx.Response(200, json={"data": [{"node": "pve1"}]})
    if rest == "/nodes/pve1/qemu":
        return httpx.Response(200, json={"data": [{"vmid": 100, "name": "Nextcloud"}]})
    if rest == "/nodes/pve1/lxc":
        return httpx.Response(200, json={"data": []})
    if rest.endswith("/status/current"):
        return httpx.Response(200, json={"data": {"vmid": 100, "name": "Nextcloud", "status": "running",
                                                  "description": "GEHEIM-NOTIZ"}})
    if rest.endswith("/rrddata"):
        return httpx.Response(200, json={"data": [{"time": 1, "cpu": 0.5}]})
    if rest.endswith("/tasks"):
        return httpx.Response(200, json={"data": [{"upid": "UPID:x", "type": "vzdump", "status": "OK",
                                                   "starttime": 1, "endtime": 2, "user": "root@pam"}]})
    if rest == "/nodes/pve1/status":
        return httpx.Response(200, json={"data": {"cpu": 0.1, "uptime": 5}})
    return httpx.Response(404)


def test_no_account(temp_db):
    assert "Proxmox-Zugang" in _call({"guest": "100"})["error"]
    assert "Proxmox-Zugang" in _call({}, "get_proxmox_node")["error"]


def test_allow_probe_off(temp_db):
    _account(allow_probe=False)
    proxmox_live._transport = httpx.MockTransport(lambda r: pytest.fail("must not call"))
    assert "Zum Auslesen verwenden" in _call({"guest": "100"})["error"]


def test_multiple_accounts_need_account_id(temp_db):
    first, _ = _account("eins"), _account("zwei")
    assert first["id"] in _call({"guest": "x"})["error"] and "accountId" in _call({"guest": "x"})["error"]


def test_wrong_category_and_unknown_account_id(temp_db):
    other = _account("NAS", category="ssh")
    _account()
    assert "accountId" in _call({"guest": "x", "accountId": other["id"]})["error"]
    assert "accountId" in _call({"guest": "x", "accountId": "gibt-es-nicht"})["error"]
    assert "accountId" in _call({"guest": "x", "accountId": 5})["error"]


def test_account_without_secret_or_token_id(temp_db):
    _account(secret="")
    proxmox_live._transport = httpx.MockTransport(lambda r: pytest.fail("must not call"))
    assert "unvollständig" in _call({"guest": "100"})["error"]


def test_account_without_token_id(temp_db):
    _account(username="")
    assert "unvollständig" in _call({"guest": "100"})["error"]


def test_unreadable_secret(temp_db):
    _account()
    crypto._KEY_PATH.write_bytes(b"")  # lose the key
    monkey = crypto._cached
    crypto._cached = None
    try:
        result = _call({"guest": "100"})
    finally:
        crypto._cached = monkey
    assert "error" in result and SECRET not in json.dumps(result)


def test_bad_args(temp_db):
    _account()
    proxmox_live._transport = httpx.MockTransport(_handler)
    assert "guest" in _call({"guest": 5})["error"]
    assert "guest" in _call({})["error"]
    assert "timeframe" in _call({"guest": "100", "timeframe": "week"})["error"]
    assert "node" in _call({"node": 5}, "get_proxmox_node")["error"]


def test_guest_and_node_results_without_secret(temp_db):
    _account()
    seen = []

    def handler(request):
        seen.append(request.headers["authorization"])
        return _handler(request)

    proxmox_live._transport = httpx.MockTransport(handler)
    text = asyncio.run(tools.dispatch("get_proxmox_guest", {"guest": "nextcloud"}))
    result = json.loads(text)
    assert result["status"]["status"] == "running" and result["aufgaben"][0]["type"] == "vzdump"
    node_text = asyncio.run(tools.dispatch("get_proxmox_node", {}))
    assert json.loads(node_text)["node"] == "pve1"
    for t in (text, node_text):
        assert SECRET not in t and "GEHEIM-NOTIZ" not in t and "UPID" not in t
    assert set(seen) == {f"PVEAPIToken=root@pam!ha={SECRET}"}


def test_errors_become_messages(temp_db):
    _account()
    proxmox_live._transport = httpx.MockTransport(lambda r: httpx.Response(401, text=SECRET))
    result = _call({"guest": "100"})
    assert "PVEAuditor" in result["error"] and SECRET not in json.dumps(result)

    def boom(request):
        raise RuntimeError(SECRET)

    proxmox_live._transport = httpx.MockTransport(boom)
    result = _call({"guest": "100"})
    assert "error" in result and SECRET not in json.dumps(result)


def test_registered_for_chat_and_mcp_and_callable_via_mcp(temp_db):
    assert set(TOOLS) <= {d["name"] for d in tools.TOOL_DEFINITIONS}
    assert set(TOOLS) == set(tools._PROXMOX_LIVE_TOOLS)
    assert set(TOOLS) <= {t.name for t in asyncio.run(mcp_server._list_tools())}
    _account()
    proxmox_live._transport = httpx.MockTransport(_handler)
    blocks = asyncio.run(mcp_server._call_tool("get_proxmox_guest", {"guest": "100"}))
    assert json.loads(blocks[0].text)["status"]["status"] == "running" and SECRET not in blocks[0].text


def test_dispatch_char_limit(temp_db, monkeypatch):
    assert tools._PROXMOX_LIVE_MAX_RESULT_CHARS > tools._MAX_RESULT_CHARS
    _account()
    proxmox_live._transport = httpx.MockTransport(_handler)
    monkeypatch.setattr(tools, "_PROXMOX_LIVE_MAX_RESULT_CHARS", 50)
    assert "gekürzt" in asyncio.run(tools.dispatch("get_proxmox_guest", {"guest": "100"}))


def test_prompt_mentions_tools_and_data_rule():
    assert "get_proxmox_guest" in prompts.CHAT_SYSTEM and SECRET not in prompts.CHAT_SYSTEM
