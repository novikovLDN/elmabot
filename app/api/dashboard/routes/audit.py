"""Audit log of admin actions (read-only).

GET /audit   paginated, newest first
"""
from aiohttp import web

import database

from ..util import json_ok, page_params

routes = web.RouteTableDef()


@routes.get("/audit")
async def list_audit(request: web.Request) -> web.Response:
    offset, limit, page = page_params(request, default_limit=50, max_limit=200)
    items = await database.audit_page(offset, limit)
    total = await database.audit_count()
    return json_ok({"items": items, "total": total, "page": page, "limit": limit})
