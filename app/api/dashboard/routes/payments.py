"""Finance endpoints — payments feed, revenue windows, provider split.

GET /payments              paginated feed (newest first)
GET /payments/revenue      paid revenue & counts per time window
GET /payments/by-provider  paid revenue split by provider
"""
from aiohttp import web

import database

from ..util import int_query, json_ok, page_params

routes = web.RouteTableDef()


@routes.get("/payments")
async def list_payments(request: web.Request) -> web.Response:
    offset, limit, page = page_params(request, default_limit=30, max_limit=100)
    items = await database.payments_page(offset, limit)
    total = await database.payments_count()
    return json_ok({"items": items, "total": total, "page": page, "limit": limit})


@routes.get("/payments/revenue")
async def revenue(request: web.Request) -> web.Response:
    return json_ok(await database.revenue_windows())


@routes.get("/payments/by-provider")
async def by_provider(request: web.Request) -> web.Response:
    hours = int_query(request, "hours", 24 * 30, 1, 24 * 365)
    return json_ok(await database.revenue_by_provider(hours))
