"""Subscription provisioning — the idempotent glue over the Remnawave panel.

``create_or_renew`` is the heart (docs TЗ §6): it talks to the panel first and
mirrors the result into the DB afterwards, so a crash mid-flight is always
recoverable. The recovery path is find-by-username: even if we lost
``panel_uuid`` in the DB, ``elma_<telegram_id>`` lets us re-adopt the panel
record instead of orphaning it.

One product, one server (MainSquad), one panel entity per user, unlimited
traffic. No basic/plus split.
"""
import logging
from datetime import datetime, timedelta

import asyncpg
import httpx

import config
from database import (
    claim_trial,
    clear_panel_uuid,
    get_subscription,
    release_trial,
    upsert_subscription,
    utcnow,
)
from database import to_db_utc

from . import remnawave

logger = logging.getLogger(__name__)

_DESCRIPTION = "Elma bot subscription"


def _iso_z(dt: datetime) -> str:
    """ISO-8601 UTC with a literal ``Z`` (§10.2 — anything else and Remnawave
    silently stores ``expireAt`` as null)."""
    return to_db_utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def next_expiry(current: asyncpg.Record | None, days: int) -> datetime:
    """``max(now, current_expiry) + days`` — renewing never burns leftover time
    and never resurrects an expired date into the past."""
    return next_expiry_delta(current, timedelta(days=days))


def next_expiry_delta(
    current: asyncpg.Record | None, delta: timedelta
) -> datetime:
    """Like :func:`next_expiry` but for an arbitrary duration (admin grants of
    months / days / hours / minutes). Extends from the later of now and the
    current expiry, so an active subscription is prolonged rather than reset."""
    base = utcnow()
    if current is not None and current["expires_at"] is not None:
        base = max(base, current["expires_at"])
    return base + delta


def _extract(data: dict | None) -> dict:
    """Pull the fields we persist out of a panel user object, defensively."""
    data = data or {}
    return {
        "panel_uuid": data.get("uuid") or data.get("id") or data.get("userUuid"),
        "vless_uuid": data.get("vlessUuid") or data.get("vless_uuid"),
        "subscription_url": (
            data.get("subscriptionUrl")
            or data.get("subscription_url")
            or data.get("url")
        ),
        "squads": data.get("activeInternalSquads") or [],
    }


def _build_create_payload(
    telegram_id: int, expire_at: datetime, *, vless_uuid: str | None
) -> dict:
    payload = {
        "username": config.build_username(telegram_id),
        "trafficLimitBytes": config.TRAFFIC_LIMIT_BYTES,  # 0 = unlimited
        "trafficLimitStrategy": "NO_RESET",
        "status": "ACTIVE",
        "expireAt": _iso_z(expire_at),
        "deviceLimit": config.DEVICE_LIMIT,
        "description": _DESCRIPTION,
        "telegramId": telegram_id,
    }
    if config.REMNAWAVE_MAIN_SQUAD_UUID:
        payload["activeInternalSquads"] = [config.REMNAWAVE_MAIN_SQUAD_UUID]
    # Reuse the same VLESS uuid when recreating a lost record so the user does
    # not have to reconfigure the client (§3).
    if vless_uuid:
        payload["vlessUuid"] = vless_uuid
    return payload


async def _ensure_squad(extracted: dict) -> None:
    """§10.4 safety net: a created user with no squad reaches no inbound."""
    squad = config.REMNAWAVE_MAIN_SQUAD_UUID
    if squad and extracted["panel_uuid"] and not extracted["squads"]:
        try:
            await remnawave.add_users_to_squad(squad, [extracted["panel_uuid"]])
        except Exception:  # noqa: BLE001 - non-fatal, logged for ops
            logger.exception(
                "Failed to add %s to squad %s", extracted["panel_uuid"], squad
            )


async def _persist(
    telegram_id: int,
    expire_at: datetime,
    source: str,
    *panel_dicts: dict | None,
    db_sub: asyncpg.Record | None,
) -> asyncpg.Record:
    """Merge panel response(s) (PATCH bodies can omit url/vless) with the
    existing DB row and write the subscription."""
    panel_uuid = vless_uuid = sub_url = None
    for d in panel_dicts:
        e = _extract(d)
        panel_uuid = panel_uuid or e["panel_uuid"]
        vless_uuid = vless_uuid or e["vless_uuid"]
        sub_url = sub_url or e["subscription_url"]
    if db_sub is not None:
        panel_uuid = panel_uuid or db_sub["panel_uuid"]
        vless_uuid = vless_uuid or db_sub["vless_uuid"]
        sub_url = sub_url or db_sub["subscription_url"]
    if not panel_uuid:
        raise RuntimeError(f"Remnawave response carried no uuid for {telegram_id}")
    return await upsert_subscription(
        telegram_id,
        panel_uuid=panel_uuid,
        vless_uuid=vless_uuid,
        subscription_url=sub_url,
        expires_at=expire_at,
        source=source,
    )


async def _adopt(
    telegram_id: int,
    found: dict,
    expire_at: datetime,
    source: str,
    db_sub: asyncpg.Record | None,
) -> asyncpg.Record:
    """Take over an existing panel record: PATCH its expiry, then persist."""
    uuid = _extract(found)["panel_uuid"]
    patched = None
    if uuid:
        patched = await remnawave.update_user(
            uuid, expireAt=_iso_z(expire_at), status="ACTIVE"
        )
    return await _persist(
        telegram_id, expire_at, source, patched, found, db_sub=db_sub
    )


async def create_or_renew(
    telegram_id: int, expire_at: datetime, source: str
) -> asyncpg.Record:
    """Idempotently ensure the panel user exists with ``expire_at`` (§6).

    Panel call first, DB write second. Raises if the panel is unreachable so the
    caller can keep the payment ``pending`` / let the trial be retried.
    """
    username = config.build_username(telegram_id)
    sub = await get_subscription(telegram_id)
    panel_uuid = sub["panel_uuid"] if sub else None
    expire_iso = _iso_z(expire_at)

    # Step 2: we already know the panel uuid -> renew via PATCH.
    if panel_uuid:
        patched = await remnawave.update_user(
            panel_uuid, expireAt=expire_iso, status="ACTIVE"
        )
        if patched is None:
            # 404: record was deleted in the panel. Forget it and recreate.
            logger.info("Panel record for %s gone (404); recreating", telegram_id)
            await clear_panel_uuid(telegram_id)
        else:
            return await _persist(telegram_id, expire_at, source, patched, db_sub=sub)

    # Step 3: preflight — adopt a record left over from a half-finished run.
    found = await remnawave.find_user_by_username(username)
    if found:
        logger.info("Adopting existing panel record for %s", telegram_id)
        return await _adopt(telegram_id, found, expire_at, source, sub)

    # Step 4: create.
    vless_uuid = sub["vless_uuid"] if sub else None
    payload = _build_create_payload(telegram_id, expire_at, vless_uuid=vless_uuid)
    try:
        created = await remnawave.create_user(payload)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 409:
            # Race: the record appeared between preflight and POST -> adopt.
            logger.info("Create conflict for %s; adopting existing record", telegram_id)
            found = await remnawave.find_user_by_username(username)
            if found:
                return await _adopt(telegram_id, found, expire_at, source, sub)
        logger.exception("Remnawave create failed for %s", telegram_id)
        raise

    await _ensure_squad(_extract(created))
    return await _persist(telegram_id, expire_at, source, created, db_sub=sub)


async def activate_trial(
    telegram_id: int, trial_days: int
) -> asyncpg.Record | None:
    """Grant the one-time trial. Returns the subscription, or ``None`` if the
    trial was already used. Re-raises on panel failure after freeing the slot so
    the user can retry."""
    expire_at = utcnow() + timedelta(days=trial_days)
    if not await claim_trial(telegram_id, expire_at):
        return None
    try:
        return await create_or_renew(telegram_id, expire_at, source="trial")
    except Exception:
        await release_trial(telegram_id)
        raise


async def deprovision(panel_uuid: str | None) -> None:
    """Best-effort panel delete; never raises (cleanup must not crash loops)."""
    if not panel_uuid:
        return
    try:
        await remnawave.delete_user(panel_uuid)
    except Exception:  # noqa: BLE001 - cleanup is best-effort
        logger.exception("Failed to delete panel user %s", panel_uuid)


async def reissue(telegram_id: int) -> asyncpg.Record | None:
    """Rotate the user's keys: delete the panel entity and provision a fresh one
    (new vless uuid / subscription url) for the same expiry. Returns the new
    subscription row, or None if there's no active subscription.

    Deleting first means ``create_or_renew`` can't adopt the old panel record,
    so the client gets genuinely new keys."""
    sub = await get_subscription(telegram_id)
    if sub is None or sub["status"] != "active":
        return None
    if sub["panel_uuid"]:
        await deprovision(sub["panel_uuid"])
    await clear_panel_uuid(telegram_id)
    return await create_or_renew(
        telegram_id, sub["expires_at"], source=sub["source"] or "admin"
    )
