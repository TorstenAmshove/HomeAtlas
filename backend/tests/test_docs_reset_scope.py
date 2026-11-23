import asyncio

from app import db, docs, llm_providers
from app.routes import docs as routes_docs


def _llm(monkeypatch):
    calls = []

    async def chat(*a, **k):
        calls.append(1)
        return type("R", (), {"text": "KI-Text"})()

    monkeypatch.setattr(llm_providers, "is_configured", lambda *a, **k: True)
    monkeypatch.setattr(llm_providers, "chat", chat)
    return calls


def _gen(**kw):
    return asyncio.run(docs.generate(db.get_settings(), use_llm=False, **kw))


def _reset(slug):
    return asyncio.run(routes_docs.reset_doc(slug, {}))


def _versions():
    return {p["slug"]: len(db.list_doc_versions(p["slug"])) for p in db.list_doc_pages()}


def test_reset_regenerates_only_target(temp_db, monkeypatch):
    _gen()
    db.create_system({"kind": "server", "name": "S1", "ip": "192.168.1.5"})
    db.create_system({"kind": "nas", "name": "N1", "ip": "192.168.1.6"})
    before = _versions()
    calls = _llm(monkeypatch)
    _reset("ueberblick")
    after = _versions()
    assert len(calls) <= 1
    assert after["ueberblick"] == before["ueberblick"] + 1
    assert all(after[s] == before[s] for s in after if s != "ueberblick")


def test_reset_keeps_other_pinned_pages(temp_db):
    _gen()
    db.set_doc_page_body("notfall", "mein Text")
    _reset("ueberblick")
    page = db.get_doc_page("notfall")
    assert page["bodyMd"] == "mein Text" and page["generated"] == 0


def test_reset_pinned_target_is_regenerated(temp_db):
    _gen()
    db.set_doc_page_body("notfall", "mein Text")
    _reset("notfall")
    page = db.get_doc_page("notfall")
    assert page["generated"] == 1 and page["bodyMd"] != "mein Text\n"


def test_reset_chapter_without_llm_branch(temp_db, monkeypatch):
    _gen()
    calls = _llm(monkeypatch)
    _reset("erreichbarkeit")
    assert calls == []
    assert db.get_doc_page("erreichbarkeit") is not None


def test_generate_without_only_slug_writes_all(temp_db):
    assert _gen() == [t.slug for t in docs.TOPICS]
    assert _gen(only_slug="notfall") == ["notfall"]


def test_reset_unknown_slug(temp_db, monkeypatch):
    calls = _llm(monkeypatch)
    assert _reset("gibt-es-nicht") == {"page": None}
    assert calls == []
