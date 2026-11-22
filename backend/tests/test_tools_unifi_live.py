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
