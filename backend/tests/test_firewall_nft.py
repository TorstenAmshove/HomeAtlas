import asyncio
import json
import sys
import types

import pytest

from app import firewall_nft as nft


def _rule(chain, *expr, table="filter", family="inet"):
    return {"rule": {"family": family, "table": table, "chain": chain, "expr": list(expr)}}


def _m(proto, field, right, op="=="):
    return {"match": {"op": op, "left": {"payload": {"protocol": proto, "field": field}}, "right": right}}


def _chain(name, hook, policy="drop", family="inet", table="filter", prio=0):
    return {"chain": {"family": family, "table": table, "name": name, "type": "filter", "hook": hook,
                      "prio": prio, "policy": policy}}


def _doc(*items):
    return json.dumps({"nftables": [{"metainfo": {"version": "1.0"}}, {"table": {"family": "inet", "name": "filter"}},
                                    *items]})


CT = {"match": {"op": "==", "left": {"ct": {"key": "state"}}, "right": ["established", "related"]}}
IIF = {"match": {"op": "==", "left": {"meta": {"key": "iifname"}}, "right": "lo"}}
ACCEPT = {"accept": None}


def _chains(facts):
    return {f["data"]["chain"]: f["data"] for f in facts if f["kind"] == "nft_chain"}


def test_parses_real_structure_inet_filter_3_chains():
    facts = nft.parse_ruleset(_doc(
        _chain("input", "input"), _chain("forward", "forward"), _chain("output", "output"),
        _rule("input", CT, ACCEPT), _rule("input", IIF, ACCEPT),
        _rule("input", _m("ip", "saddr", {"prefix": {"addr": "192.168.1.0", "len": 24}}),
              _m("tcp", "dport", 22), {"counter": {"packets": 3, "bytes": 9}}, ACCEPT)), "sys1")
    host = facts[0]
    assert host["kind"] == "nft_host" and host["data"]["chains"] == 3 and host["data"]["rules"] == 3
    c = _chains(facts)["input"]
    assert (c["hook"], c["policy"], c["prio"], c["systemId"]) == ("input", "drop", 0, "sys1")
    assert c["rules"][0]["matches"] == [{"f": "ct_state", "v": ["established", "related"]}]
    assert c["rules"][1]["matches"] == [{"f": "iif", "v": ["lo"]}]
    assert c["rules"][2] == {"no": 3, "verdict": "accept", "unsupported": [], "matches": [
        {"f": "saddr", "v": ["192.168.1.0/24"]}, {"f": "dport", "proto": "tcp", "v": ["22"]}]}
    assert facts[1]["key"] == "nft:sys1:inet/filter/input"


def test_policy_accept_and_multiple_tables():
    facts = nft.parse_ruleset(_doc(_chain("input", "input", "accept"),
                                   _chain("in2", "input", "drop", family="ip", table="other", prio=-10)))
    c = _chains(facts)
    assert c["input"]["policy"] == "accept" and c["in2"]["table"] == "other" and c["in2"]["prio"] == -10


def test_sets_ranges_negation_flagged():
    facts = nft.parse_ruleset(_doc(
        _chain("input", "input"),
        _rule("input", _m("tcp", "dport", {"set": [22, {"range": [8000, 8100]}]}), ACCEPT),
        _rule("input", _m("tcp", "dport", 22, op="!="), ACCEPT),
        _rule("input", _m("ip", "saddr", "@missing"), ACCEPT),
        {"set": {"family": "inet", "table": "filter", "name": "lan", "elem": ["10.0.0.1", {"prefix": {"addr": "10.1.0.0", "len": 16}}]}},
        _rule("input", _m("ip", "saddr", "@lan"), ACCEPT)))
    r = _chains(facts)["input"]["rules"]
    assert r[0]["matches"][0]["v"] == ["22", "8000-8100"] and not r[0]["unsupported"]
    assert "operator" in r[1]["unsupported"]
    assert "set" in r[2]["unsupported"]
    assert r[3]["matches"][0]["v"] == ["10.0.0.1", "10.1.0.0/16"]


def test_chain_without_hook_and_other_families_ignored():
    facts = nft.parse_ruleset(_doc(
        {"chain": {"family": "inet", "table": "filter", "name": "helper"}},
        _chain("in6", "input", family="ip6", table="t6"), _chain("input", "input")))
    assert list(_chains(facts)) == ["input"] and facts[0]["data"]["ignoredChains"] == 1


@pytest.mark.parametrize("expr,reason", [
    ({"jump": {"target": "x"}}, "jump"), ({"goto": {"target": "x"}}, "goto"),
    ({"masquerade": None}, "masquerade"), ({"limit": {"rate": 5}}, "limit"),
    ({"match": {"op": "==", "left": {"meta": {"key": "l4proto"}}, "right": "tcp"}}, "match"),
    (_m("ip6", "saddr", "::1"), "ip6.saddr"), (_m("ip", "saddr", "::1"), "address"),
])
def test_unsupported_expr_flagged(expr, reason):
    facts = nft.parse_ruleset(_doc(_chain("input", "input"), _rule("input", expr, ACCEPT)))
    assert reason in _chains(facts)["input"]["rules"][0]["unsupported"]


def test_counter_log_do_not_matter():
    facts = nft.parse_ruleset(_doc(_chain("input", "input"),
                                   _rule("input", {"counter": None}, {"log": {"prefix": "secret"}}, {"drop": None})))
    rule = _chains(facts)["input"]["rules"][0]
    assert rule["verdict"] == "drop" and rule["unsupported"] == [] and "secret" not in json.dumps(facts)


def test_reject_is_kept_as_reject():
    facts = nft.parse_ruleset(_doc(_chain("input", "input"), _rule("input", {"reject": {"type": "icmp"}})))
    assert _chains(facts)["input"]["rules"][0]["verdict"] == "reject"


def test_no_raw_json_or_comment_stored():
    rule = _rule("input", ACCEPT)
    rule["rule"]["comment"] = "geheim-kommentar"
    facts = nft.parse_ruleset(_doc(_chain("input", "input"), rule))
    assert "geheim-kommentar" not in json.dumps(facts) and "metainfo" not in json.dumps(facts)


@pytest.mark.parametrize("text", ["", "no json", "[]", '{"nftables": 3}', '{"x": 1}'])
def test_invalid_json_raises(text):
    with pytest.raises(nft.NftError):
        nft.parse_ruleset(text)


def test_too_many_rules_raises():
    rules = [_rule("input", ACCEPT) for _ in range(nft._MAX_RULES + 1)]
    with pytest.raises(nft.NftError):
        nft.parse_ruleset(_doc(_chain("input", "input"), *rules))


def test_empty_ruleset_is_a_successful_read():
    facts = nft.parse_ruleset(_doc())
    assert [f["kind"] for f in facts] == ["nft_host"] and facts[0]["data"]["chains"] == 0


# ---- SSH ------------------------------------------------------------------------------------

class _Conn:
    def __init__(self, result, calls):
        self.result, self.calls = result, calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def run(self, command, **kwargs):
        self.calls.append(command)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _fake_ssh(monkeypatch, result, calls):
    mod = types.SimpleNamespace(
        import_private_key=lambda s, p=None: object(),
        connect=lambda **kw: _Conn(result, calls))
    monkeypatch.setitem(sys.modules, "asyncssh", mod)
    monkeypatch.setattr(nft.crypto, "decrypt", lambda v: "k")


def _probe(monkeypatch, result):
    calls: list = []
    _fake_ssh(monkeypatch, result, calls)
    return asyncio.run(nft.probe("192.0.2.5", {"systemId": "s1", "secretEnc": "x"})), calls


def _res(out, status=0):
    return types.SimpleNamespace(stdout=out, exit_status=status)


def test_fixed_command_only(monkeypatch):
    out, calls = _probe(monkeypatch, _res(_doc(_chain("input", "input"))))
    assert out["ok"] and calls == ["nft -j list ruleset"]


def test_sudo_failure_is_unreadable_not_empty(monkeypatch):
    out, _ = _probe(monkeypatch, _res("", 1))
    assert not out["ok"] and out["facts"] == []
    out, _ = _probe(monkeypatch, _res(_doc(), 1))
    assert not out["ok"]


def test_oversize_output_rejected(monkeypatch):
    out, _ = _probe(monkeypatch, _res(" " * (nft._MAX_BYTES + 1)))
    assert not out["ok"]


def test_invalid_json_or_timeout_is_unreadable(monkeypatch):
    out, _ = _probe(monkeypatch, _res("not json"))
    assert not out["ok"]
    out, _ = _probe(monkeypatch, asyncio.TimeoutError())
    assert not out["ok"] and "Zeitüberschreitung" in out["error"]


def test_errors_have_no_output_text(monkeypatch):
    out, _ = _probe(monkeypatch, _res("TOPSECRET-OUTPUT"))
    assert "TOPSECRET" not in out["error"]
    out, _ = _probe(monkeypatch, RuntimeError("TOPSECRET-MSG"))
    assert "TOPSECRET" not in out["error"]


def test_command_matches_readme():
    from pathlib import Path
    readme = (Path(__file__).resolve().parents[2] / "README.md").read_text()
    assert f"sudo /usr/sbin/{nft._NFT_COMMAND}" in readme
