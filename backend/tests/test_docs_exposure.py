import asyncio

from app import db, docs


def _gen():
    asyncio.run(docs.generate(db.get_settings(), use_llm=False))


def test_empty_state_and_thirteen_chapters(temp_db):
    _gen()
    pages = db.list_doc_pages()
    slugs = [p["slug"] for p in sorted(pages, key=lambda p: p["sortOrder"])]
    assert len(slugs) == 13 and slugs[-3:] == ["erreichbarkeit", "zugaenge-und-konten", "notfall"]
    assert "Noch keine Erreichbarkeits-Daten" in db.get_doc_page("erreichbarkeit")["bodyMd"]


def test_chain_rendered_escaped_and_manual_page_kept(temp_db):
    db.replace_exposure_facts("cloudflared", "a", [{"kind": "tunnel_ingress", "key": "x", "data": {
        "host": "evil|`<b>.example.net", "origin": "http://192.0.2.77:80", "via": "192.0.2.30"}}])
    _gen()
    body = db.get_doc_page("erreichbarkeit")["bodyMd"]
    assert "Von außen erreichbar" in body and "evil" in body
    assert "|`" not in body and "<b>" not in body
    db.set_doc_page_body("erreichbarkeit", "mein Text")
    _gen()
    assert db.get_doc_page("erreichbarkeit")["bodyMd"].strip() == "mein Text"


def test_portforward_scan_marker_shows_no_forwards_and_wan_row_with_ip_wins(temp_db):
    from app import db, docs
    db.replace_exposure_facts("unifi_classic", "acc", [{"kind": "portforward_scan", "key": "scan", "data": {"count": 0}}])
    assert "keine Portweiterleitungen" in docs._exposure_section()
    def res(ext, facts):
        return {"kind": "wan", "source": "unifi", "siteExternalId": ext, "externalId": "w",
                "name": f"WAN-{ext}", "facts": facts}

    db.sync_network_resources("a", [res("s1", {})], [("s1", "wan")])
    db.sync_network_resources("b", [res("s2", {"ip": "203.0.113.7"})], [("s2", "wan")])
    section = docs._network_resources_section()
    assert "203.0.113.7" in section and "WAN-s1" not in section
