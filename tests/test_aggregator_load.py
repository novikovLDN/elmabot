"""Load / throughput characteristics of the aggregator.

These prove the aggregator withstands realistic and adversarial load:
  * a hot cache serves at very high throughput (the 99% real-traffic case),
  * singleflight collapses a thundering herd to a single upstream build,
  * a flood of unique tokens stays memory-bounded (no leak),
  * a realistic 95%-hit mix keeps a high hit ratio.

Upstream is faked (in-process), so numbers reflect the aggregator's own cost.
Thresholds are deliberately conservative so the suite doesn't flake on slow CI;
actual numbers print with ``-s``.
"""
import asyncio
import base64
import time

import pytest

from app.services import aggregator as agg


def _merged_body(n_servers: int = 40) -> bytes:
    lines = [f"vless://uuid-{i}@1.2.3.{i % 255}:443#Server-{i}" for i in range(n_servers)]
    return base64.b64encode("\n".join(lines).encode())


async def test_hot_cache_throughput():
    """Fresh-cache hits are near-free — the 99% real-traffic path."""
    body = _merged_body()

    async def builder():
        return body, {"h": "1"}

    await agg.serve("tok_hot", builder)  # prime the cache

    N = 20_000
    start = time.perf_counter()
    for _ in range(N):
        await agg.serve("tok_hot", builder)
    elapsed = time.perf_counter() - start
    rps = N / elapsed
    print(f"\n[hot cache] {rps:,.0f} rps ({elapsed / N * 1e6:.1f} µs/req)")
    assert agg._metrics["hits"] == N
    assert rps > 20_000, f"hot-cache throughput too low: {rps:,.0f} rps"


async def test_singleflight_herd():
    """A cold-start herd (many clients, one token, at once) → one upstream call."""
    builds = {"n": 0}

    async def slow_builder():
        builds["n"] += 1
        await asyncio.sleep(0.02)  # simulate a ~20ms panel round-trip
        return _merged_body(), {}

    CONCURRENCY = 500
    results = await asyncio.gather(
        *[agg.serve("tok_herd", slow_builder) for _ in range(CONCURRENCY)]
    )
    print(f"\n[herd] {CONCURRENCY} concurrent → {builds['n']} upstream build(s)")
    assert builds["n"] == 1, "singleflight must collapse the herd to one build"
    assert len(results) == CONCURRENCY and all(r[2] == "miss" for r in results)


async def test_unique_token_flood_is_bounded(monkeypatch):
    """A flood of unique (random) tokens must not grow the cache without bound."""
    monkeypatch.setattr(agg, "MAX_CACHE_ENTRIES", 1_000)
    body = _merged_body(10)

    async def builder():
        return body, {}

    N = 25_000
    start = time.perf_counter()
    for i in range(N):
        await agg.serve(f"flood_{i}", builder)
    elapsed = time.perf_counter() - start
    print(f"\n[flood] {N:,} unique tokens in {elapsed:.2f}s "
          f"({N / elapsed:,.0f} rps), cache pinned at {len(agg._cache)}")
    assert len(agg._cache) <= 1_000, "LRU must bound memory under a unique-token flood"


async def test_cold_miss_throughput():
    """Cold misses pay the merge+base64 cost; still comfortably fast per core."""
    prem, byp = _merged_body(25), _merged_body(15)

    async def builder():
        # Mirror the real cost: decode+merge+dedup+base64 of two sources.
        merged = agg.combine([("premium", prem), ("bypass", byp)])
        return merged, {}

    N = 3_000
    start = time.perf_counter()
    for i in range(N):
        # unique token each time forces a real build (no fresh hit)
        await agg.serve(f"cold_{i}", builder)
    elapsed = time.perf_counter() - start
    rps = N / elapsed
    print(f"\n[cold miss] {rps:,.0f} rps ({elapsed / N * 1e6:.0f} µs/req, 40-server merge)")
    assert rps > 1_000, f"cold-miss throughput too low: {rps:,.0f} rps"


async def test_mixed_95pct_hit_ratio():
    """A realistic mix (mostly repeat hits on a small hot set) keeps hit_ratio high."""
    body = _merged_body()

    async def builder():
        return body, {}

    # 20 hot tokens, 2000 requests hitting them repeatedly + a few unique misses.
    hot = [f"hot_{i}" for i in range(20)]
    for t in hot:
        await agg.serve(t, builder)  # prime

    N = 2_000
    for i in range(N):
        token = hot[i % len(hot)] if i % 20 else f"rare_{i}"
        await agg.serve(token, builder)

    snap = agg.metrics_snapshot()
    print(f"\n[mixed] hit_ratio={snap['hit_ratio']:.3f} "
          f"(hits={snap['hits']}, misses={snap['misses']})")
    assert snap["hit_ratio"] > 0.9, f"hit ratio too low: {snap['hit_ratio']}"
