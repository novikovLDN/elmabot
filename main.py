"""Entry point: DB pool + bot + scheduler in a single process."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

import config
from aiogram.types import BotCommand

from app.handlers import get_routers
from app.services import platega, remnawave
from app.services.notifications import (
    expiry_cleanup_loop,
    offer_loop,
    reminder_loop,
)
from app.web import start_webhook_server
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
    dp = Dispatcher(storage=MemoryStorage())
    for router in get_routers():
        dp.include_router(router)

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Запустить ELMA"),
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

    # Background scheduler loops.
    tasks = [
        asyncio.create_task(reminder_loop(bot), name="reminder_loop"),
        asyncio.create_task(expiry_cleanup_loop(bot), name="expiry_cleanup_loop"),
        asyncio.create_task(offer_loop(bot), name="offer_loop"),
    ]

    # Webhook server for Platega payment callbacks (only when configured).
    webhook_runner = None
    if config.PAYMENTS_ENABLED:
        webhook_runner = await start_webhook_server(bot)
    else:
        logger.info("Platega not configured — payments disabled, no webhook server")

    logger.info("Bot starting (polling)…")
    try:
        await dp.start_polling(bot)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if webhook_runner is not None:
            await webhook_runner.cleanup()
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
