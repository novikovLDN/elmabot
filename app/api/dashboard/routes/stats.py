"""Analytics endpoints — overview KPIs, revenue, time-series, breakdowns.

GET /stats/overview   users + subscription health + revenue + activity (one call)
GET /stats/revenue    paid revenue & counts per time window
GET /stats/daily      per-UTC-day series (revenue/payments/users/subs)
GET /stats/hourly     24 rows by Moscow hour-of-day
GET /stats/providers  paid revenue split by provider
GET /stats/breakdown  paid revenue split by tariff
"""
from aiohttp import web

import database

from ..util import int_query, json_ok

routes = web.RouteTableDef()


@routes.get("/stats/overview")
async def overview(request: web.Request) -> web.Response:
    return json_ok(
        {
            "users": await database.stats(),
            "health": await database.subscription_health(),
            "revenue": await database.revenue_windows(),
            "activity": await database.activity_windows(),
        }
    )


@routes.get("/stats/revenue")
async def revenue(request: web.Request) -> web.Response:
    return json_ok(await database.revenue_windows())


@routes.get("/stats/daily")
async def daily(request: web.Request) -> web.Response:
    days = int_query(request, "days", 30, 1, 365)
    return json_ok({"days": days, "series": await database.daily_timeseries(days)})


@routes.get("/stats/hourly")
async def hourly(request: web.Request) -> web.Response:
    days = int_query(request, "days", 7, 1, 90)
    return json_ok({"days": days, "series": await database.hourly_timeseries(days)})


@routes.get("/stats/providers")
async def providers(request: web.Request) -> web.Response:
    hours = int_query(request, "hours", 24 * 30, 1, 24 * 365)
    return json_ok(await database.revenue_by_provider(hours))


@routes.get("/stats/breakdown")
async def breakdown(request: web.Request) -> web.Response:
    hours = int_query(request, "hours", 24 * 30, 1, 24 * 365)
    return json_ok(await database.purchase_breakdown(hours))
