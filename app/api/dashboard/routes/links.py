"""Marketing stats-links — acquisition attribution with a click→paid funnel.

GET  /links               list with per-link funnel + ready deep link
POST /links               create (auto 6-char slug); max 10 active
POST /links/{id}/toggle   activate / deactivate
POST /links/{id}/delete   remove
"""
import secrets
import string

from aiohttp import web

import database

from ..util import json_ok, read_json

routes = web.RouteTableDef()

_ALPHABET = string.ascii_lowercase + string.digits
_MAX_ACTIVE = 10
_username_cache: str | None = None


async def _bot_username(request: web.Request) -> str:
    global _username_cache
    if _username_cache is None:
        me = await request.config_dict["bot"].get_me()
        _username_cache = me.username or ""
    return _username_cache


def _gen_slug() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(6))


def _lid(request: web.Request) -> int:
    try:
        return int(request.match_info["id"])
    except ValueError:
        raise web.HTTPBadRequest(reason="bad id")


@routes.get("/links")
async def list_links(request: web.Request) -> web.Response:
    username = await _bot_username(request)
    out = []
    for r in await database.list_stat_links():
        funnel = await database.stat_link_funnel(r["id"])
        out.append({
            **dict(r),
            **funnel,
            "link": f"https://t.me/{username}?start=s-{r['slug']}",
        })
    return json_ok(out)


@routes.post("/links")
async def create_link(request: web.Request) -> web.Response:
    body = await read_json(request)
    name = str(body.get("name", "")).strip()
    if not name:
        raise web.HTTPBadRequest(reason="название обязательно")

    active = [r for r in await database.list_stat_links() if r["active"]]
    if len(active) >= _MAX_ACTIVE:
        raise web.HTTPBadRequest(reason=f"максимум {_MAX_ACTIVE} активных ссылок")

    slug = None
    for _ in range(10):
        cand = _gen_slug()
        if await database.get_stat_link_by_slug(cand) is None:
            slug = cand
            break
    if slug is None:
        raise web.HTTPBadRequest(reason="не удалось сгенерировать slug")

    row = await database.create_stat_link(slug, name[:80], int(request["admin"]["sub"]))
    await database.log_audit(int(request["admin"]["sub"]), "stat_link_create", None, slug)
    username = await _bot_username(request)
    return json_ok({
        **dict(row),
        "link": f"https://t.me/{username}?start=s-{slug}",
        "new_users": 0, "trials": 0, "paid": 0, "revenue_kopecks": 0,
    }, status=201)


@routes.post("/links/{id}/toggle")
async def toggle_link(request: web.Request) -> web.Response:
    lid = _lid(request)
    row = next((r for r in await database.list_stat_links() if r["id"] == lid), None)
    if row is None:
        raise web.HTTPNotFound(reason="not found")
    if not row["active"]:
        active = [r for r in await database.list_stat_links() if r["active"]]
        if len(active) >= _MAX_ACTIVE:
            raise web.HTTPBadRequest(reason=f"максимум {_MAX_ACTIVE} активных ссылок")
    await database.set_stat_link_active(lid, not row["active"])
    return json_ok({"ok": True, "active": not row["active"]})


@routes.post("/links/{id}/delete")
async def delete_link(request: web.Request) -> web.Response:
    lid = _lid(request)
    await database.delete_stat_link(lid)
    await database.log_audit(int(request["admin"]["sub"]), "stat_link_delete", None, str(lid))
    return json_ok({"ok": True})
