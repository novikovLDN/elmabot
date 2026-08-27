"""subscription_service.resolve_live_url: premium subscription URL is read live
from the panel and synced to the DB when it changes, mirroring how bypass
self-syncs — so a panel-side link change is picked up on the next request."""
import pytest

from app.services import subscription_service as svc


ACTIVE = {"status": "active", "subscription_url": "http://panel/OLD"}


async def test_syncs_when_panel_url_changed(monkeypatch):
    saved = {}

    async def fake_find(username):
        return {"id": 5, "subscriptionUrl": "http://panel/NEW"}

    async def fake_set_url(tg, url):
        saved["tg"], saved["url"] = tg, url

    monkeypatch.setattr(svc.remnawave, "find_user_by_username", fake_find)
    monkeypatch.setattr(svc, "set_subscription_url", fake_set_url)

    url = await svc.resolve_live_url(42, sub=ACTIVE)
    assert url == "http://panel/NEW", "returns the current panel URL"
    assert saved == {"tg": 42, "url": "http://panel/NEW"}, "DB synced to the new URL"


async def test_no_write_when_url_unchanged(monkeypatch):
    writes = {"n": 0}

    async def fake_find(username):
        return {"id": 5, "subscriptionUrl": "http://panel/OLD"}

    async def fake_set_url(tg, url):
        writes["n"] += 1

    monkeypatch.setattr(svc.remnawave, "find_user_by_username", fake_find)
    monkeypatch.setattr(svc, "set_subscription_url", fake_set_url)

    url = await svc.resolve_live_url(42, sub=ACTIVE)
    assert url == "http://panel/OLD" and writes["n"] == 0


async def test_falls_back_to_stored_on_panel_failure(monkeypatch):
    async def boom(username):
        raise RuntimeError("panel down")

    monkeypatch.setattr(svc.remnawave, "find_user_by_username", boom)
    url = await svc.resolve_live_url(42, sub=ACTIVE)
    assert url == "http://panel/OLD", "a panel read failure must not break the subscription"


async def test_none_when_no_active_premium(monkeypatch):
    # Explicit inactive row -> None, no panel/DB call.
    assert await svc.resolve_live_url(42, sub={"status": "expired", "subscription_url": "x"}) is None

    # sub omitted -> reads the row itself; a missing row -> None.
    async def no_sub(tg):
        return None

    monkeypatch.setattr(svc, "get_subscription", no_sub)
    assert await svc.resolve_live_url(42) is None
