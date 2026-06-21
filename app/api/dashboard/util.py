"""Shared helpers for dashboard routes: JSON serialization + pagination."""
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import asyncpg
from aiohttp import web


def _default(o: Any) -> Any:
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Decimal):
        # money is stored as integer kopecks; sums come back as Decimal
        return int(o) if o == o.to_integral_value() else float(o)
    if isinstance(o, asyncpg.Record):
        return dict(o)
    if isinstance(o, (set, frozenset)):
        return list(o)
    raise TypeError(f"not serializable: {type(o).__name__}")


def _dumps(data: Any) -> str:
    return json.dumps(data, default=_default, ensure_ascii=False)


def json_ok(data: Any, status: int = 200) -> web.Response:
    return web.json_response(data, status=status, dumps=_dumps)


def page_params(request: web.Request, default_limit: int = 50, max_limit: int = 200):
    """Parse ?page & ?limit (1-based page) into (offset, limit, page)."""
    try:
        page = max(1, int(request.query.get("page", "1")))
    except ValueError:
        page = 1
    try:
        limit = int(request.query.get("limit", str(default_limit)))
    except ValueError:
        limit = default_limit
    limit = max(1, min(limit, max_limit))
    return (page - 1) * limit, limit, page


def int_query(request: web.Request, name: str, default: int, lo: int, hi: int) -> int:
    try:
        val = int(request.query.get(name, str(default)))
    except ValueError:
        return default
    return max(lo, min(val, hi))


async def read_json(request: web.Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        raise web.HTTPBadRequest(reason="invalid json")
    if not isinstance(data, dict):
        raise web.HTTPBadRequest(reason="expected object")
    return data
