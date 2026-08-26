"""Shared fixtures for the aggregator test suite.

The aggregator keeps process-global caches/metrics, so every test starts from a
clean slate. Nothing here touches the network or a DB — the unit under test is
pure in-memory logic (cache / singleflight / stale) exercised through fakes.
"""
import base64

import pytest

from app.services import aggregator as agg


@pytest.fixture(autouse=True)
def reset_aggregator():
    """Wipe the in-process cache/metrics before and after each test."""
    def _wipe():
        agg._cache.clear()
        agg._neg.clear()
        agg._inflight.clear()
        agg._good_ua = None
        for k in agg._metrics:
            agg._metrics[k] = 0
    _wipe()
    yield
    _wipe()


@pytest.fixture
def fast_ttl(monkeypatch):
    """Shrink the fresh window so expiry is testable without real sleeps."""
    monkeypatch.setattr(agg, "FRESH_TTL", 0.05)
    return 0.05


def b64_uris(*names: str) -> bytes:
    """A base64 vless URI list body (what the panel returns under our UA)."""
    lines = [f"vless://uuid-{i}@1.2.3.{i}:443#{n}" for i, n in enumerate(names, 1)]
    return base64.b64encode("\n".join(lines).encode())
