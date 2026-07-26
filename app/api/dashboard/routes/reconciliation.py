"""Reconciliation — panel↔DB expiry watchdog (over-issuance).

GET /reconciliation/candidates?limit=N   compare each active paid subscription's
Remnawave expireAt with the DB expires_at; flag panel > DB by ≥1 day (the user
has more panel access than the DB says they paid for), or a missing panel user.

Read-only diagnostic. Bounded + paced (sequential panel reads), so keep the
limit modest.
"""
import asyncio
from datetime import datetime, timezone

from aiohttp import web

import config
import database
from app.services import remnawave

from ..util import int_query, json_ok

routes = web.RouteTableDef()


def _parse_iso(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@routes.get("/reconciliation/candidates")
async def candidates(request: web.Request) -> web.Response:
    limit = int_query(request, "limit", 100, 1, 400)
    rows = await database.active_paid_for_reconcile(limit)
    out = []
    scanned = 0
    for r in rows:
        scanned += 1
        try:
            panel = await remnawave.find_user_by_username(
                config.build_username(r["telegram_id"])
            )
        except Exception:  # noqa: BLE001 - skip a bad panel read, keep scanning
            await asyncio.sleep(0.02)
            continue

        db_exp = r["expires_at"]
        if panel is None:
            out.append({
                "telegram_id": r["telegram_id"], "issue": "no_panel",
                "db_expires": db_exp, "panel_expires": None, "days_over": 0,
            })
        else:
            panel_exp = _parse_iso(panel.get("expireAt"))
            if panel_exp and db_exp and panel_exp > db_exp:
                days_over = (panel_exp - db_exp).days
                if days_over >= 1:
                    out.append({
                        "telegram_id": r["telegram_id"], "issue": "over_issued",
                        "db_expires": db_exp, "panel_expires": panel_exp,
                        "days_over": days_over,
                    })
        await asyncio.sleep(0.02)  # gentle pacing on the panel

    out.sort(key=lambda c: c["days_over"], reverse=True)
    return json_ok({"scanned": scanned, "limit": limit, "candidates": out})
