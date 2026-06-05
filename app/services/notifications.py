"""Background scheduler loops: expiry reminders and expired-access cleanup.

Each loop is a plain ``while True: sleep; work`` wrapped in try/except so one
failure never kills the cycle. No APScheduler/Celery — a single process covers
the whole lite build.
"""
import asyncio
import logging

from aiogram import Bot

from config import (
    EXPIRY_INTERVAL_SECONDS,
    REMINDER_INTERVAL_SECONDS,
)
from database import (
    due_reminders,
    expired_active,
    mark_expired,
    mark_reminder_sent,
)

from . import access
from ..keyboards import buy_keyboard
from ..utils import safe_send

logger = logging.getLogger(__name__)


async def _send_reminders(bot: Bot, flag_column: str, headline: str) -> None:
    rows = await due_reminders(flag_column)
    for row in rows:
        text = (
            f"⏳ <b>{headline}</b>\n\n"
            "Чтобы не остаться без ELMA VPN, продли доступ 👇"
        )
        await safe_send(bot, row["telegram_id"], text, reply_markup=buy_keyboard())
        await mark_reminder_sent(row["telegram_id"], flag_column)
    if rows:
        logger.info("Sent %d '%s' reminders", len(rows), flag_column)


async def reminder_loop(bot: Bot) -> None:
    while True:
        try:
            await _send_reminders(
                bot, "reminder_24h_sent", "Подписка истекает через 24 часа"
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
                await access.deprovision(row["vpn_uuid"])
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
