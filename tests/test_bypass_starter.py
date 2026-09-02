"""ensure_starter_bypass: every subscriber gets a bypass profile once — created
when absent, never re-granted, and a no-op when bypass is disabled."""
import pytest

from app.services import bypass_service as bp


@pytest.fixture
def wire(monkeypatch):
    calls = {"provisioned": []}

    async def fake_provision(tg, extra_bytes):
        calls["provisioned"].append((tg, extra_bytes))
        return extra_bytes

    monkeypatch.setattr(bp, "provision_traffic", fake_provision)
    monkeypatch.setattr(bp.config, "BYPASS_ENABLED", True)
    monkeypatch.setattr(bp.config, "BYPASS_TRIAL_BONUS_MB", 500)
    return calls


async def test_creates_profile_when_absent(wire, monkeypatch):
    async def no_bypass(tg):
        return None

    monkeypatch.setattr(bp, "get_bypass", no_bypass)

    created = await bp.ensure_starter_bypass(42)
    assert created is True
    assert wire["provisioned"] == [(42, 500 * 1024 * 1024)], "starter allowance in bytes"


async def test_no_restack_when_already_has_bypass(wire, monkeypatch):
    async def has_bypass(tg):
        return {"panel_uuid": "123"}

    monkeypatch.setattr(bp, "get_bypass", has_bypass)

    created = await bp.ensure_starter_bypass(42)
    assert created is False and wire["provisioned"] == [], "renewals must not re-grant"


async def test_noop_when_bypass_disabled(wire, monkeypatch):
    monkeypatch.setattr(bp.config, "BYPASS_ENABLED", False)
    assert await bp.ensure_starter_bypass(42) is False
    assert wire["provisioned"] == []


async def test_noop_when_allowance_zero(wire, monkeypatch):
    monkeypatch.setattr(bp.config, "BYPASS_TRIAL_BONUS_MB", 0)
    assert await bp.ensure_starter_bypass(42) is False
    assert wire["provisioned"] == []


def test_backwards_compatible_alias():
    assert bp.provision_trial_bonus is bp.ensure_starter_bypass
