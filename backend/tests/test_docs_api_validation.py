import asyncio

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import db, docs
from app.routes import docs as routes_docs


def _gen(**kw):
    return asyncio.run(docs.generate(db.get_settings(), use_llm=False, **kw))


def _run(coro):
    return asyncio.run(coro)


def _stale(slug="alt", generated=True, manual=""):
    db.upsert_doc_page(slug, "x", "Alt", "Text", "", 99, generated=generated)
    db.snapshot_doc_page(slug, "test")
    if manual:
        db.set_doc_page_manual(slug, manual)


def test_reset_unknown_slug_404(temp_db):
    with pytest.raises(HTTPException) as e:
        _run(routes_docs.reset_doc("gibt-es-nicht", {}))
    assert e.value.status_code == 404


def test_reset_unknown_slug_does_not_generate(temp_db, monkeypatch):
    called = []

    async def fake(*a, **k):
        called.append(1)

    monkeypatch.setattr(docs, "generate", fake)
    with pytest.raises(HTTPException):
        _run(routes_docs.reset_doc("gibt-es-nicht", {}))
    assert not called and db.get_doc_page("gibt-es-nicht") is None


def test_reset_unknown_slug_404_before_409(temp_db, monkeypatch):
    monkeypatch.setattr(docs, "is_generating", lambda: True)
    with pytest.raises(HTTPException) as e:
        _run(routes_docs.reset_doc("gibt-es-nicht", {}))
    assert e.value.status_code == 404


def test_reset_known_slug_still_200(temp_db):
    _gen()
    assert _run(routes_docs.reset_doc("ueberblick", {}))["page"]["slug"] == "ueberblick"


def test_versions_unknown_slug_404(temp_db):
    with pytest.raises(HTTPException) as e:
        _run(routes_docs.list_doc_versions("gibt-es-nicht", {}))
    assert e.value.status_code == 404


def test_versions_known_slug_without_versions_empty(temp_db):
    db.upsert_doc_page("ueberblick", "x", "T", "", "", 1)
    assert _run(routes_docs.list_doc_versions("ueberblick", {})) == {"versions": []}


def test_get_and_manual_unknown_slug_404(temp_db):
    with pytest.raises(HTTPException) as e:
        _run(routes_docs.get_doc("nope", {}))
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        _run(routes_docs.edit_doc_manual("nope", {"manualMd": "x"}, {}))
    assert e.value.status_code == 404


def test_edit_doc_body_requires_bodymd():
    with pytest.raises(ValidationError):
        routes_docs.DocBodyBody()
    with pytest.raises(ValidationError):
        routes_docs.DocBodyBody(bodyMd=None)


def test_edit_doc_empty_body_allowed(temp_db):
    _gen()
    page = _run(routes_docs.edit_doc("notfall", routes_docs.DocBodyBody(bodyMd=""), {}))["page"]
    assert page["generated"] == 0 and page["bodyMd"] == ""


def test_edit_doc_unknown_slug_404(temp_db):
    with pytest.raises(HTTPException) as e:
        _run(routes_docs.edit_doc("nope", routes_docs.DocBodyBody(bodyMd="x"), {}))
    assert e.value.status_code == 404
    assert db.get_doc_page("nope") is None


def test_generate_removes_stale_generated_page(temp_db):
    _gen()
    _stale()
    assert db.list_doc_versions("alt")
    other = len(db.list_doc_versions("ueberblick"))
    _gen()
    assert db.get_doc_page("alt") is None
    assert db.list_doc_versions("alt") == []
    assert len(db.list_doc_versions("ueberblick")) >= other


def test_generate_keeps_stale_page_with_manual_notes(temp_db):
    _stale(manual="Notiz")
    _gen()
    assert db.get_doc_page("alt") is not None


def test_generate_removes_stale_page_whitespace_notes(temp_db):
    _stale(manual="   ")
    _gen()
    assert db.get_doc_page("alt") is None


def test_generate_keeps_stale_page_when_pinned(temp_db):
    _stale(generated=False)
    _gen()
    assert db.get_doc_page("alt") is not None


def test_generate_only_slug_does_not_clean(temp_db):
    _gen()
    _stale()
    _gen(only_slug="ueberblick")
    assert db.get_doc_page("alt") is not None


def test_generate_returns_only_written_slugs(temp_db):
    _stale()
    assert "alt" not in _gen()
