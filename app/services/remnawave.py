"""Thin async client over the Remnawave panel REST API (httpx), **v3.x**.

Four user operations plus a squad helper. Auth is a Bearer token.

Remnawave 3.x breaking changes handled here:
- users are identified by a numeric ``id`` (the ``uuid`` field is gone). PATCH
  carries ``{"id": <int>, ...}`` in the body; DELETE is ``/api/users/{id}``.
- our stored ``panel_uuid`` column now holds that numeric id (as a string); a
  legacy (non-numeric) value yields ``None`` from :func:`_as_id`, so the caller
  re-adopts the record by ``username`` (still supported) and heals itself.
- squad membership uses ``userIds`` (numbers), not ``userUuids``.
- DELETE returns 204 (no body); ``404`` is normalised to ``None``.

No webhooks panel->bot: the bot always drives the panel.
"""
import asyncio
import logging

import httpx

import config

logger = logging.getLogger(__name__)

_BASE = config.REMNAWAVE_URL.rstrip("/")
_TIMEOUT = httpx.Timeout(15.0)
_RETRIES = 3
_RETRY_BACKOFF = 0.5  # seconds, doubled each attempt

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Lazily create a shared client bound to the running event loop."""
    global _client
    if _client is None or _client.is_closed:
        if not _BASE or not config.REMNAWAVE_TOKEN:
            raise RuntimeError("REMNAWAVE_URL / REMNAWAVE_TOKEN are not configured")
        _client = httpx.AsyncClient(
            base_url=_BASE,
            headers={"Authorization": f"Bearer {config.REMNAWAVE_TOKEN}"},
            timeout=_TIMEOUT,
        )
    return _client


async def close() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None


async def _req(method: str, path: str, **kwargs) -> dict | None:
    """One request with light retries on transient transport / 5xx errors.

    Returns the parsed JSON, or ``None`` for ``404``. Raises
    ``httpx.HTTPStatusError`` for other non-2xx responses (e.g. 409 conflict),
    so the caller can branch on the status code.
    """
    client = _get_client()
    delay = _RETRY_BACKOFF
    last_exc: Exception | None = None
    for attempt in range(1, _RETRIES + 1):
        try:
            resp = await client.request(method, path, **kwargs)
        except httpx.TransportError as exc:  # connect/read/timeout
            last_exc = exc
            logger.warning(
                "Remnawave %s %s transport error (attempt %d/%d): %s",
                method, path, attempt, _RETRIES, exc,
            )
        else:
            if resp.status_code == 404:
                return None
            if resp.status_code >= 500 and attempt < _RETRIES:
                logger.warning(
                    "Remnawave %s %s -> %d (attempt %d/%d), retrying",
                    method, path, resp.status_code, attempt, _RETRIES,
                )
            else:
                resp.raise_for_status()
                if resp.content:
                    return _unwrap(resp.json())
                return {}
        if attempt < _RETRIES:
            await asyncio.sleep(delay)
            delay *= 2
    assert last_exc is not None
    raise last_exc


def _unwrap(payload: dict) -> dict:
    """Remnawave sometimes nests the object under ``{"response": {...}}``."""
    if isinstance(payload, dict) and isinstance(payload.get("response"), dict):
        return payload["response"]
    return payload


# --- User operations -------------------------------------------------------

def _as_id(identifier) -> int | None:
    """Coerce a stored identifier to Remnawave's numeric user id (3.x). A legacy
    uuid string (or None) returns None, so the caller re-adopts by username."""
    try:
        return int(identifier)
    except (TypeError, ValueError):
        return None


async def create_user(payload: dict) -> dict:
    """POST /api/users -> 201. The response carries the numeric ``id``."""
    return await _req("POST", "/api/users", json=payload)


async def update_user(identifier, **fields) -> dict | None:
    """PATCH /api/users — 3.x identifies the user by numeric ``id`` in the body.
    A non-numeric (legacy uuid) identifier returns ``None`` so the caller heals
    the record via find-by-username; ``None`` also on 404."""
    uid = _as_id(identifier)
    if uid is None:
        return None
    return await _req("PATCH", "/api/users", json={"id": uid, **fields})


async def find_user_by_username(username: str) -> dict | None:
    """GET /api/users/by-username/{username} — still supported in 3.x (unlike
    by-telegram-id / by-email / by-tag / by-id). Returns the object with the
    numeric ``id``, or ``None`` on 404."""
    return await _req("GET", f"/api/users/by-username/{username}")


async def delete_user(identifier) -> None:
    """DELETE /api/users/{id} (numeric id in 3.x). 204/404 both mean 'gone'."""
    uid = _as_id(identifier)
    if uid is None:
        return
    await _req("DELETE", f"/api/users/{uid}")


async def add_users_to_squad(squad_uuid: str, user_ids: list) -> dict | None:
    """Attach users to an internal squad — safety net for a freshly created user
    that came back with an empty ``activeInternalSquads``. 3.x uses ``userIds``
    (numbers), not ``userUuids``."""
    ids = [i for i in (_as_id(u) for u in user_ids) if i is not None]
    if not ids:
        return None
    return await _req(
        "POST",
        "/api/squads/add-users-to-squad",
        json={"squadUuid": squad_uuid, "userIds": ids},
    )
