"""In-memory pub-sub bus for dashboard live events.

A single process serves both the bot and the dashboard, so a plain in-memory
fan-out is enough. Publishers (bot handlers, billing, broadcasts) call
``bus.publish({...})``; the dashboard WebSocket subscribes and streams events to
admins. Not durable and not multi-instance — see ТЗ §11 (would need Redis).
"""
import asyncio
import logging
from collections import deque
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


class SimplePubSub:
    def __init__(self, history: int = 50) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._recent: deque[dict[str, Any]] = deque(maxlen=history)

    def publish(self, event: dict[str, Any]) -> None:
        """Fan a fire-and-forget event out to every subscriber. Safe to call from
        sync code; never raises into the caller."""
        self._recent.append(event)
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:  # slow consumer — drop, don't block the bot
                logger.debug("dropping event for a full subscriber queue")

    def recent(self) -> list[dict[str, Any]]:
        return list(self._recent)

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subscribers.discard(q)


bus = SimplePubSub()
