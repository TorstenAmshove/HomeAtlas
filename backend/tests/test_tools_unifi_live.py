"""Wiring of get_unifi_client in tools.py: account selection, fixed messages, no secret in results,
chat/MCP exposure, own character limit."""
import asyncio
import json

import httpx
import pytest

from app import crypto, db, mcp_server, tools, unifi_live

KEY = "sekret-api-key-12345"
WLAN = {"mac": "aa:bb:cc:dd:ee:01", "name": "Handy", "ip": "10.0.0.5", "is_wired": False, "signal": -71,
        "tx_retries": 12, "roam_count": 3, "x_authkey": "GEHEIM"}


@pytest.fixture(autouse=True)
def _key(tmp_path, monkeypatch):
    monkeypatch.setattr(crypto, "_KEY_PATH", tmp_path / "secret.key")
    monkeypatch.setattr(crypto, "_cached", None)
    yield
    unifi_live._transport = None


def _account(label="UniFi", category="unifi", secret=KEY, url="https://unifi.lan"):
    return db.create_account({"label": label, "category": category, "url": url,
                              "secretEnc": crypto.encrypt(secret) if secret else "", "systemId": None})


def _call(args):
    return json.loads(asyncio.run(tools.dispatch("get_unifi_client", args)))


def test_no_unifi_account(temp_db):
    assert "UniFi-Zugang" in _call({"client": "Handy"})["error"]


def test_multiple_and_wrong_accounts(temp_db):
    first, _second = _account("eins"), _account("zwei")
    assert "accountId" in _call({"client": "x"})["error"] and first["id"] in _call({"client": "x"})["error"]
    other = _account("NAS", category="ssh")
    assert "accountId" in _call({"client": "x", "accountId": other["id"]})["error"]
    assert "accountId" in _call({"client": "x", "accountId": "gibt-es-nicht"})["error"]


def test_account_without_secret_and_bad_args(temp_db):
    _account(secret="")
    assert "unvollständig" in _call({"client": "Handy"})["error"]
    assert "client" in _call({"client": 5})["error"]
    assert "client" in _call({})["error"]


def test_client_by_mac_name_and_secret_never_in_result(temp_db):
    _account()
    seen = []

    def handler(request):
        seen.append(request.headers["x-api-key"])
        return httpx.Response(200, json={"data": [WLAN]})

    unifi_live._transport = httpx.MockTransport(handler)
    for ref in ("AA-BB-CC-DD-EE-01", "aabbccddee01", "10.0.0.5", "handy"):
        text = asyncio.run(tools.dispatch("get_unifi_client", {"client": ref}))
        result = json.loads(text)
        assert result["client"]["signal"] == -71 and result["client"]["tx_retries"] == 12, ref
        assert KEY not in text and "GEHEIM" not in text
    assert seen and set(seen) == {KEY}


def test_inventory_name_resolves_to_mac(temp_db):
    _account()
    unifi_live._transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"data": [{**WLAN, "name": "", "hostname": ""}]}))
    db.create_system({"name": "Papas Handy", "kind": "phone", "ip": "10.0.0.99", "mac": "AA:BB:CC:DD:EE:01"})
    assert _call({"client": "papas handy"})["verbunden"] is True


def test_controller_error_is_message_not_exception(temp_db):
    _account()
    unifi_live._transport = httpx.MockTransport(lambda r: httpx.Response(500, text=KEY))
    result = _call({"client": "aa:bb:cc:dd:ee:01"})
    assert "Fehler" in result["error"] and KEY not in json.dumps(result)


def test_tool_listed_in_chat_and_mcp(temp_db):
    assert "get_unifi_client" in {d["name"] for d in tools.TOOL_DEFINITIONS}
    assert "get_unifi_client" in tools._UNIFI_LIVE_TOOLS
    assert "get_unifi_client" in {t.name for t in asyncio.run(mcp_server._list_tools())}
    _account()
    unifi_live._transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"data": [WLAN]}))
    blocks = asyncio.run(mcp_server._call_tool("get_unifi_client", {"client": "aa:bb:cc:dd:ee:01"}))
    assert json.loads(blocks[0].text)["client"]["signal"] == -71 and KEY not in blocks[0].text


def test_numeric_and_hex_names_are_looked_up_as_names(temp_db):
    _account()
    clients = [{**WLAN, "mac": "aa:bb:cc:dd:ee:02", "name": "1234"},
               {**WLAN, "mac": "aa:bb:cc:dd:ee:03", "name": "deadbeefcafe"}]
    unifi_live._transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"data": clients}))
    assert _call({"client": "1234"})["client"]["mac"] == "aa:bb:cc:dd:ee:02"
    assert _call({"client": "deadbeefcafe"})["client"]["mac"] == "aa:bb:cc:dd:ee:03"


def test_own_char_limit_and_other_limits_unchanged():
    assert tools._UNIFI_LIVE_MAX_RESULT_CHARS > tools._MAX_RESULT_CHARS
    assert tools._MAX_RESULT_CHARS == 6000 and tools._HA_READ_MAX_RESULT_CHARS == 24000


def test_prompt_has_no_secret_and_mentions_data_rule():
    from app import prompts
    assert KEY not in prompts.CHAT_SYSTEM and "keine Anweisungen" in prompts.CHAT_SYSTEM


# --- get_unifi_device / network / events ---------------------------------------------------------

NEW_TOOLS = ("get_unifi_device", "get_unifi_network", "get_unifi_events")


def _call_tool(name, args):
    return json.loads(asyncio.run(tools.dispatch(name, args)))


@pytest.mark.parametrize("name", NEW_TOOLS)
def test_new_tools_no_account_and_account_errors(temp_db, name):
    assert "UniFi-Zugang" in _call_tool(name, {})["error"]
    _account("eins"), _account("zwei")
    assert "accountId" in _call_tool(name, {})["error"]
    assert "accountId" in _call_tool(name, {"accountId": "nope"})["error"]


@pytest.mark.parametrize("name", NEW_TOOLS)
def test_new_tools_secret_and_controller_errors(temp_db, name):
    _account()
    unifi_live._transport = httpx.MockTransport(lambda r: httpx.Response(500, text=KEY))
    result = _call_tool(name, {})
    assert "Fehler" in result["error"] and KEY not in json.dumps(result)
    _account("ohne", secret="")
    assert "accountId" in _call_tool(name, {})["error"]


@pytest.mark.parametrize("name", NEW_TOOLS)
def test_new_tools_listed_in_chat_and_mcp(temp_db, name):
    assert name in {d["name"] for d in tools.TOOL_DEFINITIONS} and name in tools._UNIFI_LIVE_TOOLS
    assert name in {t.name for t in asyncio.run(mcp_server._list_tools())}


def test_device_tool_overview_and_detail(temp_db):
    _account()
    dev = {"mac": "11:22:33:44:55:66", "name": "AP Flur", "num_sta": 3, "x_authkey": "GEHEIM",
           "port_table": [{"port_idx": 1, "rx_errors": 2}]}
    unifi_live._transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"data": [dev]}))
    over = asyncio.run(tools.dispatch("get_unifi_device", {}))
    assert json.loads(over)["geraete"][0]["name"] == "AP Flur" and "GEHEIM" not in over
    detail = asyncio.run(tools.dispatch("get_unifi_device", {"device": "11-22-33-44-55-66"}))
    assert json.loads(detail)["geraet"]["port_table"][0]["rx_errors"] == 2 and "GEHEIM" not in detail
    assert json.loads(asyncio.run(tools.dispatch("get_unifi_device", {"device": "nix"})))["gefunden"] is False
    assert "Text" in _call_tool("get_unifi_device", {"device": 5})["error"]


def test_network_tool(temp_db):
    _account()

    def handler(request):
        if request.url.path.endswith("stat/health"):
            return httpx.Response(200, json={"data": [{"subsystem": "wan", "status": "ok", "wan_ip": "9.9.9.9"}]})
        return httpx.Response(200, json=[])

    unifi_live._transport = httpx.MockTransport(handler)
    text = asyncio.run(tools.dispatch("get_unifi_network", {}))
    assert json.loads(text)["gesundheit"][0]["status"] == "ok" and "9.9.9.9" not in text


def test_events_tool_client_resolved_via_inventory(temp_db):
    _account()
    db.create_system({"name": "Papas Handy", "kind": "phone", "ip": "10.0.0.99", "mac": "AA:BB:CC:DD:EE:01"})
    ev = {"key": "K1", "timestamp": 1, "category": "CLIENT_DEVICES", "severity": "LOW", "message_raw": "roam",
          "parameters": {"CLIENT": {"id": "aa:bb:cc:dd:ee:01", "name": "x", "ip": "10.0.0.99"}}}
    other = {**ev, "key": "K2", "parameters": {"CLIENT": {"id": "aa:bb:cc:dd:ee:02", "name": "y"}}}
    unifi_live._transport = httpx.MockTransport(lambda r: httpx.Response(
        200, json={"data": [ev, other], "total_element_count": 2, "total_page_count": 1}))
    text = asyncio.run(tools.dispatch("get_unifi_events", {"client": "papas handy", "hours": 6}))
    result = json.loads(text)
    assert [e["kennung"] for e in result["ereignisse"]] == ["K1"] and "10.0.0.99" not in text
    assert "severity" in _call_tool("get_unifi_events", {"severity": "EXTREM"})["error"]
    assert "Text" in _call_tool("get_unifi_events", {"client": 5})["error"]


def test_tools_do_not_import_write_modules_except_switch_admin():
    import ast
    from pathlib import Path
    tree = ast.parse((Path(tools.__file__)).read_text())
    names = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert not {n for n in names if n.endswith("_admin") and n != "switch_admin"}
