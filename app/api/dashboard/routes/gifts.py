"""Gifts — issued gift codes and their redemption status.

GET /gifts   paginated list (newest first)
"""
from aiohttp import web

import database

from ..util import json_ok, page_params

routes = web.RouteTableDef()


@routes.get("/gifts")
async def list_gifts(request: web.Request) -> web.Response:
    offset, limit, page = page_params(request, default_limit=30, max_limit=100)
    items = await database.gifts_page(offset, limit)
    total = await database.gifts_count()
    return json_ok({"items": items, "total": total, "page": page, "limit": limit})
