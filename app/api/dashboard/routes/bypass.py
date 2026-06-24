"""Bypass migration — provision a bypass entity for existing subscribers.

GET  /bypass/backfill/preview   eligible count + running state
POST /bypass/backfill {gb}      start a paced background backfill

Targets active *paid* subscribers without a bypass entity yet, creates their
Remnawave bypass profile (right squad) with ``gb`` GB so they have access and
metering starts. Idempotent (skips anyone who already has bypass), paced to
respect panel rate limits, runs in the background with live progress events.
"""
import asyncio
import logging

from aiohttp import web

import config
import database
from app.events import bus
from app.services import bypass_service

from ..util import json_ok, read_json

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()

_GB = 1024 ** 3
_running = False  # single-instance guard against concurrent backfills


@routes.get("/bypass/backfill/preview")
async def preview(request: web.Request) -> web.Response:
    eligible = await database.bypass_backfill_count() if config.BYPASS_ENABLED else 0
    return json_ok(
        {"enabled": config.BYPASS_ENABLED, "eligible": eligible, "running": _running}
    )


@routes.post("/bypass/backfill")
async def backfill(request: web.Request) -> web.Response:
    global _running
    if not config.BYPASS_ENABLED:
        raise web.HTTPBadRequest(reason="bypass disabled — set REMNAWAVE_BYPASS_SQUAD_UUID")
    if _running:
        raise web.HTTPConflict(reason="backfill already running")

    body = await read_json(request)
    try:
        gb = int(body.get("gb"))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(reason="gb required")
    if not 1 <= gb <= 100_000:
        raise web.HTTPBadRequest(reason="gb out of range (1..100000)")

    admin_id = int(request["admin"]["sub"])
    targets = await database.bypass_backfill_targets()
    total = len(targets)
    extra = gb * _GB
    pace = config.BYPASS_BACKFILL_PACE_MS / 1000.0

    _running = True
    bus.publish({"type": "bypass_backfill:started", "total": total, "gb": gb})
    await database.log_audit(admin_id, "bypass_backfill", None, f"{total} users × {gb} ГБ")

    async def run() -> None:
        global _running
        ok = failed = done = 0
        try:
            for uid in targets:
                # Re-check idempotency: skip anyone who got a bypass meanwhile.
                existing = await database.get_bypass(uid)
                if existing and existing["panel_uuid"]:
                    done += 1
                    continue
                try:
                    await bypass_service.provision_traffic(uid, extra)
                    ok += 1
                except Exception:  # noqa: BLE001 - one bad user mustn't stop the run
                    failed += 1
                    logger.exception("bypass backfill failed for %s", uid)
                done += 1
                if done % 20 == 0:
                    bus.publish({
                        "type": "bypass_backfill:progress",
                        "done": done, "total": total, "ok": ok, "failed": failed,
                    })
                await asyncio.sleep(pace)
            bus.publish({
                "type": "bypass_backfill:done",
                "done": done, "total": total, "ok": ok, "failed": failed,
            })
            logger.info("Bypass backfill done: ok=%d failed=%d total=%d", ok, failed, total)
        finally:
            _running = False

    asyncio.create_task(run())
    return json_ok({"ok": True, "total": total, "gb": gb}, status=202)
