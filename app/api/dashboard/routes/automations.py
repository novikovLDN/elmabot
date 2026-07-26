"""Automations — built-in lifecycle messages (edit text / on-off) + custom ones.

GET  /automations/builtin            built-in messages + current override
POST /automations/builtin/{key}      {enabled, text} override

GET  /automations                    custom automations
POST /automations                    create
POST /automations/{id}               update fields
POST /automations/{id}/toggle        enable / disable
POST /automations/{id}/delete        remove
"""
from aiohttp import web

import database
from app.services import notifications

from ..util import json_ok, read_json
from .broadcasts import _parse_button_specs

routes = web.RouteTableDef()

_TRIGGERS = ("after_signup", "after_trial_expire", "before_sub_expire", "after_sub_expire")
_SCOPES = ("all", "1m", "3m", "6m", "12m")


def _aid(request: web.Request) -> int:
    try:
        return int(request.match_info["id"])
    except ValueError:
        raise web.HTTPBadRequest(reason="bad id")


def _discount(body: dict):
    """(pct, hours, scope) or (None, None, None); raises on invalid."""
    pct = body.get("discount_pct")
    if pct in ("", None):
        return None, None, None
    try:
        pct = int(pct)
        hours = int(body.get("discount_hours", 24))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(reason="discount_pct/hours must be numbers")
    scope = str(body.get("discount_scope", "all"))
    if not 1 <= pct <= 99:
        raise web.HTTPBadRequest(reason="discount_pct 1..99")
    if not 1 <= hours <= 8760:
        raise web.HTTPBadRequest(reason="discount_hours 1..8760")
    if scope not in _SCOPES:
        raise web.HTTPBadRequest(reason="bad discount_scope")
    return pct, hours, scope


# --- Built-in overrides ----------------------------------------------------

@routes.get("/automations/builtin")
async def builtin(request: web.Request) -> web.Response:
    ov = await database.list_overrides()
    out = []
    for item in notifications.builtin_registry():
        o = ov.get(item["key"], {})
        out.append({
            **item,
            "enabled": o.get("enabled", True),
            "text_override": o.get("text"),
        })
    return json_ok(out)


@routes.post("/automations/builtin/{key}")
async def set_builtin(request: web.Request) -> web.Response:
    key = request.match_info["key"]
    if key not in {i["key"] for i in notifications.builtin_registry()}:
        raise web.HTTPNotFound(reason="unknown automation")
    body = await read_json(request)
    enabled = bool(body.get("enabled", True))
    text = str(body.get("text", "")).strip() or None
    await database.set_override(key, enabled=enabled, text=text)
    await database.log_audit(int(request["admin"]["sub"]), "automation_builtin", None, key)
    return json_ok({"ok": True})


# --- Custom automations ----------------------------------------------------

@routes.get("/automations")
async def list_auto(request: web.Request) -> web.Response:
    return json_ok([dict(r) for r in await database.list_automations()])


@routes.post("/automations")
async def create_auto(request: web.Request) -> web.Response:
    body = await read_json(request)
    name = str(body.get("name", "")).strip()
    trigger = str(body.get("trigger_type", ""))
    text = str(body.get("text", "")).strip()
    if not name or trigger not in _TRIGGERS or not text:
        raise web.HTTPBadRequest(reason="name, trigger_type и text обязательны")
    try:
        delay_hours = int(body.get("delay_hours", 0))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(reason="delay_hours must be a number")
    if not 0 <= delay_hours <= 8760:
        raise web.HTTPBadRequest(reason="delay_hours 0..8760")
    pct, hours, scope = _discount(body)
    row = await database.create_automation(
        name=name[:80], trigger_type=trigger, delay_hours=delay_hours, text=text,
        discount_pct=pct, discount_hours=hours, discount_scope=scope,
        buttons=_parse_button_specs(body.get("buttons") or []),
    )
    await database.log_audit(int(request["admin"]["sub"]), "automation_create", None, name)
    return json_ok(dict(row), status=201)


@routes.post("/automations/{id}")
async def update_auto(request: web.Request) -> web.Response:
    aid = _aid(request)
    body = await read_json(request)
    fields: dict = {}
    if "name" in body:
        fields["name"] = str(body["name"]).strip()[:80]
    if "text" in body:
        fields["text"] = str(body["text"]).strip()
    if "delay_hours" in body:
        try:
            d = int(body["delay_hours"])
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(reason="delay_hours must be a number")
        fields["delay_hours"] = max(0, min(d, 8760))
    if "trigger_type" in body:
        if body["trigger_type"] not in _TRIGGERS:
            raise web.HTTPBadRequest(reason="bad trigger_type")
        fields["trigger_type"] = body["trigger_type"]
    if "discount_pct" in body:
        pct, hours, scope = _discount(body)
        fields["discount_pct"] = pct
        fields["discount_hours"] = hours
        fields["discount_scope"] = scope
    if "buttons" in body:
        fields["buttons"] = _parse_button_specs(body.get("buttons") or [])
    if not fields:
        raise web.HTTPBadRequest(reason="нет полей для обновления")
    await database.update_automation(aid, **fields)
    return json_ok({"ok": True})


@routes.post("/automations/{id}/toggle")
async def toggle_auto(request: web.Request) -> web.Response:
    aid = _aid(request)
    row = next((r for r in await database.list_automations() if r["id"] == aid), None)
    if row is None:
        raise web.HTTPNotFound(reason="not found")
    await database.update_automation(aid, enabled=not row["enabled"])
    return json_ok({"ok": True, "enabled": not row["enabled"]})


@routes.post("/automations/{id}/delete")
async def delete_auto(request: web.Request) -> web.Response:
    aid = _aid(request)
    await database.delete_automation(aid)
    await database.log_audit(int(request["admin"]["sub"]), "automation_delete", None, str(aid))
    return json_ok({"ok": True})
