"""Entry point: DB pool + bot + scheduler in a single process."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

import config
from aiogram.types import BotCommand

from app.brand import install_brand
from app.handlers import get_routers
from app.services import platega, remnawave
from app.services.notifications import (
    expiry_cleanup_loop,
    offer_loop,
    payment_reconcile_loop,
    reminder_loop,
    traffic_monitor_loop,
)
from app.web import start_server
from database import close_db, init_db


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def main() -> None:
    setup_logging()
    logger = logging.getLogger("main")

    await init_db()

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    install_brand(bot)  # rewrites the brand token in outgoing messages if rebranded
    dp = Dispatcher(storage=MemoryStorage())
    for router in get_routers():
        dp.include_router(router)

    await bot.set_my_commands(
        [
            BotCommand(command="start", description=f"Запустить {config.BRAND_NAME}"),
            BotCommand(command="menu", description="Главное меню"),
            BotCommand(command="connect", description="Подключиться"),
            BotCommand(command="buy", description="Купить / продлить подписку"),
            BotCommand(command="account", description="Личный кабинет"),
            BotCommand(command="invite", description="Реферальная программа"),
            BotCommand(command="gift", description="Подарить подписку"),
            BotCommand(command="help", description="Помощь"),
            BotCommand(command="about", description="О сервисе"),
        ]
    )

    # Probe the Incy crypt-link sidecar once (logs INCY_SELFTEST_OK/FAIL). A
    # failure is non-fatal — Incy degrades to legacy links, Happ is unaffected.
    from app.services import incy_crypto

    await incy_crypto.selftest()

    # Background scheduler loops.
    tasks = [
        asyncio.create_task(reminder_loop(bot), name="reminder_loop"),
        asyncio.create_task(expiry_cleanup_loop(bot), name="expiry_cleanup_loop"),
        asyncio.create_task(offer_loop(bot), name="offer_loop"),
        asyncio.create_task(traffic_monitor_loop(bot), name="traffic_monitor_loop"),
        asyncio.create_task(payment_reconcile_loop(bot), name="payment_reconcile_loop"),
    ]

    runner = None
    try:
        if config.USE_WEBHOOK:
            # Full webhook mode: Telegram + Platega share one aiohttp server/port.
            webhook_url = config.WEBHOOK_BASE_URL + config.WEBHOOK_PATH
            await bot.set_webhook(
                url=webhook_url,
                secret_token=config.TELEGRAM_WEBHOOK_SECRET,
                allowed_updates=dp.resolve_used_update_types(),
                drop_pending_updates=True,
            )
            runner = await start_server(bot, dp)
            logger.info("Bot started (webhook) at %s", webhook_url)
            await asyncio.Event().wait()  # serve until cancelled
        else:
            # Polling mode (local dev): drop any stale webhook first.
            await bot.delete_webhook(drop_pending_updates=True)
            if config.PAYMENTS_ENABLED or config.DASHBOARD_ENABLED:
                runner = await start_server(bot)  # Platega callback and/or dashboard
            else:
                logger.info("Polling mode, payments off — no HTTP server")
            logger.info("Bot starting (polling)…")
            await dp.start_polling(bot)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if runner is not None:
            await runner.cleanup()
        await platega.close()
        await remnawave.close()
        await bot.session.close()
        await close_db()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
