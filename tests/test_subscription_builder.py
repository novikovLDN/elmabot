"""End-to-end merge behaviour of app.web._build_subscription.

Key guarantee under test: when bypass GB is exhausted but the user still has an
active premium subscription, the MAIN (UNLIMITED) servers stay in the served
subscription — and the dead metered servers are dropped."""
import base64
from datetime import datetime, timezone

import pytest

from app import web
from app.services import aggregator as agg
from conftest import b64_uris


def _decode(body: bytes) -> str:
    return base64.b64decode(body).decode()


@pytest.fixture
def patch_sources(monkeypatch):
    """Wire premium + bypass sources; return a dict the test tweaks."""
    state = {
        "premium": {"status": "active", "subscription_url": "http://panel/prem",
                    "expires_at": datetime(2030, 1, 1, tzinfo=timezone.utc)},
        "bypass_row": {"subscription_url": "http://panel/bp"},
        "usage": {"used": 0, "limit": 10 * 1024**3, "remaining": 10 * 1024**3,
                  "subscription_url": "http://panel/bp", "live": True},
        "fetched": [],
    }

    async def fake_get_subscription(tg):
        return state["premium"]

    async def fake_get_bypass(tg):
        return state["bypass_row"]

    async def fake_get_usage(tg):
        return state["usage"]

    async def fake_fetch(url):
        state["fetched"].append(url)
        body = b64_uris("PREM-1", "PREM-2") if url == "http://panel/prem" else b64_uris("BYP-1")
        return body, {}

    monkeypatch.setattr(web, "get_subscription", fake_get_subscription)
    monkeypatch.setattr(web, "get_bypass", fake_get_bypass)
    monkeypatch.setattr(web.bypass_service, "get_usage", fake_get_usage)
    monkeypatch.setattr(agg, "fetch", fake_fetch)
    monkeypatch.setattr(web.config, "BYPASS_ENABLED", True)
    monkeypatch.setattr(web.config, "SUBSCRIPTION_WEBPAGE_URL", "https://elma.example/renew")
    return state


async def test_premium_and_bypass_both_served_when_traffic_left(patch_sources):
    body, headers = await web._build_subscription(request=None, tg_id=1)
    merged = _decode(body)
    assert "PREM-1" in merged and "PREM-2" in merged
    assert "BYP-1" in merged, "bypass servers shown while GB remain"
    assert "http://panel/prem" in patch_sources["fetched"]
    assert "http://panel/bp" in patch_sources["fetched"]


async def test_main_servers_survive_when_bypass_exhausted(patch_sources):
    # GB used up: remaining 0, panel entity LIMITED.
    patch_sources["usage"] = {
        "used": 10 * 1024**3, "limit": 10 * 1024**3, "remaining": 0,
        "subscription_url": "http://panel/bp", "live": True,
    }
    body, headers = await web._build_subscription(request=None, tg_id=1)
    merged = _decode(body)
    assert "PREM-1" in merged and "PREM-2" in merged, "UNLIMITED servers must remain"
    assert "BYP-1" not in merged, "exhausted metered servers are dropped"
    assert "http://panel/bp" not in patch_sources["fetched"], "bypass not even fetched when exhausted"
    # The traffic bar still reports full usage so the client prompts a top-up.
    assert "total=" in headers["Subscription-Userinfo"]
    assert "download=" in headers["Subscription-Userinfo"]


async def test_premium_survives_when_bypass_fetch_fails(patch_sources, monkeypatch):
    async def flaky_fetch(url):
        if url == "http://panel/bp":
            raise RuntimeError("bypass entity unreachable")
        return b64_uris("PREM-1", "PREM-2"), {}

    monkeypatch.setattr(agg, "fetch", flaky_fetch)
    body, _ = await web._build_subscription(request=None, tg_id=1)
    merged = _decode(body)
    assert "PREM-1" in merged and "PREM-2" in merged, "a failing bypass source must not sink premium"
