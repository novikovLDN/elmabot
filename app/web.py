"""Minimal HTTP server for Platega payment webhooks.

Runs in the same process/event loop as the bot (started from ``main`` only when
Platega is configured). Platega POSTs the final transaction status to
``/platega/webhook``; we verify the credentials, then provision idempotently.

Platega retries non-2xx responses (up to 3 times, 5 min apart), so:
  * duplicate / already-paid  -> 200 (stop retrying)
  * provisioning failed       -> 500 (let it retry; complete_purchase is idempotent)
"""
import asyncio
import base64
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

import config
from app.services import aggregator, billing, bypass_service, platega
from database import (
    get_bypass,
    get_payment,
    get_subscription,
    is_payment_paid,
    mark_payment_failed,
    user_by_sub_token,
)

logger = logging.getLogger(__name__)

# Branded one-tap connect page; the crypt key arrives in the URL #fragment and
# never reaches us, so this is a static file. Read once at import.
_CONNECT_HTML_PATH = Path(__file__).resolve().parent.parent / "web" / "connect.html"
try:
    _CONNECT_HTML = _CONNECT_HTML_PATH.read_text(encoding="utf-8")
except OSError:  # pragma: no cover - file should always ship with the app
    logger.warning("connect.html not found at %s", _CONNECT_HTML_PATH)
    _CONNECT_HTML = "<!doctype html><meta charset=utf-8><title>Elma</title>"


async def _health(_: web.Request) -> web.Response:
    return web.Response(text="ok")


async def _connect_page(_: web.Request) -> web.Response:
    return web.Response(
        text=_CONNECT_HTML,
        content_type="text/html",
        headers={"Cache-Control": "public, max-age=3600"},
    )


_bot_webpage_cache: str | None = None


async def _subscription_webpage(request: web.Request) -> str | None:
    """URL for the client's «Продлить» button / web-page icon — the configured
    one, else the bot's own t.me link (resolved once and cached)."""
    global _bot_webpage_cache
    if config.SUBSCRIPTION_WEBPAGE_URL:
        return config.SUBSCRIPTION_WEBPAGE_URL
    if _bot_webpage_cache is None:
        try:
            me = await request.app["bot"].me()
            _bot_webpage_cache = f"https://t.me/{me.username}?start=renew"
        except Exception:  # noqa: BLE001 - fall back to support
            _bot_webpage_cache = config.SUPPORT_URL or ""
    return _bot_webpage_cache or None


async def _happ_add(request: web.Request) -> web.Response:
    """One-tap add-to-Happ: an https link that 302-redirects to the ``happ://``
    deep link (happ:// itself isn't clickable in Telegram, https is)."""
    token = request.match_info.get("token", "")
    tg = await user_by_sub_token(token)
    if tg is None or (config.SUBSCRIPTION_ADMIN_ONLY and tg not in config.ADMIN_IDS):
        return web.Response(status=404, text="not found")
    return web.HTTPFound(f"happ://add/{aggregator.sub_link(token)}")


async def _build_subscription(request: web.Request, tg_id: int) -> tuple[bytes, dict]:
    """Resolve, fetch, merge and header-build a user's aggregated subscription.

    Returns ``(body, headers)`` for :func:`aggregator.serve` to cache and serve.
    Raises :class:`aggregator.SubscriptionNotFound` when the user has nothing to
    serve, and lets an upstream failure propagate (so ``serve`` can fall back to
    a stale copy)."""
    # Two subscription links to merge: premium (subscriptions table) and bypass
    # (bypass table). Take each link straight from where it's stored — that's the
    # actual link. get_usage is only for the remaining-traffic number.
    if config.BYPASS_ENABLED:
        sub, bp_row, usage = await asyncio.gather(
            get_subscription(tg_id), get_bypass(tg_id), bypass_service.get_usage(tg_id)
        )
    else:
        sub, bp_row, usage = await get_subscription(tg_id), None, None

    prem_active = bool(sub and sub["status"] == "active")
    prem_expire = sub["expires_at"] if prem_active else None
    # Resolve the premium URL LIVE from the panel (self-syncs a changed panel
    # link), reusing the row we already fetched. Bypass already self-syncs via
    # get_usage, so now both pick up a panel-side URL change immediately.
    from app.services import subscription_service

    prem_url = await subscription_service.resolve_live_url(tg_id, sub=sub) if prem_active else None
    # Bypass link: the stored subscription_url (fall back to the live usage read).
    bp_url = (
        (bp_row["subscription_url"] if bp_row else None)
        or (usage["subscription_url"] if usage else None)
        or None
    )
    # Only trust the numbers when they came from the panel this request.
    bp_live = bool(usage and usage.get("live"))
    bp_used = int(usage["used"]) if bp_live else 0
    bp_limit = int(usage["limit"]) if bp_live else 0
    bp_remaining = int(usage["remaining"]) if bp_live else None
    if not prem_url and not bp_url:
        raise aggregator.SubscriptionNotFound

    prem_note = config.SUBSCRIPTION_NOTE_PREMIUM
    bp_note = config.SUBSCRIPTION_NOTE_BYPASS

    # Fetch both config lists concurrently. Premium and bypass are independent
    # panel entities, so an active premium subscription always contributes its
    # UNLIMITED servers regardless of bypass state — the main servers stay
    # available even when bypass GB is used up. The bypass servers are served
    # exactly as the panel returns them (metered entity, LIMITED at 0 GB); the
    # traffic bar below reflects the panel's live usage so the client shows the
    # limit correctly and prompts a top-up.
    prem_task = asyncio.create_task(aggregator.fetch(prem_url)) if prem_url else None
    bp_task = asyncio.create_task(aggregator.fetch(bp_url)) if bp_url else None
    groups: list[tuple[str, bytes]] = []
    for note, task in ((prem_note, prem_task), (bp_note, bp_task)):
        if task is None:
            continue
        try:
            body, _ = await task
            groups.append((note, body))
            logger.info("aggregator %s: %r -> %d bytes", tg_id, note, len(body))
        except Exception:  # noqa: BLE001 - one source failing shouldn't sink the other
            logger.exception("aggregator fetch failed for %s (%s)", tg_id, note)

    combined = aggregator.combine(groups)
    if combined is None:
        # Nothing mergeable: either every upstream failed, or the panel answered
        # with a non-URI-list (a JSON/Clash template, e.g. a UA it maps to JSON).
        # Never serve that raw body as text/plain — it imports as garbage ("0
        # servers"). Signal an upstream error so serve() falls back to the last
        # good base64 copy (or 503), and log so the UA can be corrected.
        logger.error(
            "aggregator %s: no mergeable uri-list (%d source(s)); check "
            "SUBSCRIPTION_UPSTREAM_UA=%s via /aggcheck",
            tg_id, len(groups), config.SUBSCRIPTION_UPSTREAM_UA,
        )
        raise RuntimeError("no mergeable uri-list from panel")

    title_b64 = base64.b64encode(config.SUBSCRIPTION_TITLE.encode()).decode()
    headers: dict[str, str] = {
        "Content-Type": "text/plain; charset=utf-8",
        "Profile-Title": f"base64:{title_b64}",
        "Profile-Update-Interval": str(config.SUBSCRIPTION_UPDATE_INTERVAL),
        "Content-Disposition": f'inline; filename="{config.SUBSCRIPTION_BRAND}"',
    }
    # Web-page / «Продлить» button + support link shown in the client's header
    # card. Points at the bot's renew screen.
    webpage = await _subscription_webpage(request)
    if webpage:
        headers["Profile-Web-Page-Url"] = webpage
        headers["Support-Url"] = webpage

    # Description (legend + remaining bypass traffic, shown only when the figure
    # is live/known this request).
    announce = aggregator.build_announce(
        has_premium=bool(prem_url),
        has_bypass=bool(bp_url),
        remaining_bytes=bp_remaining if (bp_live and bp_limit > 0) else None,
    )
    if announce:
        headers["Announce"] = "base64:" + base64.b64encode(announce.encode()).decode()

    # Subscription-Userinfo drives the client's header card:
    #   • expire (premium end) -> the "истекает через N д" banner + «Продлить»
    #     button; sent whenever there's an active premium sub, INDEPENDENT of
    #     bypass (this is what was missing).
    #   • download/total (bypass metered) -> the traffic bar; only when live, so
    #     we never publish a stale consumption number (total=0 => unlimited).
    expire_ts = int(prem_expire.timestamp()) if prem_expire else 0
    metered = bp_live and bp_limit > 0
    download = bp_used if metered else 0
    total = bp_limit if metered else 0
    if expire_ts or metered:
        headers["Subscription-Userinfo"] = (
            f"upload=0; download={download}; total={total}; expire={expire_ts}"
        )
    return combined, headers


async def _subscription(request: web.Request) -> web.Response:
    """Aggregated subscription: merge the user's premium + bypass panel configs
    into one Elma-branded subscription served from our own domain. Admin-only
    while SUBSCRIPTION_ADMIN_ONLY.

    A short in-process cache + singleflight + stale fallback (aggregator.serve)
    absorbs client polling and keeps the link alive through a panel outage."""
    if not config.SUBSCRIPTION_BASE_URL:
        return web.Response(status=404, text="not found")
    token = request.match_info.get("token", "")
    if not aggregator.valid_token(token):
        return web.Response(status=404, text="not found")
    # The token is a per-user secret in the DB — an unknown/revoked token 404s.
    tg_id = await user_by_sub_token(token)
    if tg_id is None or (config.SUBSCRIPTION_ADMIN_ONLY and tg_id not in config.ADMIN_IDS):
        return web.Response(status=404, text="not found")

    try:
        body, headers, x_cache = await aggregator.serve(
            token, lambda: _build_subscription(request, tg_id)
        )
    except aggregator.SubscriptionNotFound:
        return web.Response(status=404, text="no subscription")
    except aggregator.SubscriptionUnavailable:
        return web.Response(status=503, text="upstream error", headers={"Retry-After": "30"})

    resp = web.Response(body=body)
    resp.headers.update(headers)
    resp.headers["X-Cache"] = x_cache
    # Never let the client / a CDN / a proxy serve a stale copy — our own cache
    # (aggregator.serve) is the single source of freshness, keyed to the token.
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


async def _subscription_metrics(_: web.Request) -> web.Response:
    """Aggregator health: hit_ratio, upstream ok/fail, cache sizes. Non-sensitive
    counters for monitoring (healthy: hit_ratio > 0.9)."""
    return web.json_response(aggregator.metrics_snapshot())


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

    bot: Bot = request.app["bot"]
    try:
        await billing.finalize_confirmed_payment(bot, payment)
    except Exception as exc:  # noqa: BLE001 - let Platega retry (idempotent)
        logger.exception("Finalize failed for Platega txn %s", txn_id)
        # Surface the error in the admin tab; status stays retryable until paid.
        await mark_payment_failed(txn_id, f"Ошибка обработки оплаты: {exc}")
        return web.Response(status=500, text="finalize failed")

    logger.info(
        "Platega payment finalized: txn=%s user=%s code=%s",
        txn_id, payment["telegram_id"], payment["tariff_code"],
    )
    return web.Response(text="ok")


def build_app(bot: Bot, dp: Dispatcher | None = None) -> web.Application:
    """Build the aiohttp app. When ``dp`` is given, Telegram updates are served
    on ``config.WEBHOOK_PATH`` alongside the Platega callback (same port)."""
    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/", _health)
    app.router.add_get("/connect", _connect_page)
    app.router.add_get("/sub/_metrics", _subscription_metrics)
    app.router.add_get("/sub/{token}", _subscription)
    app.router.add_get("/add/{token}", _happ_add)
    app.router.add_post("/platega/webhook", _platega_webhook)
    # Admin web dashboard (no-op unless DASHBOARD_ENABLED).
    from app.api.dashboard import setup_dashboard

    setup_dashboard(app, bot)
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
