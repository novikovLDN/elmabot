"""Unit tests for the subscription aggregator: token validation, the body cache,
singleflight de-dup, the stale-copy fallback, negative caching, LRU bounds,
metrics, cache invalidation, the diagnostic probe, and the merge helpers."""
import asyncio
import base64
import time

import pytest

from app.services import aggregator as agg
from conftest import b64_uris


# --- token validation ------------------------------------------------------

@pytest.mark.parametrize("token", ["abcd", "A_b-9" * 5, "x" * 128, "tok_ABC123"])
def test_valid_token_accepts(token):
    assert agg.valid_token(token) is True


@pytest.mark.parametrize("token", ["", "abc", "x" * 129, "bad/slash", "space bar", "emoji😀x"])
def test_valid_token_rejects(token):
    assert agg.valid_token(token) is False


# --- basic cache: miss then fresh hit --------------------------------------

async def test_miss_then_fresh_hit():
    calls = {"n": 0}

    async def builder():
        calls["n"] += 1
        return b"BODY", {"h": "1"}

    body, headers, state = await agg.serve("tok_basic", builder)
    assert (body, headers, state) == (b"BODY", {"h": "1"}, "miss")

    body, headers, state = await agg.serve("tok_basic", builder)
    assert state == "hit" and body == b"BODY"
    assert calls["n"] == 1  # second call served from cache, no rebuild


async def test_invalid_token_raises_not_found():
    async def builder():
        raise AssertionError("builder must not run for an invalid token")

    with pytest.raises(agg.SubscriptionNotFound):
        await agg.serve("!!bad", builder)
    assert agg._metrics["not_found"] == 1


# --- singleflight ----------------------------------------------------------

async def test_singleflight_collapses_concurrent_builds():
    calls = {"n": 0}

    async def slow_builder():
        calls["n"] += 1
        await asyncio.sleep(0.05)
        return b"ONE", {}

    results = await asyncio.gather(*[agg.serve("tok_sf", slow_builder) for _ in range(50)])
    assert calls["n"] == 1, "50 concurrent callers must trigger exactly one build"
    assert all(r[0] == b"ONE" for r in results)
    assert agg._metrics["singleflight_wait"] == 49


async def test_followers_get_leader_exception():
    """A concurrent follower sees the leader's NotFound, not a hang."""
    async def nf_builder():
        await asyncio.sleep(0.02)
        raise agg.SubscriptionNotFound

    results = await asyncio.gather(
        *[agg.serve("tok_nf", nf_builder) for _ in range(10)],
        return_exceptions=True,
    )
    assert all(isinstance(r, agg.SubscriptionNotFound) for r in results)


# --- freshness: refetch after the window -----------------------------------

async def test_refetch_after_fresh_window(fast_ttl):
    calls = {"n": 0}

    async def builder():
        calls["n"] += 1
        return f"v{calls['n']}".encode(), {}

    b1, _, s1 = await agg.serve("tok_fresh", builder)
    assert (b1, s1) == (b"v1", "miss")
    time.sleep(fast_ttl + 0.02)
    b2, _, s2 = await agg.serve("tok_fresh", builder)
    assert (b2, s2) == (b"v2", "miss"), "past the window a refresh must rebuild live"
    assert calls["n"] == 2


# --- stale fallback --------------------------------------------------------

async def test_stale_served_when_upstream_fails(fast_ttl):
    state = {"fail": False}

    async def builder():
        if state["fail"]:
            raise RuntimeError("panel down")
        return b"GOOD", {"h": "v"}

    await agg.serve("tok_stale", builder)          # cache a good copy
    time.sleep(fast_ttl + 0.02)                     # let it go non-fresh
    state["fail"] = True
    body, headers, cache_state = await agg.serve("tok_stale", builder)
    assert cache_state == "stale" and body == b"GOOD" and headers == {"h": "v"}
    assert agg._metrics["stale"] == 1
    assert agg._metrics["upstream_fail"] == 1


async def test_no_stale_and_failure_raises_unavailable():
    async def boom():
        raise RuntimeError("panel down")

    with pytest.raises(agg.SubscriptionUnavailable):
        await agg.serve("tok_503", boom)


# --- negative cache --------------------------------------------------------

async def test_not_found_is_negatively_cached():
    calls = {"n": 0}

    async def nf():
        calls["n"] += 1
        raise agg.SubscriptionNotFound

    for _ in range(5):
        with pytest.raises(agg.SubscriptionNotFound):
            await agg.serve("tok_missing", nf)
    assert calls["n"] == 1, "unknown token must be remembered, not re-resolved each time"


async def test_invalidate_clears_negative_cache():
    async def nf():
        raise agg.SubscriptionNotFound

    with pytest.raises(agg.SubscriptionNotFound):
        await agg.serve("tok_reappear", nf)
    assert agg._neg_get("tok_reappear") is True
    agg.clear_cache("tok_reappear")
    assert agg._neg_get("tok_reappear") is False


# --- LRU bounds ------------------------------------------------------------

async def test_body_cache_is_lru_bounded(monkeypatch):
    monkeypatch.setattr(agg, "MAX_CACHE_ENTRIES", 100)

    async def builder():
        return b"x", {}

    for i in range(250):
        await agg.serve(f"tok_lru_{i:04d}", builder)
    assert len(agg._cache) <= 100, "cache must not grow unbounded under unique tokens"
    # The oldest entries are evicted; the most recent survive.
    assert "tok_lru_0249" in agg._cache
    assert "tok_lru_0000" not in agg._cache


# --- invalidation ----------------------------------------------------------

async def test_invalidate_drops_body(fast_ttl, monkeypatch):
    calls = {"n": 0}

    async def builder():
        calls["n"] += 1
        return f"b{calls['n']}".encode(), {}

    await agg.serve("tok_inv", builder)  # fresh in cache

    # invalidate(tg) resolves the token via the DB and clears it.
    import database
    async def fake_get_user(tg):
        return {"sub_token": "tok_inv"}
    monkeypatch.setattr(database, "get_user", fake_get_user)

    await agg.invalidate(777)
    assert "tok_inv" not in agg._cache
    # next fetch rebuilds live rather than serving the old (now-cleared) body
    body, _, state = await agg.serve("tok_inv", builder)
    assert state == "miss" and body == b"b2"


# --- per-user link reissue -------------------------------------------------

async def test_rotate_link_isolates_user_and_clears_old_cache(monkeypatch):
    import database

    tokens = {6001: "old_token_A", 6002: "token_B_other"}

    async def fake_get_user(tg):
        return {"sub_token": tokens[tg]}

    async def fake_reissue(tg):
        tokens[tg] = f"new_token_{tg}"
        return tokens[tg]

    monkeypatch.setattr(database, "get_user", fake_get_user)
    monkeypatch.setattr(database, "reissue_sub_token", fake_reissue)

    async def builder():
        return b"BODY", {}

    await agg.serve("old_token_A", builder)      # user 6001 cached
    await agg.serve("token_B_other", builder)    # user 6002 cached
    assert "old_token_A" in agg._cache and "token_B_other" in agg._cache

    new = await agg.rotate_link(6001)
    assert new == "new_token_6001", "a fresh unique token is issued"
    assert "old_token_A" not in agg._cache, "the old link's cache is dropped (dies at once)"
    assert new not in agg._cache, "the new link rebuilds live on first fetch"
    assert "token_B_other" in agg._cache, "no other user's link is affected"


# --- metrics ---------------------------------------------------------------

async def test_metrics_snapshot_hit_ratio():
    async def builder():
        return b"B", {}

    await agg.serve("tok_m", builder)  # miss
    await agg.serve("tok_m", builder)  # hit
    await agg.serve("tok_m", builder)  # hit
    snap = agg.metrics_snapshot()
    assert snap["hits"] == 2 and snap["misses"] == 1
    assert snap["hit_ratio"] == pytest.approx(2 / 3, abs=1e-4)
    assert snap["cache_entries"] == 1 and snap["inflight"] == 0


# --- probe (format diagnostic) ---------------------------------------------

async def test_probe_detects_base64_vs_json(monkeypatch):
    class FakeResp:
        def __init__(self, body, ct):
            self.content, self.status_code = body, 200
            self.headers = {"content-type": ct}

    class FakeClient:
        is_closed = False

        async def get(self, url, headers=None):
            if "Happ" in headers.get("User-Agent", ""):
                return FakeResp(b'{"outbounds":[]}', "application/json")
            return FakeResp(b64_uris("S1", "S2"), "text/plain")

    monkeypatch.setattr(agg, "_get_client", lambda: FakeClient())

    good = await agg.probe("http://panel/sub/x")
    assert good["is_uri_list"] and good["servers"] == 2 and good["content_type"] == "text/plain"

    bad = await agg.probe("http://panel/sub/x", "Happ/2.0")
    assert not bad["is_uri_list"] and bad["servers"] == 0 and bad["content_type"] == "application/json"


# --- merge helpers ---------------------------------------------------------

def test_extract_uris_from_base64_and_plaintext():
    assert agg._extract_uris(b64_uris("A", "B")) == [
        "vless://uuid-1@1.2.3.1:443#A",
        "vless://uuid-2@1.2.3.2:443#B",
    ]
    plain = b"vless://a@h:443#X\nvless://b@h:443#Y"
    assert agg._extract_uris(plain) == ["vless://a@h:443#X", "vless://b@h:443#Y"]
    # A structured (JSON/Clash) body is not a URI list.
    assert agg._extract_uris(b'{"outbounds": []}') is None


def test_combine_keeps_all_servers_with_notes():
    prem = b64_uris("P1", "P2")
    byp = b64_uris("B1")
    merged = agg.combine([("premium", prem), ("bypass", byp)])
    decoded = base64.b64decode(merged).decode()
    lines = decoded.splitlines()
    assert len(lines) == 3, "every server from every source is kept"
    assert "premium" in decoded and "bypass" in decoded  # note appended as subtitle


def test_combine_returns_none_when_nothing_mergeable():
    assert agg.combine([("premium", b'{"json": true}')]) is None


def test_build_announce_variants():
    _MB = 1024 ** 3
    a = agg.build_announce(has_premium=True, has_bypass=True, remaining_bytes=5 * _MB)
    assert "UNLIMITED" in a and "LTE" in a and "5.00 ГБ" in a
    b = agg.build_announce(has_premium=True, has_bypass=False, remaining_bytes=None)
    assert "UNLIMITED" in b and "LTE" not in b
