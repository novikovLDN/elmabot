"""Broadcasts — segments, sending, history (last 500), resend and scheduling.

GET  /broadcasts/segments            [{key, label, count}]
POST /broadcasts/test-self           preview to the requesting admin(s)
POST /broadcasts                     start a send now (journaled in history)
GET  /broadcasts/history?limit=500   recent broadcasts (newest first)
POST /broadcasts/{id}/resend         re-run a past broadcast, as-is
GET  /broadcasts/scheduled           scheduled / recurring broadcasts
POST /broadcasts/scheduled           create one (once | daily | weekly, MSK)
POST /broadcasts/scheduled/{id}/toggle   pause / resume
POST /broadcasts/scheduled/{id}/cancel   delete

All times are Moscow (MSK, UTC+3); stored UTC. See broadcast_runner.
"""
import asyncio
import json
import logging

from aiohttp import web

import config
import database
from app.services import broadcast_runner

from ..util import int_query, json_ok, read_json

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()

_KINDS = ("once", "daily", "weekly")
_PRESET_KEYS = (
    "buy", "channel", "referral", "gift", "trial", "connect", "cabinet",
    "promo", "adddevice", "traffic", "support",
)
_SCOPES = ("all", "1m", "3m", "6m", "12m")


def _parse_button_specs(raw) -> str | None:
    """Validate incoming button specs into a JSON string for storage. Accepts
    preset keys (strings or {kind}) and discount specs {kind:discount,pct,hours,scope}."""
    if not isinstance(raw, list):
        return None
    specs: list[dict] = []
    for b in raw:
        if isinstance(b, str) and b in _PRESET_KEYS:
            specs.append({"kind": b})
        elif isinstance(b, dict):
            kind = b.get("kind")
            if kind in _PRESET_KEYS:
                specs.append({"kind": kind})
            elif kind == "discount":
                try:
                    pct, hours = int(b.get("pct")), int(b.get("hours"))
                except (TypeError, ValueError):
                    continue
                scope = str(b.get("scope", "all"))
                if 1 <= pct <= 99 and 1 <= hours <= 8760 and scope in _SCOPES:
                    specs.append({"kind": "discount", "pct": pct, "hours": hours, "scope": scope})
    return json.dumps(specs) if specs else None


def _clean(body: dict) -> dict:
    """Normalise a broadcast spec from a request body."""
    return {
        "segment": str(body.get("segment", "")),
        "text": str(body.get("text", "")).strip(),
        "photo_file_id": (body.get("photo_file_id") or None),
        "button_text": (body.get("button_text") or None),
        "button_url": (body.get("button_url") or None),
        "buttons": _parse_button_specs(body.get("buttons") or []),
        "text_b": (str(body.get("text_b", "")).strip() or None),
        "is_ab": bool(body.get("is_ab")),
    }


@routes.get("/broadcasts/segments")
async def segments(request: web.Request) -> web.Response:
    out = []
    for key, entry in database.SEGMENTS.items():
        label, _where = entry[0], entry[1]
        desc = entry[2] if len(entry) > 2 else ""
        out.append({
            "key": key, "label": label, "description": desc,
            "count": await database.segment_count(key),
        })
    return json_ok(out)


@routes.post("/broadcasts/test-self")
async def test_self(request: web.Request) -> web.Response:
    bot = request.config_dict["bot"]
    body = await read_json(request)
    spec = _clean(body)
    if not spec["text"] and not spec["photo_file_id"]:
        raise web.HTTPBadRequest(reason="empty message")
    markup = broadcast_runner.build_markup(spec["button_text"], spec["button_url"], spec["buttons"])
    send_one = broadcast_runner.build_sender(bot, spec["text"], spec["photo_file_id"], markup)
    sent = 0
    for aid in config.ADMIN_IDS:
        try:
            await send_one(aid)
            sent += 1
        except Exception:  # noqa: BLE001 - one bad admin chat shouldn't fail the test
            pass
    if sent == 0:
        raise web.HTTPBadRequest(reason="не удалось отправить тест ни одному админу")
    return json_ok({"ok": True, "sent": sent})


@routes.post("/broadcasts")
async def create(request: web.Request) -> web.Response:
    bot = request.config_dict["bot"]
    body = await read_json(request)
    spec = _clean(body)
    if spec["segment"] not in database.SEGMENTS:
        raise web.HTTPBadRequest(reason="unknown segment")
    if not spec["text"] and not spec["photo_file_id"]:
        raise web.HTTPBadRequest(reason="empty message")

    admin_id = int(request["admin"]["sub"])
    total = len(await database.recipients(spec["segment"]))
    asyncio.create_task(
        broadcast_runner.run_broadcast(bot, admin_id=admin_id, source="manual", **spec)
    )
    return json_ok({"ok": True, "segment": spec["segment"], "total": total}, status=202)


@routes.get("/broadcasts/history")
async def history(request: web.Request) -> web.Response:
    limit = int_query(request, "limit", 500, 1, 500)
    rows = await database.list_broadcasts(limit)
    return json_ok([dict(r) for r in rows])


@routes.get("/broadcasts/item/{id}")
async def get_one(request: web.Request) -> web.Response:
    """Single broadcast — used to prefill the "clone" wizard."""
    try:
        bid = int(request.match_info["id"])
    except ValueError:
        raise web.HTTPBadRequest(reason="bad id")
    row = await database.get_broadcast(bid)
    if row is None:
        raise web.HTTPNotFound(reason="broadcast not found")
    return json_ok(dict(row))


@routes.post("/broadcasts/{id}/resend")
async def resend(request: web.Request) -> web.Response:
    bot = request.config_dict["bot"]
    try:
        bid = int(request.match_info["id"])
    except ValueError:
        raise web.HTTPBadRequest(reason="bad id")
    row = await database.get_broadcast(bid)
    if row is None:
        raise web.HTTPNotFound(reason="broadcast not found")
    if row["segment"] not in database.SEGMENTS:
        raise web.HTTPBadRequest(reason="сегмент больше не существует")

    admin_id = int(request["admin"]["sub"])
    total = len(await database.recipients(row["segment"]))
    asyncio.create_task(broadcast_runner.run_broadcast(
        bot, admin_id=admin_id, source="resend", segment=row["segment"],
        text=row["text"], photo_file_id=row["photo_file_id"],
        button_text=row["button_text"], button_url=row["button_url"],
        buttons=row["buttons"], text_b=row["text_b"], is_ab=row["is_ab"],
    ))
    return json_ok({"ok": True, "segment": row["segment"], "total": total}, status=202)


# --- Scheduled / recurring -------------------------------------------------

@routes.get("/broadcasts/scheduled")
async def scheduled_list(request: web.Request) -> web.Response:
    rows = await database.list_scheduled()
    return json_ok([dict(r) for r in rows])


@routes.post("/broadcasts/scheduled")
async def scheduled_create(request: web.Request) -> web.Response:
    body = await read_json(request)
    spec = _clean(body)
    if spec["segment"] not in database.SEGMENTS:
        raise web.HTTPBadRequest(reason="unknown segment")
    if not spec["text"] and not spec["photo_file_id"]:
        raise web.HTTPBadRequest(reason="empty message")

    kind = str(body.get("kind", ""))
    if kind not in _KINDS:
        raise web.HTTPBadRequest(reason="kind: once | daily | weekly")

    time_msk = str(body.get("time_msk", "")).strip() or None
    weekdays = None
    run_at_local = str(body.get("run_at_local", "")).strip() or None
    try:
        if kind in ("daily", "weekly"):
            broadcast_runner.parse_hhmm(time_msk or "")  # validate
        if kind == "weekly":
            days = sorted(broadcast_runner.parse_weekdays(str(body.get("weekdays", ""))))
            weekdays = ",".join(str(d) for d in days)
        run_at = broadcast_runner.initial_run_at(
            kind, run_at_local=run_at_local, time_msk=time_msk, weekdays=weekdays,
        )
    except ValueError as exc:
        raise web.HTTPBadRequest(reason=str(exc))

    admin_id = int(request["admin"]["sub"])
    row = await database.create_scheduled(
        admin_id=admin_id, segment=spec["segment"], text=spec["text"],
        photo_file_id=spec["photo_file_id"], button_text=spec["button_text"],
        button_url=spec["button_url"], kind=kind, run_at=run_at,
        time_msk=time_msk if kind != "once" else None, weekdays=weekdays,
        buttons=spec["buttons"],
    )
    await database.log_audit(
        admin_id, "broadcast_schedule", None, f"{kind} {spec['segment']}"
    )
    return json_ok(dict(row), status=201)


@routes.post("/broadcasts/scheduled/{id}/toggle")
async def scheduled_toggle(request: web.Request) -> web.Response:
    try:
        sid = int(request.match_info["id"])
    except ValueError:
        raise web.HTTPBadRequest(reason="bad id")
    row = await database.get_scheduled(sid)
    if row is None:
        raise web.HTTPNotFound(reason="not found")
    new_active = not row["active"]
    # Resuming a recurring schedule whose slot has passed: move it to the next
    # future slot so it doesn't fire immediately on resume.
    if new_active and row["kind"] != "once":
        nxt = broadcast_runner.compute_next_run(
            row["kind"], row["time_msk"], row["weekdays"], broadcast_runner._now()
        )
        if nxt is not None:
            await database.set_scheduled_run_at(sid, nxt)
    await database.set_scheduled_active(sid, new_active)
    return json_ok({"ok": True, "active": new_active})


@routes.post("/broadcasts/scheduled/{id}/cancel")
async def scheduled_cancel(request: web.Request) -> web.Response:
    try:
        sid = int(request.match_info["id"])
    except ValueError:
        raise web.HTTPBadRequest(reason="bad id")
    await database.delete_scheduled(sid)
    return json_ok({"ok": True})
