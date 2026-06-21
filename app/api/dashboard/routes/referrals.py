"""Referral programme — overall KPIs and the inviter leaderboard.

GET /referrals/overall   totals (referrals / credited / referrers)
GET /referrals/top       leaderboard page (top inviters)
"""
from aiohttp import web

import database

from ..util import json_ok, page_params

routes = web.RouteTableDef()


@routes.get("/referrals/overall")
async def overall(request: web.Request) -> web.Response:
    return json_ok(await database.referrals_overview())


@routes.get("/referrals/top")
async def top(request: web.Request) -> web.Response:
    offset, limit, page = page_params(request, default_limit=25, max_limit=100)
    items = await database.referral_leaderboard(offset, limit)
    total = await database.referral_leaderboard_count()
    return json_ok({"items": items, "total": total, "page": page, "limit": limit})
