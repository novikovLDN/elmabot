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


@routes.post("/users/{tg}/reissue")
async def reissue(request: web.Request) -> web.Response:
    """Rotate the user's VPN keys (new subscription url); notify them."""
    from app.services import subscription_service
    from app.utils import safe_send

    tg = _tg(request)
    try:
        sub = await subscription_service.reissue(tg)
    except Exception as exc:  # noqa: BLE001 - panel failure
        raise web.HTTPBadGateway(reason=f"reissue failed: {exc}")
    if sub is None:
        raise web.HTTPBadRequest(reason="нет активной подписки")

    await database.log_audit(int(request["admin"]["sub"]), "reissue", tg)
    bot = request.config_dict["bot"]
    await safe_send(
        bot, tg,
        "🔑 <b>Ключ доступа перевыпущен</b>\n\n"
        "Старая ссылка больше не работает. Открой «Подключиться» и импортируй "
        "новый ключ на своих устройствах.",
    )
    return json_ok({"ok": True})


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
