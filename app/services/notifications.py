"""Background scheduler loops: expiry reminders, cleanup and discount offers.

Each loop is a plain ``while True: sleep; work`` wrapped in try/except so one
failure never kills the cycle. No APScheduler/Celery — a single process covers
the whole lite build.

Reminder timeline (approved copy):
- 3 days before expiry  -> gentle "продли" reminder
- on the day of expiry  -> "сегодня" reminder + −20% renewal offer
- after expiry          -> "доступ приостановлен" + −20% restore offer
- end of trial          -> −10% first-purchase offer (valid ~1 day)
- 3 days after expiry    -> −20% reactivation offer
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
from ..keyboards import offer_keyboard
from ..utils import safe_send

logger = logging.getLogger(__name__)


async def _send_3day(bot: Bot) -> None:
    rows = await due_reminders("reminder_24h_sent")  # column repurposed: 3 days
    for row in rows:
        text = (
            "⚡️ <b>Подписка заканчивается через 2 дня</b>\n\n"
            "Продли сейчас — срок добавится к текущему.\n"
            "Не теряй доступ 💎"
        )
        await safe_send(
            bot, row["telegram_id"], text,
            reply_markup=offer_keyboard("🔄 Продлить подписку"),
        )
        await mark_reminder_sent(row["telegram_id"], "reminder_24h_sent")
    if rows:
        logger.info("Sent %d 3-day reminders", len(rows))


async def _send_day_of(bot: Bot) -> None:
    rows = await due_reminders("reminder_3h_sent")  # column repurposed: day-of
    for row in rows:
        uid = row["telegram_id"]
        # −20% renewal offer for paid subscriptions (trials get their own −10%).
        if row["source"] != "trial":
            await set_offer(uid, "sub_end", DISCOUNT_SUB_END_PCT, utcnow() + timedelta(days=1))
        text = (
            "⏳ <b>Подписка заканчивается сегодня</b>\n\n"
            "Не теряй доступ — продли за минуту."
        )
        await safe_send(bot, uid, text, reply_markup=offer_keyboard("🔄 Продлить подписку"))
        await mark_reminder_sent(uid, "reminder_3h_sent")
    if rows:
        logger.info("Sent %d day-of reminders", len(rows))


async def reminder_loop(bot: Bot) -> None:
    while True:
        try:
            await _send_3day(bot)
            await _send_day_of(bot)
        except Exception:  # noqa: BLE001 - keep the loop alive
            logger.exception("reminder_loop iteration failed")
        await asyncio.sleep(REMINDER_INTERVAL_SECONDS)


async def expiry_cleanup_loop(bot: Bot) -> None:
    while True:
        try:
            rows = await expired_active()
            for row in rows:
                uid = row["telegram_id"]
                await subscription_service.deprovision(row["panel_uuid"])
                await mark_expired(uid)
                # Trials are converted by the dedicated −10% trial-end offer
                # (offer_loop); they must NOT get the paid "Доступ приостановлен"
                # / −20% restore message — that's only for ended PAID subs.
                if row["source"] == "trial":
                    continue
                # −20% restore offer right at expiry.
                await set_offer(uid, "sub_end", DISCOUNT_SUB_END_PCT, utcnow() + timedelta(days=1))
                await safe_send(
                    bot,
                    uid,
                    "😔 <b>Доступ приостановлен</b>\n\n"
                    "Подписка закончилась.\n"
                    "Но всё легко исправить — один клик\n"
                    "и ты снова в сети 🤍",
                    reply_markup=offer_keyboard("🔑 Восстановить доступ −20%"),
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
            "☁️ <b>Твои 2 дня подходят к концу</b>\n\n"
            "Успел почувствовать разницу? 🤍\n\n"
            "Продолжи без перерыва —\n"
            f"специально для тебя скидка {DISCOUNT_TRIAL_END_PCT}% 🎁\n\n"
            "Действует только сегодня.",
            reply_markup=offer_keyboard(f"🔑 Купить со скидкой −{DISCOUNT_TRIAL_END_PCT}%"),
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
            "☁️ <b>Соскучился по свободному интернету?</b>\n\n"
            "Ты был с нами — и мы помним 🤍\n\n"
            f"Возвращайся со скидкой {DISCOUNT_REACTIVATION_PCT}% —\n"
            "это только для тебя.",
            reply_markup=offer_keyboard(f"🔑 Купить со скидкой −{DISCOUNT_REACTIVATION_PCT}%"),
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
