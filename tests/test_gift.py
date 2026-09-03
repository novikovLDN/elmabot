"""Gift purchase: the webhook routes a gf_ payment to the gift branch (issue
code + send the buyer a link), settles the payment, and never activates the
buyer's own subscription."""
import pytest

from app.services import billing
from app.tariffs import get_tariff


class FakeBot:
    class _Me:
        username = "elma_bot"

    async def me(self):
        return self._Me()


@pytest.fixture
def spy(monkeypatch):
    calls = {"gift": [], "purchase": [], "traffic": [], "paid": [], "created": [], "sent": []}

    async def fake_complete_gift(bot, buyer, tariff, *, invoice_id=None, amount_paid=0):
        calls["gift"].append((buyer, tariff.code, invoice_id, amount_paid))
        return "https://t.me/x?start=gift_abc"

    async def fake_complete_purchase(*a, **k):
        calls["purchase"].append((a, k))

    async def fake_complete_traffic(*a, **k):
        calls["traffic"].append((a, k))

    async def fake_delete_screen(bot, payment):
        pass

    async def fake_notify(bot, tg):
        pass

    monkeypatch.setattr(billing, "notify_purchase_activated", fake_notify)
    monkeypatch.setattr(billing, "complete_gift_purchase", fake_complete_gift)
    monkeypatch.setattr(billing, "complete_purchase", fake_complete_purchase)
    monkeypatch.setattr(billing, "complete_traffic_purchase", fake_complete_traffic)
    monkeypatch.setattr(billing, "_delete_confirm_screen", fake_delete_screen)
    # neutralise the trailing revenue-milestone push (imports push_service)
    import app.services.push_service as push
    async def noop():
        return None
    monkeypatch.setattr(push, "check_revenue_milestones", noop)
    return calls


def _payment(code):
    return {
        "tariff_code": code, "invoice_id": "inv1", "telegram_id": 777,
        "amount_kopecks": 49900, "provider": "platega", "confirm_message_id": 5,
    }


async def test_gift_payment_routes_to_gift_branch(spy):
    await billing.finalize_confirmed_payment(FakeBot(), _payment("gf_3m"))
    assert spy["gift"] == [(777, "3m", "inv1", 49900)], "gift code issued for the buyer"
    assert spy["purchase"] == [], "buyer's own subscription must NOT be activated"


async def test_normal_payment_still_activates_subscription(spy):
    await billing.finalize_confirmed_payment(FakeBot(), _payment("3m"))
    assert spy["gift"] == [] and len(spy["purchase"]) == 1


async def test_complete_gift_purchase_settles_and_sends(monkeypatch):
    created, paid, sent = [], [], []

    async def fake_create_gift(code, tariff_code, buyer):
        created.append((code, tariff_code, buyer))

    async def fake_mark_paid(buyer, invoice_id, amount):
        paid.append((buyer, invoice_id, amount))

    async def fake_send(bot, uid, text, **k):
        sent.append(text)

    monkeypatch.setattr(billing, "create_gift", fake_create_gift)
    monkeypatch.setattr(billing, "mark_payment_paid", fake_mark_paid)
    monkeypatch.setattr(billing, "safe_send", fake_send)

    tariff = get_tariff("6m")
    link = await billing.complete_gift_purchase(
        FakeBot(), 777, tariff, invoice_id="inv9", amount_paid=89900,
    )
    assert link.startswith("https://t.me/elma_bot?start=gift_")
    assert paid == [(777, "inv9", 89900)], "payment settled"
    assert len(created) == 1 and created[0][1] == "6m"
    assert len(sent) == 2, "confirmation + forwardable card"
    assert any("start=gift_" in s for s in sent), "card carries the activation link"
