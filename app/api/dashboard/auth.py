"""Authentication endpoints (exempt from the admin guard).

POST /auth/login          {password, telegram_id?} -> {token, telegram_id}
GET  /auth/setup/{token}   validate a magic-link, returns {valid, telegram_id}
POST /auth/setup          {token, password} -> set password, returns {token}
GET  /auth/me             current admin (manual Bearer check)
"""
from aiohttp import web

import database

from .security import hash_password, make_jwt, require_admin, verify_password
from .util import json_ok, read_json

routes = web.RouteTableDef()


async def _admins_with_password() -> list[int]:
    pool = database.get_pool()
    rows = await pool.fetch(
        "SELECT telegram_id FROM admin_auth WHERE password_hash IS NOT NULL"
    )
    return [r["telegram_id"] for r in rows]


@routes.post("/auth/login")
async def login(request: web.Request) -> web.Response:
    body = await read_json(request)
    password = str(body.get("password", ""))
    raw_tg = body.get("telegram_id")
    if raw_tg not in (None, ""):
        try:
            tg = int(raw_tg)
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(reason="bad telegram_id")
    else:
        ids = await _admins_with_password()
        if len(ids) == 1:
            tg = ids[0]
        elif not ids:
            raise web.HTTPUnauthorized(reason="no admin password set — use /dashboard in the bot")
        else:
            raise web.HTTPBadRequest(reason="telegram_id required")

    if not verify_password(password, await database.get_admin_password_hash(tg)):
        raise web.HTTPUnauthorized(reason="invalid credentials")
    user = await database.get_user(tg)
    username = user["username"] if user else None
    return json_ok({"token": make_jwt(tg, username), "telegram_id": tg})


@routes.get("/auth/setup/{token}")
async def setup_check(request: web.Request) -> web.Response:
    rec = await database.peek_login_token(request.match_info["token"])
    if rec is None:
        return json_ok({"valid": False})
    return json_ok(
        {"valid": True, "telegram_id": rec["telegram_id"], "purpose": rec["purpose"]}
    )


@routes.post("/auth/setup")
async def setup(request: web.Request) -> web.Response:
    body = await read_json(request)
    token = str(body.get("token", ""))
    password = str(body.get("password", ""))
    if len(password) < 8:
        raise web.HTTPBadRequest(reason="password must be at least 8 characters")
    rec = await database.consume_login_token(token)
    if rec is None:
        raise web.HTTPUnauthorized(reason="invalid or expired link")
    tg = rec["telegram_id"]
    await database.set_admin_password(tg, hash_password(password))
    await database.log_audit(tg, "password_set")
    user = await database.get_user(tg)
    username = user["username"] if user else None
    return json_ok({"token": make_jwt(tg, username), "telegram_id": tg})


@routes.get("/auth/me")
async def me(request: web.Request) -> web.Response:
    payload = require_admin(request)
    return json_ok(
        {"telegram_id": int(payload["sub"]), "username": payload.get("username")}
    )
