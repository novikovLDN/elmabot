"""Purchase completion — the single place a successful payment lands.

The actual payment provider is not wired yet (buttons only); when it is, the
provider's success handler just calls :func:`complete_purchase`. It extends the
subscription, journals the payment, clears any used discount, and — on the
buyer's *first* paid purchase — credits the referrer with bonus days.
"""
import logging

import asyncpg
from aiogram import Bot

import config
from app.tariffs import Tariff
from app.utils import safe_send
from database import (
    clear_offer,
    credit_referral,
    get_subscription,
    has_paid_payment,
    mark_payment_paid,
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
        await subscription_service.create_or_renew(
            referrer_id, new_expires, source="referral"
        )
        await safe_send(
            bot,
            referrer_id,
            f"🎉 Твой друг оформил подписку ELMA — тебе начислено "
            f"<b>+{config.REFERRAL_BONUS_DAYS} дней</b>!",
        )
    except Exception:  # noqa: BLE001 - never fail the buyer's purchase on this
        logger.exception("Failed to reward referrer %s", referrer_id)
