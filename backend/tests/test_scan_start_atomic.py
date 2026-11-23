import asyncio
import threading

import pytest
from fastapi.testclient import TestClient

from app import auth, db, main, pipeline


def test_second_create_if_idle_returns_none(temp_db):
    first = db.create_scan_if_idle("a")
    assert first is not None
    assert db.create_scan_if_idle("b") is None
    db.finish_scan(first, "done", {})
    assert db.create_scan_if_idle("c") is not None


def test_parallel_starts_create_one_scan(temp_db):
    results: list = []
    barrier = threading.Barrier(8)

    def go():
        barrier.wait()
        results.append(db.create_scan_if_idle("x"))

    threads = [threading.Thread(target=go) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len([r for r in results if r is not None]) == 1
    assert len(db.list_scans()) == 1


@pytest.fixture()
def client(temp_db, monkeypatch):
    main.app.dependency_overrides[main.require_admin] = lambda: {"role": auth.ROLE_ADMIN, "username": "admin"}

    async def fake_scan(scan_id):
        return None

    monkeypatch.setattr(pipeline, "run_full_scan", fake_scan)
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()


def test_route_second_start_409(client):
    assert client.post("/api/scans").status_code == 200
    second = client.post("/api/scans")
    assert second.status_code == 409
    assert len(db.list_scans()) == 1


def test_scheduler_skips_when_scan_running(temp_db, monkeypatch):
    monkeypatch.setattr(db, "get_settings", lambda: {"scanAutoEnabled": True})
    started = []

    async def fake_scan(scan_id):
        started.append(scan_id)

    monkeypatch.setattr(pipeline, "run_full_scan", fake_scan)
    # the cheap pre-check passes, but another start wins before the insert
    monkeypatch.setattr(db, "running_scan", lambda: None)
    assert db.create_scan_if_idle("manuell") is not None
    asyncio.run(pipeline.Scheduler()._maybe_run())
    assert started == []
    assert len(db.list_scans()) == 1
