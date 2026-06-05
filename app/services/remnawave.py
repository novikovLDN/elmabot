"""Thin async client over the Remnawave panel REST API (httpx).

Four user operations plus a squad helper. Auth is a Bearer token. The panel
PATCHes through a single ``/api/users`` endpoint (uuid in the body, not the
path). ``404`` is normalised to ``None`` so callers can treat "missing" as data
rather than an exception.

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

async def create_user(payload: dict) -> dict:
    return await _req("POST", "/api/users", json=payload)


async def update_user(panel_uuid: str, **fields) -> dict | None:
    """PATCH /api/users — uuid travels in the body. ``None`` on 404."""
    return await _req("PATCH", "/api/users", json={"uuid": panel_uuid, **fields})


async def find_user_by_username(username: str) -> dict | None:
    return await _req("GET", f"/api/users/by-username/{username}")


async def delete_user(panel_uuid: str) -> None:
    """DELETE /api/users/{uuid}. 404 is treated as already-deleted."""
    await _req("DELETE", f"/api/users/{panel_uuid}")


async def add_users_to_squad(squad_uuid: str, user_uuids: list[str]) -> dict | None:
    """Attach users to an internal squad — the §10.4 safety net for when a
    freshly created user came back with an empty ``activeInternalSquads``."""
    return await _req(
        "POST",
        "/api/squads/add-users-to-squad",
        json={"squadUuid": squad_uuid, "userUuids": user_uuids},
    )
