"""Entry point: DB pool + bot + scheduler in a single process."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

import config
from app.handlers import get_routers
from app.services import vpn
from app.services.notifications import expiry_cleanup_loop, reminder_loop
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

    # Background scheduler loops.
    tasks = [
        asyncio.create_task(reminder_loop(bot), name="reminder_loop"),
        asyncio.create_task(expiry_cleanup_loop(bot), name="expiry_cleanup_loop"),
    ]

    logger.info("Bot starting (polling)…")
    try:
        await dp.start_polling(bot)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await vpn.close()
        await bot.session.close()
        await close_db()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
