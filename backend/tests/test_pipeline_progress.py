import asyncio

import pytest

from app import db, pipeline


@pytest.mark.parametrize("creds", [True, False])
def test_progress_never_decreases(temp_db, monkeypatch, creds):
    async def fake_discover(settings, progress, extra_targets=None, subnets=None):
        return {"findings": [], "warnings": [], "gateway": "", "dnsServers": [], "hostIp": "",
                "routedTargets": [], "counts": {}}

    async def fake_probe(log):
        return 0, [], {}, []

    monkeypatch.setattr(pipeline.discovery, "discover", fake_discover)
    monkeypatch.setattr(pipeline, "_probe_with_credentials", fake_probe)
    monkeypatch.setattr(pipeline.oui, "is_downloaded", lambda: True)
    db.update_settings({"scanUseCredentials": creds, "scanUseLlm": False})
    seen: list[int] = []
    orig = db.update_scan

    def rec(scan_id, **kw):
        if kw.get("progress") is not None:
            seen.append(kw["progress"])
        return orig(scan_id, **kw)

    monkeypatch.setattr(db, "update_scan", rec)
    asyncio.run(pipeline.run_full_scan(temp_db.create_scan("test")))
    assert seen == sorted(seen)
