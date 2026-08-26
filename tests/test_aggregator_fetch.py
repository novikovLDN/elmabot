"""fetch() self-healing UA negotiation: it must skip UAs the panel answers with
a JSON template and settle on the one that yields a base64 uri-list, remembering
it so the steady state is a single upstream request."""
import base64

import pytest

from app.services import aggregator as agg
from conftest import b64_uris


class _FakeResp:
    def __init__(self, body):
        self.content, self.status_code, self.headers = body, 200, {}

    def raise_for_status(self):
        pass


class _FakePanel:
    """Answers a set of UAs with base64 and everything else with JSON."""
    is_closed = False

    def __init__(self, base64_uas):
        self.base64_uas = set(base64_uas)
        self.calls = []

    async def get(self, url, headers=None):
        ua = headers["User-Agent"]
        self.calls.append(ua)
        if ua in self.base64_uas:
            return _FakeResp(b64_uris("S1", "S2", "S3"))
        return _FakeResp(b'[{"remarks":"Auto | Fast"}]')  # JSON template


async def test_fetch_picks_the_base64_ua(monkeypatch):
    # Only v2rayNG yields base64 here (whatever the configured first UA is).
    panel = _FakePanel(base64_uas={"v2rayNG/1.9.5"})
    monkeypatch.setattr(agg, "_get_client", lambda: panel)
    monkeypatch.setattr(
        agg.config, "SUBSCRIPTION_UPSTREAM_UAS",
        ["v2rayTun/2.0", "Shadowrocket/2.2.0", "v2rayNG/1.9.5"],
    )

    body, _ = await agg.fetch("http://panel/sub/x")
    assert agg._extract_uris(body) is not None and len(agg._extract_uris(body)) == 3
    assert agg._good_ua == "v2rayNG/1.9.5"
    # It tried the JSON UAs first, then found the base64 one.
    assert panel.calls == ["v2rayTun/2.0", "Shadowrocket/2.2.0", "v2rayNG/1.9.5"]


async def test_fetch_remembers_good_ua(monkeypatch):
    panel = _FakePanel(base64_uas={"Shadowrocket/2.2.0"})
    monkeypatch.setattr(agg, "_get_client", lambda: panel)
    monkeypatch.setattr(
        agg.config, "SUBSCRIPTION_UPSTREAM_UAS",
        ["v2rayTun/2.0", "Shadowrocket/2.2.0", "v2rayNG/1.9.5"],
    )

    await agg.fetch("http://panel/sub/x")   # discovers Shadowrocket
    panel.calls.clear()
    await agg.fetch("http://panel/sub/x")   # second fetch tries good UA first
    assert panel.calls == ["Shadowrocket/2.2.0"], "steady state is a single request"


async def test_fetch_returns_last_body_when_no_ua_works(monkeypatch):
    panel = _FakePanel(base64_uas=set())  # panel returns JSON to everything
    monkeypatch.setattr(agg, "_get_client", lambda: panel)
    monkeypatch.setattr(
        agg.config, "SUBSCRIPTION_UPSTREAM_UAS", ["a", "b", "c"],
    )
    body, _ = await agg.fetch("http://panel/sub/x")
    # Non-uri-list body is returned so combine() rejects it (caller → stale/503),
    # and every UA was attempted.
    assert agg._extract_uris(body) is None
    assert panel.calls == ["a", "b", "c"] and agg._good_ua is None
