"""Admin dashboard sub-app: REST API + WebSocket + the built SPA.

Mounted onto the bot's aiohttp server by :func:`setup_dashboard` when
``DASHBOARD_ENABLED`` is set. URLs:
    GET  /dashboard/                SPA (Vite build)
    *    /dashboard/api/...         REST API (JWT, except /auth/*)
    WS   /dashboard/ws              live event stream
"""
import logging
from pathlib import Path

from aiohttp import web

import config

from . import auth, passkey
from .routes import (
    audit,
    broadcasts,
    bypass,
    gifts,
    links,
    payments,
    promo,
    referrals,
    settings,
    stats,
    users,
)
from .security import require_admin
from .ws import ws_handler

logger = logging.getLogger(__name__)

# repo root / dashboard / dist  (Vite build output)
_DIST = Path(__file__).resolve().parents[3] / "dashboard" / "dist"

_PLACEHOLDER = (
    "<!doctype html><html lang='ru'><meta charset='utf-8'>"
    "<title>Dashboard</title>"
    "<body style='font-family:system-ui;background:#0b0b10;color:#e5e7eb;"
    "display:grid;place-items:center;height:100vh;margin:0'>"
    "<div style='text-align:center'><h1>Дашборд не собран</h1>"
    "<p style='color:#94a3b8'>Соберите фронтенд: <code>cd dashboard &amp;&amp; "
    "npm install &amp;&amp; npm run build</code> (в Docker — автоматически).</p></div>"
)


@web.middleware
async def _auth_middleware(request: web.Request, handler):
    # /auth/* endpoints handle their own access; everything else needs a JWT.
    if not request.path.startswith("/dashboard/api/auth/"):
        request["admin"] = require_admin(request)
    return await handler(request)


def build_api(bot) -> web.Application:
    api = web.Application(middlewares=[_auth_middleware])
    api["bot"] = bot
    api.add_routes(auth.routes)
    api.add_routes(passkey.routes)
    for module in (stats, users, payments, referrals, broadcasts, gifts, audit, settings, bypass, promo, links):
        api.add_routes(module.routes)
    return api


async def _spa(request: web.Request) -> web.StreamResponse:
    tail = request.match_info.get("tail", "")
    if tail:
        candidate = (_DIST / tail).resolve()
        # serve real build files (manifest, sw.js, icons); guard traversal
        if _DIST in candidate.parents and candidate.is_file():
            return web.FileResponse(candidate)
    index = _DIST / "index.html"
    if index.is_file():
        return web.FileResponse(index)
    return web.Response(text=_PLACEHOLDER, content_type="text/html")


def setup_dashboard(app: web.Application, bot) -> None:
    """Mount the dashboard onto the main aiohttp app (no-op if disabled)."""
    if not config.DASHBOARD_ENABLED:
        return
    app.add_subapp("/dashboard/api", build_api(bot))
    app.router.add_get("/dashboard/ws", ws_handler)
    assets = _DIST / "assets"
    if assets.is_dir():
        app.router.add_static("/dashboard/assets", assets)
    app.router.add_get("/dashboard", _spa)
    app.router.add_get("/dashboard/", _spa)
    app.router.add_get("/dashboard/{tail:.*}", _spa)
    logger.info("Admin dashboard mounted at /dashboard/ (dist present: %s)", _DIST.is_dir())
