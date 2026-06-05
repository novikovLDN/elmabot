"""Purchase completion — the single place a successful payment lands.

The actual payment provider is not wired yet (buttons only); when it is, the
provider's success handler just calls :func:`complete_purchase`. It extends the
subscription, journals the payment, clears any used discount, and — on the
buyer's *first* paid purchase — credits the referrer with bonus days.
"""
import logging
import secrets

import asyncpg
from aiogram import Bot

import config
from app.format import fmt_date
from app.tariffs import Tariff, get_tariff
from app.utils import safe_send
from database import (
    clear_offer,
    create_gift,
    credit_referral,
    get_subscription,
    get_user,
    has_paid_payment,
    mark_payment_paid,
    redeem_gift_record,
)

from . import subscription_service

logger = logging.getLogger(__name__)


async def complete_purchase(
    bot: Bot,
    user_id: int,
    tariff: Tariff,
    *,
    invoice_id: str,
    amount_paid: int,
) -> asyncpg.Record:
    """Provision the bought tariff and settle the side effects.

    Provisioning runs first; the payment is marked paid only after it succeeds
    (the caller refunds on exception, keeping "paid -> served OR refunded").
    """
    current = await get_subscription(user_id)
    first_purchase = not await has_paid_payment(user_id)

    new_expires = subscription_service.next_expiry(current, tariff.days)
    sub = await subscription_service.create_or_renew(
        user_id, new_expires, source="payment"
    )
    await mark_payment_paid(user_id, invoice_id, amount_paid)
    await clear_offer(user_id)

    if first_purchase:
        await _reward_referrer(bot, user_id)
    return sub


async def _reward_referrer(bot: Bot, buyer_id: int) -> None:
    """Grant the inviter bonus days when their friend buys for the first time."""
    referrer_id = await credit_referral(buyer_id)
    if not referrer_id:
        return
    try:
        ref_sub = await get_subscription(referrer_id)
        new_expires = subscription_service.next_expiry(
            ref_sub, config.REFERRAL_BONUS_DAYS
        )
        sub = await subscription_service.create_or_renew(
            referrer_id, new_expires, source="referral"
        )
        await safe_send(
            bot,
            referrer_id,
            "🎉 <b>Друг оформил подписку!</b>\n\n"
            f"+{config.REFERRAL_BONUS_DAYS} дней добавлены к твоей подписке 🤍\n\n"
            f"📅 Теперь активна до: {fmt_date(sub['expires_at'])}",
        )
    except Exception:  # noqa: BLE001 - never fail the buyer's purchase on this
        logger.exception("Failed to reward referrer %s", referrer_id)


async def notify_referrer_on_trial(bot: Bot, user_id: int) -> None:
    """Tell the inviter their friend joined (on the friend's trial activation)."""
    user = await get_user(user_id)
    referrer_id = user["referred_by"] if user else None
    if not referrer_id:
        return
    await safe_send(
        bot,
        referrer_id,
        "🫂 <b>Твой друг подключился к ELMA!</b>\n\n"
        "Как только он оформит подписку —\n"
        "ты получишь +7 дней 🎁",
    )


# --- Gifts (ready; gift creation is gated behind payment) -----------------

async def create_gift_code(buyer_id: int, tariff: Tariff) -> str:
    """Issue a one-time gift code (called once a gift payment succeeds)."""
    code = secrets.token_urlsafe(9)
    await create_gift(code, tariff.code, buyer_id)
    return code


async def redeem_gift(bot: Bot, user_id: int, code: str) -> Tariff | None:
    """Activate a gift for the recipient. Returns the tariff on success, or None
    if the code is unknown / already used. Notifies the gifter."""
    rec = await redeem_gift_record(code, user_id)
    if rec is None:
        return None
    tariff = get_tariff(rec["tariff_code"])
    if tariff is None:
        return None
    current = await get_subscription(user_id)
    new_expires = subscription_service.next_expiry(current, tariff.days)
    await subscription_service.create_or_renew(user_id, new_expires, source="gift")
    await safe_send(
        bot,
        rec["created_by"],
        "🎁 <b>Твой подарок активирован!</b>\n\n"
        "Получатель уже в сети —\nбез лагов и блокировок 🤍",
    )
    return tariff
