"""Minimal HTTP server for Platega payment webhooks.

Runs in the same process/event loop as the bot (started from ``main`` only when
Platega is configured). Platega POSTs the final transaction status to
``/platega/webhook``; we verify the credentials, then provision idempotently.

Platega retries non-2xx responses (up to 3 times, 5 min apart), so:
  * duplicate / already-paid  -> 200 (stop retrying)
  * provisioning failed       -> 500 (let it retry; complete_purchase is idempotent)
"""
import logging

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

import config
from app.services import billing, platega
from app.tariffs import TARIFFS, get_tariff
from database import get_payment, is_payment_paid, mark_payment_failed

logger = logging.getLogger(__name__)


async def _health(_: web.Request) -> web.Response:
    return web.Response(text="ok")


async def _platega_webhook(request: web.Request) -> web.Response:
    if not platega.verify_callback(
        request.headers.get("X-MerchantId"), request.headers.get("X-Secret")
    ):
        logger.warning("Platega webhook with bad credentials from %s", request.remote)
        return web.Response(status=403, text="forbidden")

    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return web.Response(status=400, text="bad json")

    txn_id = data.get("id")
    status = data.get("status")
    if not txn_id or not status:
        return web.Response(status=400, text="missing fields")

    logger.info("Platega webhook: txn=%s status=%s", txn_id, status)

    # Idempotency — Platega retries, and a status can arrive more than once.
    if await is_payment_paid(txn_id):
        return web.Response(text="already processed")

    if status != platega.STATUS_CONFIRMED:
        # CANCELED / CHARGEBACKED — record the failure (admin Payments tab) and ack.
        reason = (
            "Возврат средств (CHARGEBACKED)"
            if status == platega.STATUS_CHARGEBACKED
            else "Платёж отменён или не завершён (CANCELED)"
        )
        await mark_payment_failed(txn_id, reason)
        return web.Response(text="ignored")

    payment = await get_payment(txn_id)
    if payment is None:
        # We journal a pending row before showing the pay link, so this is odd.
        logger.warning("Platega CONFIRMED for unknown txn %s", txn_id)
        return web.Response(text="unknown txn")

    tariff = get_tariff(payment["tariff_code"]) or TARIFFS[0]
    bot: Bot = request.app["bot"]
    try:
        await billing.complete_purchase(
            bot,
            payment["telegram_id"],
            tariff,
            invoice_id=txn_id,
            amount_paid=payment["amount_kopecks"],
        )
    except Exception as exc:  # noqa: BLE001 - let Platega retry (idempotent)
        logger.exception("Provisioning failed for Platega txn %s", txn_id)
        # Surface the error in the admin tab; status stays retryable until paid.
        await mark_payment_failed(txn_id, f"Ошибка выдачи доступа: {exc}")
        return web.Response(status=500, text="provisioning failed")

    await billing.notify_purchase_activated(bot, payment["telegram_id"])
    logger.info("Platega payment provisioned: txn=%s user=%s", txn_id, payment["telegram_id"])
    return web.Response(text="ok")


def build_app(bot: Bot, dp: Dispatcher | None = None) -> web.Application:
    """Build the aiohttp app. When ``dp`` is given, Telegram updates are served
    on ``config.WEBHOOK_PATH`` alongside the Platega callback (same port)."""
    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/", _health)
    app.router.add_post("/platega/webhook", _platega_webhook)
    if dp is not None:
        SimpleRequestHandler(
            dispatcher=dp,
            bot=bot,
            secret_token=config.TELEGRAM_WEBHOOK_SECRET,
        ).register(app, path=config.WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)
    return app


async def start_server(bot: Bot, dp: Dispatcher | None = None) -> web.AppRunner:
    """Start the HTTP server; returns the runner so it can be cleaned up.

    Always serves ``/`` and ``/platega/webhook``; with ``dp`` it also serves the
    Telegram webhook endpoint.
    """
    runner = web.AppRunner(build_app(bot, dp))
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=config.WEBHOOK_PORT)
    await site.start()
    routes = "/platega/webhook" + (f" + {config.WEBHOOK_PATH}" if dp else "")
    logger.info("HTTP server listening on :%d (%s)", config.WEBHOOK_PORT, routes)
    return runner
