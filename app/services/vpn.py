"""Thin async client over the Remnawave panel REST API.

One server, no cluster logic. Four operations: add / update-expiry / delete /
find. The panel username is ``tg_{telegram_id}`` so the DB<->panel link can be
rebuilt from the panel alone if needed (§6.1).

The exact Remnawave payload shape can vary between panel versions, so response
parsing is defensive: we accept both ``{...}`` and ``{"response": {...}}`` and
probe a few common field names for the uuid and subscription URL.
"""
import logging
from datetime import datetime

import aiohttp

from config import (
    REMNAWAVE_TOKEN,
    REMNAWAVE_URL,
    VPN_TRAFFIC_LIMIT_GB,
    panel_username,
)
from database import to_db_utc

logger = logging.getLogger(__name__)

_GB = 1024 * 1024 * 1024
_session: aiohttp.ClientSession | None = None


def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        if not REMNAWAVE_URL or not REMNAWAVE_TOKEN:
            raise RuntimeError("REMNAWAVE_URL / REMNAWAVE_TOKEN are not configured")
        _session = aiohttp.ClientSession(
            base_url=REMNAWAVE_URL,
            headers={
                "Authorization": f"Bearer {REMNAWAVE_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=aiohttp.ClientTimeout(total=20),
        )
    return _session


async def close() -> None:
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
        _session = None


def _unwrap(payload: dict) -> dict:
    if isinstance(payload, dict) and isinstance(payload.get("response"), dict):
        return payload["response"]
    return payload


def _extract(data: dict) -> dict:
    """Pull (uuid, vless_url) out of a panel user object, defensively."""
    data = _unwrap(data)
    uuid = data.get("uuid") or data.get("id") or data.get("userUuid")
    url = (
        data.get("subscriptionUrl")
        or data.get("subscription_url")
        or data.get("vlessUrl")
        or data.get("vless_url")
        or data.get("url")
    )
    return {"uuid": uuid, "url": url}


def _expire_iso(expires_at: datetime) -> str:
    return to_db_utc(expires_at).isoformat()


async def add_user(telegram_id: int, expires_at: datetime) -> dict:
    """POST /api/users — returns ``{"uuid": ..., "url": ...}``.

    Idempotent-ish: if the panel reports the username already exists we fall
    back to looking it up and updating its expiry, so retries don't blow up.
    """
    session = _get_session()
    body = {
        "username": panel_username(telegram_id),
        "status": "ACTIVE",
        "expireAt": _expire_iso(expires_at),
        "trafficLimitBytes": VPN_TRAFFIC_LIMIT_GB * _GB,
        "trafficLimitStrategy": "NO_RESET",
    }
    async with session.post("/api/users", json=body) as resp:
        if resp.status in (409, 400):
            text = await resp.text()
            if "exist" in text.lower():
                logger.info("Panel user for %s exists; recovering", telegram_id)
                existing = await find_user(telegram_id)
                if existing and existing.get("uuid"):
                    await update_user_expiry(existing["uuid"], expires_at)
                    return existing
            resp.raise_for_status()
        resp.raise_for_status()
        data = await resp.json()
    result = _extract(data)
    if not result["uuid"]:
        raise RuntimeError(f"Remnawave add_user returned no uuid: {data!r}")
    return result


async def update_user_expiry(uuid: str, expires_at: datetime) -> None:
    """PATCH /api/users/{uuid} — extend the subscription."""
    session = _get_session()
    body = {"uuid": uuid, "status": "ACTIVE", "expireAt": _expire_iso(expires_at)}
    async with session.patch(f"/api/users/{uuid}", json=body) as resp:
        resp.raise_for_status()


async def delete_user(uuid: str) -> None:
    """DELETE /api/users/{uuid} — revoke access. 404 is treated as success."""
    session = _get_session()
    async with session.delete(f"/api/users/{uuid}") as resp:
        if resp.status == 404:
            return
        resp.raise_for_status()


async def find_user(telegram_id: int) -> dict | None:
    """GET /api/users/by-username/{username} — for recovery / sanity."""
    session = _get_session()
    username = panel_username(telegram_id)
    async with session.get(f"/api/users/by-username/{username}") as resp:
        if resp.status == 404:
            return None
        resp.raise_for_status()
        data = await resp.json()
    result = _extract(data)
    return result if result["uuid"] else None
