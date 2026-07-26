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
    from app.services import cashback

    tg = _tg(request)
    detail = await database.user_detail(tg)
    if detail is None:
        raise web.HTTPNotFound(reason="user not found")
    referral = await database.referral_stats(tg)
    paid_refs = int(referral.get("purchased", 0))
    fixed = detail.get("cashback_fixed_percent")
    tier_pct, tier_name = cashback.tier_for(paid_refs)
    return json_ok(
        {
            "user": detail,
            "payments": await database.user_payments(tg, 50),
            "referral": referral,
            "cashback": {
                "fixed_percent": fixed,
                "tier_percent": tier_pct,
                "tier_name": tier_name,
                "effective_percent": cashback.effective_percent(paid_refs, fixed),
            },
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


@routes.post("/users/{tg}/balance")
async def adjust_balance(request: web.Request) -> web.Response:
    tg = _tg(request)
    body = await read_json(request)
    try:
        delta_rub = int(body.get("delta_rubles"))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(reason="delta_rubles required")
    if delta_rub == 0:
        raise web.HTTPBadRequest(reason="delta must be non-zero")
    delta_kop = delta_rub * 100
    if delta_kop < 0 and await database.get_balance(tg) + delta_kop < 0:
        raise web.HTTPBadRequest(reason="баланс не может стать отрицательным")
    new_balance = await database.adjust_balance(tg, delta_kop, "admin")
    await database.log_audit(int(request["admin"]["sub"]), "balance_adjust", tg, f"{delta_rub:+d} ₽")
    return json_ok({"ok": True, "balance_kopecks": new_balance})


@routes.post("/users/{tg}/vip")
async def set_vip(request: web.Request) -> web.Response:
    tg = _tg(request)
    body = await read_json(request)
    on = bool(body.get("on", True))
    await database.set_vip(tg, on)
    await database.log_audit(int(request["admin"]["sub"]), "vip_set" if on else "vip_clear", tg)
    return json_ok({"ok": True, "is_vip": on})


@routes.post("/users/{tg}/cashback-fix")
async def cashback_fix(request: web.Request) -> web.Response:
    tg = _tg(request)
    body = await read_json(request)
    try:
        percent = int(body.get("percent"))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(reason="percent required")
    if not 0 <= percent <= 100:
        raise web.HTTPBadRequest(reason="percent 0..100")
    await database.set_cashback_fixed(tg, percent)
    await database.log_audit(int(request["admin"]["sub"]), "cashback_fix", tg, f"{percent}%")
    return json_ok({"ok": True, "cashback_fixed_percent": percent})


@routes.post("/users/{tg}/cashback-fix/clear")
async def cashback_fix_clear(request: web.Request) -> web.Response:
    tg = _tg(request)
    await database.set_cashback_fixed(tg, None)
    await database.log_audit(int(request["admin"]["sub"]), "cashback_fix_clear", tg)
    return json_ok({"ok": True})
