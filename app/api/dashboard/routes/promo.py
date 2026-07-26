"""Promo codes — list / create / toggle / delete.

GET  /promo                list all codes with usage
POST /promo                create a code (discount or bonus days)
POST /promo/{code}/toggle  activate / deactivate
POST /promo/{code}/delete  remove
"""
import re
from datetime import timedelta

from aiohttp import web

import database
from database import utcnow

from ..util import json_ok, read_json

routes = web.RouteTableDef()

_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{3,32}$")


@routes.get("/promo")
async def list_promo(request: web.Request) -> web.Response:
    rows = await database.list_promos()
    return json_ok([dict(r) for r in rows])


@routes.post("/promo")
async def create_promo(request: web.Request) -> web.Response:
    body = await read_json(request)
    code = str(body.get("code", "")).strip()
    if not _CODE_RE.match(code):
        raise web.HTTPBadRequest(reason="код: 3–32 символа [A-Za-z0-9_-]")
    kind = str(body.get("kind", ""))
    if kind not in ("discount", "days"):
        raise web.HTTPBadRequest(reason="kind: discount | days")

    discount_pct = discount_days = grant_days = None
    if kind == "discount":
        try:
            discount_pct = int(body.get("discount_pct"))
            discount_days = int(body.get("discount_days", 3))
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(reason="discount_pct required")
        if not 1 <= discount_pct <= 99:
            raise web.HTTPBadRequest(reason="discount_pct 1..99")
        if not 1 <= discount_days <= 365:
            raise web.HTTPBadRequest(reason="discount_days 1..365")
    else:
        try:
            grant_days = int(body.get("grant_days"))
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(reason="grant_days required")
        if not 1 <= grant_days <= 3650:
            raise web.HTTPBadRequest(reason="grant_days 1..3650")

    max_uses = body.get("max_uses")
    if max_uses in ("", None):
        max_uses = None
    else:
        try:
            max_uses = int(max_uses)
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(reason="max_uses must be a number")
        if max_uses < 1:
            raise web.HTTPBadRequest(reason="max_uses >= 1")

    try:
        per_user_limit = int(body.get("per_user_limit", 1))
    except (TypeError, ValueError):
        per_user_limit = 1
    per_user_limit = max(1, min(per_user_limit, 100))

    expires_at = None
    expires_days = body.get("expires_days")
    if expires_days not in ("", None):
        try:
            d = int(expires_days)
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(reason="expires_days must be a number")
        if d > 0:
            expires_at = utcnow() + timedelta(days=d)

    if await database.get_promo(code) is not None:
        raise web.HTTPConflict(reason="такой код уже есть")

    row = await database.create_promo(
        code=code, kind=kind, discount_pct=discount_pct, discount_days=discount_days,
        grant_days=grant_days, max_uses=max_uses, per_user_limit=per_user_limit,
        expires_at=expires_at, created_by=int(request["admin"]["sub"]),
    )
    await database.log_audit(int(request["admin"]["sub"]), "promo_create", None, code)
    return json_ok(dict(row), status=201)


@routes.post("/promo/{code}/toggle")
async def toggle_promo(request: web.Request) -> web.Response:
    code = request.match_info["code"]
    row = await database.get_promo(code)
    if row is None:
        raise web.HTTPNotFound(reason="not found")
    await database.set_promo_active(code, not row["active"])
    return json_ok({"ok": True, "active": not row["active"]})


@routes.post("/promo/{code}/delete")
async def delete_promo(request: web.Request) -> web.Response:
    code = request.match_info["code"]
    await database.delete_promo(code)
    await database.log_audit(int(request["admin"]["sub"]), "promo_delete", None, code)
    return json_ok({"ok": True})
