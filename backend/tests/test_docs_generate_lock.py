import asyncio

import pytest
from fastapi.testclient import TestClient

from app import auth, db, docs, main


@pytest.fixture()
def tracked(temp_db, monkeypatch):
    """Real generate() with an awaiting fake LLM intro; records the peak concurrency."""
    db.create_system({"name": "Router", "kind": "router", "discoveryKey": "k:r", "hostname": "r"})
    state = {"active": 0, "peak": 0, "calls": 0, "fail": False}

    async def fake_intro(topic, systems, settings):
        state["calls"] += 1
        state["active"] += 1
        state["peak"] = max(state["peak"], state["active"])
        try:
            await asyncio.sleep(0.01)
            if state["fail"]:
                raise RuntimeError("boom")
            return "Intro"
        finally:
            state["active"] -= 1

    monkeypatch.setattr(docs, "_write_intro", fake_intro)
    monkeypatch.setattr(docs, "_generate_lock", asyncio.Lock())
    return state


def test_generate_never_overlaps(tracked):
    async def run():
        return await asyncio.gather(docs.generate({}), docs.generate({}))

    a, b = asyncio.run(run())
    assert tracked["peak"] == 1
    assert a == b
    for slug in a:
        # unchanged content on the second run must not create a duplicate version
        assert len(db.list_doc_versions(slug)) <= 1


def test_lock_released_after_exception(tracked):
    async def run():
        tracked["fail"] = True
        with pytest.raises(RuntimeError):
            await docs.generate({})
        assert not docs.is_generating()
        tracked["fail"] = False
        return await docs.generate({})

    assert asyncio.run(run())


def test_pipeline_waits_for_running_generation(tracked):
    order = []

    async def run():
        async def first():
            await docs.generate({})
            order.append("first")

        async def second():
            await asyncio.sleep(0.001)
            assert docs.is_generating()
            await docs.generate({})  # what pipeline.py does: waits instead of failing
            order.append("second")

        await asyncio.gather(first(), second())

    asyncio.run(run())
    assert order == ["first", "second"]


@pytest.fixture()
def client(temp_db):
    main.app.dependency_overrides[main.require_admin] = lambda: {"role": auth.ROLE_ADMIN, "username": "admin"}
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()


def test_generate_route_409_while_generating(client, monkeypatch):
    monkeypatch.setattr(docs, "is_generating", lambda: True)
    r = client.post("/api/docs/generate", json={})
    assert r.status_code == 409
    assert "gerade erzeugt" in r.json()["detail"]


def test_reset_route_409_and_page_untouched(client, monkeypatch):
    called = []
    monkeypatch.setattr(docs, "is_generating", lambda: True)
    monkeypatch.setattr(db, "reset_doc_page", lambda slug: called.append(slug))
    r = client.post("/api/docs/uebersicht/reset")
    assert r.status_code == 409
    assert called == []
