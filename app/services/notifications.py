"""Background scheduler loops: expiry reminders, cleanup and discount offers.

Each loop is a plain ``while True: sleep; work`` wrapped in try/except so one
failure never kills the cycle. No APScheduler/Celery — a single process covers
the whole lite build.

Discount offers (stored on the user row, applied on the buy screen):
- end of trial      -> −10% first-purchase offer (valid ~1 day)
- subscription ending (24h) -> −20% renewal offer (valid until expiry)
- 3 days after expiry      -> −20% reactivation offer
"""
import asyncio
import logging
from datetime import timedelta

from aiogram import Bot

from config import (
    DISCOUNT_REACTIVATION_PCT,
    DISCOUNT_SUB_END_PCT,
    DISCOUNT_TRIAL_END_PCT,
    EXPIRY_INTERVAL_SECONDS,
    REACTIVATION_AFTER_DAYS,
    REMINDER_INTERVAL_SECONDS,
)
from database import (
    due_reactivation_offers,
    due_reminders,
    due_trial_end_offers,
    expired_active,
    mark_expired,
    mark_react_offer_sent,
    mark_reminder_sent,
    mark_trial_offer_sent,
    set_offer,
    utcnow,
)

from . import subscription_service
from ..keyboards import buy_keyboard
from ..utils import safe_send

logger = logging.getLogger(__name__)


async def _send_reminders(
    bot: Bot, flag_column: str, headline: str, *, offer_pct: int = 0
) -> None:
    rows = await due_reminders(flag_column)
    for row in rows:
        uid = row["telegram_id"]
        extra = ""
        # The −20% "renewal" offer applies to paid subscriptions, not trials
        # (trials get their own −10% offer once they end).
        if offer_pct and row["source"] != "trial":
            # "−20% в день окончания": offer valid until the subscription expires.
            await set_offer(uid, "sub_end", offer_pct, row["expires_at"])
            extra = f"\n\n🎁 Только сегодня: <b>−{offer_pct}%</b> на продление."
        text = (
            f"⏳ <b>{headline}</b>\n\n"
            "Чтобы не остаться без ELMA VPN, продли доступ 👇" + extra
        )
        await safe_send(bot, uid, text, reply_markup=buy_keyboard())
        await mark_reminder_sent(uid, flag_column)
    if rows:
        logger.info("Sent %d '%s' reminders", len(rows), flag_column)


async def reminder_loop(bot: Bot) -> None:
    while True:
        try:
            await _send_reminders(
                bot,
                "reminder_24h_sent",
                "Подписка истекает через 24 часа",
                offer_pct=DISCOUNT_SUB_END_PCT,
            )
            await _send_reminders(
                bot, "reminder_3h_sent", "Подписка истекает через 3 часа"
            )
        except Exception:  # noqa: BLE001 - keep the loop alive
            logger.exception("reminder_loop iteration failed")
        await asyncio.sleep(REMINDER_INTERVAL_SECONDS)


async def expiry_cleanup_loop(bot: Bot) -> None:
    while True:
        try:
            rows = await expired_active()
            for row in rows:
                await subscription_service.deprovision(row["panel_uuid"])
                await mark_expired(row["telegram_id"])
                await safe_send(
                    bot,
                    row["telegram_id"],
                    "🚫 Доступ к ELMA VPN истёк. Продли его, чтобы вернуться 👇",
                    reply_markup=buy_keyboard(),
                )
            if rows:
                logger.info("Expired %d subscriptions", len(rows))
        except Exception:  # noqa: BLE001 - keep the loop alive
            logger.exception("expiry_cleanup_loop iteration failed")
        await asyncio.sleep(EXPIRY_INTERVAL_SECONDS)


async def _trial_end_offers(bot: Bot) -> None:
    rows = await due_trial_end_offers()
    for row in rows:
        uid = row["telegram_id"]
        await set_offer(uid, "trial_end", DISCOUNT_TRIAL_END_PCT, utcnow() + timedelta(days=1))
        await mark_trial_offer_sent(uid)
        await safe_send(
            bot,
            uid,
            "✨ <b>Как тебе ELMA?</b>\n\n"
            "Пробный период закончился. Сегодня дарим "
            f"<b>−{DISCOUNT_TRIAL_END_PCT}%</b> на первую подписку — "
            "оформи со скидкой 👇",
            reply_markup=buy_keyboard(),
        )
    if rows:
        logger.info("Sent %d trial-end offers", len(rows))


async def _reactivation_offers(bot: Bot) -> None:
    rows = await due_reactivation_offers(REACTIVATION_AFTER_DAYS)
    for row in rows:
        uid = row["telegram_id"]
        await set_offer(uid, "reactivation", DISCOUNT_REACTIVATION_PCT, utcnow() + timedelta(days=1))
        await mark_react_offer_sent(uid)
        await safe_send(
            bot,
            uid,
            "🤍 <b>Скучаем по тебе в ELMA</b>\n\n"
            f"Возвращайся со скидкой <b>−{DISCOUNT_REACTIVATION_PCT}%</b> "
            "на любой тариф 👇",
            reply_markup=buy_keyboard(),
        )
    if rows:
        logger.info("Sent %d reactivation offers", len(rows))


async def offer_loop(bot: Bot) -> None:
    while True:
        try:
            await _trial_end_offers(bot)
            await _reactivation_offers(bot)
        except Exception:  # noqa: BLE001 - keep the loop alive
            logger.exception("offer_loop iteration failed")
        await asyncio.sleep(EXPIRY_INTERVAL_SECONDS)
