"""Broadcasts — audience segments and sending (with live progress events).

GET  /broadcasts/segments   [{key, label, count}] across all segments
POST /broadcasts/test-self  {text, photo_file_id?, button_text?, button_url?}
                            preview to the requesting admin only
POST /broadcasts            {segment, text, photo_file_id?, button_text?, button_url?}
                            start a background send; progress via bus events

No persistence table yet — runs stream progress over the WebSocket and finish
with a broadcast:done event (ТЗ broadcast history can be added later).
"""
import asyncio
import logging

from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web

import database
from app.events import bus
from app.services import broadcaster

from ..util import json_ok, read_json

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()


def _markup(button_text: str | None, button_url: str | None):
    if button_text and button_url:
        kb = InlineKeyboardBuilder()
        kb.button(text=button_text, url=button_url)
        return kb.as_markup()
    return None


def _sender(bot, text: str, photo: str | None, markup):
    async def send_one(uid: int) -> None:
        if photo:
            await bot.send_photo(
                uid, photo, caption=text, parse_mode="HTML", reply_markup=markup
            )
        else:
            await bot.send_message(
                uid, text, parse_mode="HTML", reply_markup=markup,
                disable_web_page_preview=True,
            )

    return send_one


@routes.get("/broadcasts/segments")
async def segments(request: web.Request) -> web.Response:
    out = []
    for key, (label, _where) in database.SEGMENTS.items():
        out.append({"key": key, "label": label, "count": await database.segment_count(key)})
    return json_ok(out)


@routes.post("/broadcasts/test-self")
async def test_self(request: web.Request) -> web.Response:
    bot = request.config_dict["bot"]
    body = await read_json(request)
    text = str(body.get("text", "")).strip()
    if not text and not body.get("photo_file_id"):
        raise web.HTTPBadRequest(reason="empty message")
    admin_id = int(request["admin"]["sub"])
    markup = _markup(body.get("button_text"), body.get("button_url"))
    try:
        await _sender(bot, text, body.get("photo_file_id"), markup)(admin_id)
    except Exception as exc:  # noqa: BLE001
        raise web.HTTPBadRequest(reason=f"send failed: {exc}")
    return json_ok({"ok": True})


@routes.post("/broadcasts")
async def create(request: web.Request) -> web.Response:
    bot = request.config_dict["bot"]
    body = await read_json(request)
    segment = str(body.get("segment", ""))
    text = str(body.get("text", "")).strip()
    photo = body.get("photo_file_id")
    if segment not in database.SEGMENTS:
        raise web.HTTPBadRequest(reason="unknown segment")
    if not text and not photo:
        raise web.HTTPBadRequest(reason="empty message")

    admin_id = int(request["admin"]["sub"])
    user_ids = await database.recipients(segment)
    markup = _markup(body.get("button_text"), body.get("button_url"))
    send_one = _sender(bot, text, photo, markup)
    total = len(user_ids)

    await database.log_audit(admin_id, "broadcast", None, f"{segment} → {total}")
    bus.publish({"type": "broadcast:created", "segment": segment, "total": total})

    async def run() -> None:
        async def progress(res) -> None:
            bus.publish({
                "type": "broadcast:progress", "segment": segment,
                "sent": res.sent, "blocked": res.blocked,
                "failed": res.failed, "total": total,
            })

        res = await broadcaster.broadcast(user_ids, send_one, progress=progress)
        bus.publish({
            "type": "broadcast:done", "segment": segment,
            "sent": res.sent, "blocked": res.blocked,
            "failed": res.failed, "total": total,
        })
        logger.info(
            "Dashboard broadcast to %s done: sent=%d blocked=%d failed=%d",
            segment, res.sent, res.blocked, res.failed,
        )

    asyncio.create_task(run())
    return json_ok({"ok": True, "segment": segment, "total": total}, status=202)
