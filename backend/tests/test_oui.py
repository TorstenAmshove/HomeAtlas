"""IEEE OUI registry download and cache behavior."""
import asyncio

import httpx

from app import oui


def test_refresh_identifies_homeatlas_to_ieee(monkeypatch, tmp_path):
    registry = "".join(
        f"MA-L,{assignment:06X},Vendor {assignment},Address\n"
        for assignment in range(1000)
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200 if request.headers.get("user-agent") == "HomeAtlas/1.0 (+https://github.com/TorstenAmshove/HomeAtlas)" else 418,
            text=registry,
        )
    )

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(oui.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(oui, "_CACHE_PATH", tmp_path / "oui.json")
    monkeypatch.setattr(oui, "_loaded", None)

    ok, _ = asyncio.run(oui.refresh_from_ieee())

    assert ok
    assert oui.lookup("00:00:00:11:22:33") == "Vendor 0"


def test_download_backoff(tmp_path, monkeypatch):
    import asyncio

    from app import oui
    monkeypatch.setattr(oui, "_CACHE_PATH", tmp_path / "oui.json")
    assert oui.download_due()

    async def fail():
        return False, "offline"
    monkeypatch.setattr(oui, "_refresh_from_ieee", fail)
    asyncio.run(oui.refresh_from_ieee())
    stamp = float((tmp_path / "oui.attempt").read_text())
    assert not oui.download_due(now=stamp + 86399)
    assert oui.download_due(now=stamp + 86400)
    assert oui.download_due(now=stamp - 10)  # future timestamp

    async def ok():
        return True, "ok"
    monkeypatch.setattr(oui, "_refresh_from_ieee", ok)
    asyncio.run(oui.refresh_from_ieee())
    assert not (tmp_path / "oui.attempt").exists()

    (tmp_path / "oui.attempt").write_text("müll")
    assert oui.download_due()
