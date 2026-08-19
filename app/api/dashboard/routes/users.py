"""User search, detail and manual access control (grant / revoke).

GET  /users               search + pagination
GET  /users/{tg}          full detail + recent payments + referral stats
POST /users/{tg}/grant    {days}  — provision/extend access (source=admin)
POST /users/{tg}/revoke   suspend the subscription and deprovision the panel
"""
from aiohttp import web

import database
from app.events import bus

from ..util import json_ok, page_params, read_json

routes = web.RouteTableDef()


def _tg(request: web.Request) -> int:
    try:
        return int(request.match_info["tg"])
    except ValueError:
        raise web.HTTPBadRequest(reason="bad telegram_id")


@routes.get("/users")
async def list_users(request: web.Request) -> web.Response:
    q = request.query.get("q", "").strip()
    offset, limit, page = page_params(request, default_limit=25, max_limit=100)
    items = await database.users_search(q, offset, limit)
    total = await database.users_count(q)
    return json_ok({"items": items, "total": total, "page": page, "limit": limit})


@routes.get("/users/{tg}")
async def user(request: web.Request) -> web.Response:
    tg = _tg(request)
    detail = await database.user_detail(tg)
    if detail is None:
        raise web.HTTPNotFound(reason="user not found")
    return json_ok(
        {
            "user": detail,
            "payments": await database.user_payments(tg, 50),
            "referral": await database.referral_stats(tg),
        }
    )


@routes.post("/users/{tg}/grant")
async def grant(request: web.Request) -> web.Response:
    from app.services import subscription_service

    tg = _tg(request)
    body = await read_json(request)
    try:
        days = int(body.get("days"))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(reason="days required")
    if not 0 < days <= 3650:
        raise web.HTTPBadRequest(reason="days out of range")

    current = await database.get_subscription(tg)
    expire = subscription_service.next_expiry(current, days)
    try:
        await subscription_service.create_or_renew(tg, expire, source="admin")
    except Exception as exc:  # noqa: BLE001 - panel/db failure -> 502
        raise web.HTTPBadGateway(reason=f"provision failed: {exc}")

    await database.log_audit(int(request["admin"]["sub"]), "grant", tg, f"+{days}d")
    bus.publish({"type": "admin:grant", "telegram_id": tg, "days": days})
    return json_ok({"ok": True, "expires_at": expire})


@routes.post("/users/{tg}/revoke")
async def revoke(request: web.Request) -> web.Response:
    from app.services import subscription_service

    tg = _tg(request)
    sub = await database.revoke_subscription(tg)
    if sub and sub["panel_uuid"]:
        try:
            await subscription_service.deprovision(sub["panel_uuid"])
        except Exception:  # noqa: BLE001 - DB already marked revoked; panel best-effort
            pass
    await database.log_audit(int(request["admin"]["sub"]), "revoke", tg)
    bus.publish({"type": "admin:revoke", "telegram_id": tg})
    return json_ok({"ok": True})


async def _notify_reissue(bot, tg: int) -> None:
    """Tell the user their subscription was reissued; the Подключиться flow shows
    the fresh key (it re-reads the current panel key each time)."""
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    from app.utils import safe_send

    kb = InlineKeyboardBuilder()
    kb.button(text="📲 Подключиться", callback_data="dev:menu")
    kb.button(text="🏠 Главное меню", callback_data="menu:main")
    kb.adjust(1)
    await safe_send(
        bot, tg,
        "🔑 <b>Ваша подписка обновлена</b>\n\n"
        "Ключ доступа перевыпущен — старый ключ больше не действует.\n\n"
        "Нажми «Подключиться», чтобы установить новый ключ на своих устройствах 👇",
        reply_markup=kb.as_markup(),
    )


@routes.post("/users/{tg}/reissue")
async def reissue(request: web.Request) -> web.Response:
    """Reissue the user's subscription: rotate the aggregator link + the panel
    VPN key, then notify the user. Records the admin's reason; logs any error."""
    from app.services import subscription_service

    tg = _tg(request)
    body = await read_json(request)
    reason = str(body.get("reason", "")).strip()[:300]
    admin_id = int(request["admin"]["sub"])

    # 1. Rotate the aggregator link — DB-only, instant, can't break the VPN.
    #    The old /sub link dies immediately.
    await database.reissue_sub_token(tg)

    # 2. Rotate the panel VPN key (new vless url; old configs stop working).
    try:
        sub = await subscription_service.reissue(tg)
    except Exception as exc:  # noqa: BLE001 - panel failure: log and surface
        detail = f"{reason} | {exc}" if reason else str(exc)
        await database.log_audit(admin_id, "reissue_error", tg, detail[:300])
        raise web.HTTPBadGateway(reason=f"reissue failed: {exc}")

    # 3. Notify the user — the Подключиться flow serves the new key automatically.
    await _notify_reissue(request.config_dict["bot"], tg)

    # 4. Audit success with the reason (per-user record).
    await database.log_audit(admin_id, "reissue", tg, reason or None)
    bus.publish({"type": "admin:reissue", "telegram_id": tg})
    return json_ok({"ok": True, "had_active_sub": sub is not None})


@routes.post("/users/{tg}/discount")
async def set_discount(request: web.Request) -> web.Response:
    """Give the user a personal discount (offer) applied on the buy screen."""
    from datetime import datetime, timedelta, timezone

    tg = _tg(request)
    body = await read_json(request)
    try:
        percent = int(body.get("percent"))
        days = int(body.get("days", 1))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(reason="percent required")
    if not 1 <= percent <= 99:
        raise web.HTTPBadRequest(reason="percent 1..99")
    if not 1 <= days <= 365:
        raise web.HTTPBadRequest(reason="days 1..365")

    expires = datetime.now(timezone.utc) + timedelta(days=days)
    await database.set_offer(tg, "admin", percent, expires)
    await database.log_audit(
        int(request["admin"]["sub"]), "discount_set", tg, f"-{percent}% {days}d"
    )
    bus.publish({"type": "admin:discount", "telegram_id": tg, "percent": percent})
    return json_ok({"ok": True, "expires_at": expires})


@routes.post("/users/{tg}/discount/clear")
async def clear_discount(request: web.Request) -> web.Response:
    tg = _tg(request)
    await database.clear_offer(tg)
    await database.log_audit(int(request["admin"]["sub"]), "discount_clear", tg)
    return json_ok({"ok": True})
