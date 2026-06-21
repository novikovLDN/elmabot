"""WebSocket fan-out of live bot events to dashboard admins.

The browser can't set Authorization headers on a WebSocket, so the JWT is passed
as ``?token=``. On connect we replay the recent backlog, then stream new events.
"""
import asyncio
import logging

from aiohttp import web

from app.events import bus

from .security import JWTError, decode_jwt
from .util import _dumps

logger = logging.getLogger(__name__)


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    try:
        decode_jwt(request.query.get("token", ""))
    except JWTError:
        raise web.HTTPUnauthorized(reason="invalid token")

    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    for event in bus.recent()[-25:]:
        await ws.send_json(event, dumps=_dumps)

    async def pump() -> None:
        async for event in bus.subscribe():
            await ws.send_json(event, dumps=_dumps)

    task = asyncio.create_task(pump())
    try:
        async for _msg in ws:  # drain client frames (pings/close)
            pass
    finally:
        task.cancel()
    return ws
