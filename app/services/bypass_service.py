"""Bypass provisioning — a second Remnawave entity, metered by GB.

Completely separate from premium (``subscription_service``): its own panel user
``<prefix>bp_<id>`` in the bypass squad, ``trafficLimitBytes`` accumulating with
every pack, ``expireAt`` far in the future. Buying bypass never touches the
premium row, and buying premium never touches this one.
"""
import logging
from datetime import timedelta

import config
from database import (
    clear_bypass_panel,
    get_bypass,
    set_bypass_meta,
    upsert_bypass,
    utcnow,
)

from . import remnawave

logger = logging.getLogger(__name__)

_DESCRIPTION = "Elma bypass (traffic)"


def _iso_z(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _far_future() -> str:
    return _iso_z(utcnow() + timedelta(days=config.BYPASS_EXPIRE_DAYS))


def _extract(data: dict | None) -> dict:
    data = data or {}
    return {
        "uuid": data.get("uuid") or data.get("id") or data.get("userUuid"),
        "url": (
            data.get("subscriptionUrl")
            or data.get("subscription_url")
            or data.get("url")
        ),
        "used": data.get("usedTrafficBytes") or data.get("used_traffic_bytes") or 0,
        "limit": data.get("trafficLimitBytes") or data.get("traffic_limit_bytes") or 0,
        "squads": data.get("activeInternalSquads") or [],
    }


def _create_payload(telegram_id: int, limit_bytes: int) -> dict:
    payload = {
        "username": config.build_bypass_username(telegram_id),
        "trafficLimitBytes": int(limit_bytes),
        "trafficLimitStrategy": "NO_RESET",
        "status": "ACTIVE",
        "expireAt": _far_future(),
        "deviceLimit": config.BYPASS_DEVICE_LIMIT,
        "description": _DESCRIPTION,
        "telegramId": telegram_id,
    }
    if config.REMNAWAVE_BYPASS_SQUAD_UUID:
        payload["activeInternalSquads"] = [config.REMNAWAVE_BYPASS_SQUAD_UUID]
    return payload


async def _ensure_squad(uuid: str | None, squads: list) -> None:
    squad = config.REMNAWAVE_BYPASS_SQUAD_UUID
    if squad and uuid and not squads:
        try:
            await remnawave.add_users_to_squad(squad, [uuid])
        except Exception:  # noqa: BLE001 - non-fatal
            logger.exception("Failed to add bypass %s to squad %s", uuid, squad)


async def _create_or_adopt(telegram_id: int, limit_bytes: int) -> tuple[str, str | None]:
    """Create a fresh bypass entity, or adopt one left in the panel."""
    username = config.build_bypass_username(telegram_id)
    found = await remnawave.find_user_by_username(username)
    if found:
        e = _extract(found)
        if e["uuid"]:
            patched = await remnawave.update_user(
                e["uuid"], trafficLimitBytes=int(limit_bytes),
                status="ACTIVE", expireAt=_far_future(),
            )
            pe = _extract(patched)
            await _ensure_squad(e["uuid"], e["squads"])
            return e["uuid"], pe["url"] or e["url"]

    created = _extract(await remnawave.create_user(_create_payload(telegram_id, limit_bytes)))
    if not created["uuid"]:
        raise RuntimeError(f"Remnawave bypass create returned no uuid for {telegram_id}")
    await _ensure_squad(created["uuid"], created["squads"])
    return created["uuid"], created["url"]


async def provision_trial_bonus(telegram_id: int) -> bool:
    """Create a bypass entity with the free trial bonus (BYPASS_TRIAL_BONUS_MB),
    once. Returns True if the bonus was granted. No-op if bypass is off, the
    bonus is 0, or the user already has a bypass entity (never stacks)."""
    if not config.BYPASS_ENABLED or config.BYPASS_TRIAL_BONUS_MB <= 0:
        return False
    row = await get_bypass(telegram_id)
    if row and row["panel_uuid"]:
        return False  # already has bypass — don't add the bonus again
    bonus_bytes = config.BYPASS_TRIAL_BONUS_MB * 1024 * 1024
    await provision_traffic(telegram_id, bonus_bytes)
    logger.info("Granted %d MB trial bypass bonus to %s",
                config.BYPASS_TRIAL_BONUS_MB, telegram_id)
    return True


async def provision_traffic(telegram_id: int, extra_bytes: int) -> int:
    """Add ``extra_bytes`` to the user's bypass entity (creating it if needed).
    Returns the new total limit in bytes. Panel call first, DB write second."""
    row = await get_bypass(telegram_id)
    if row and row["panel_uuid"]:
        new_limit = int(row["traffic_limit_bytes"] or 0) + int(extra_bytes)
        patched = await remnawave.update_user(
            row["panel_uuid"], trafficLimitBytes=new_limit, status="ACTIVE"
        )
        if patched is None:
            # 404 — entity gone from the panel; recreate with the new total.
            logger.info("Bypass entity for %s gone (404); recreating", telegram_id)
            await clear_bypass_panel(telegram_id)
            uuid, url = await _create_or_adopt(telegram_id, new_limit)
            await upsert_bypass(
                telegram_id, panel_uuid=uuid, subscription_url=url,
                traffic_limit_bytes=new_limit, reset_notify=True,
            )
            return new_limit
        url = _extract(patched)["url"] or row["subscription_url"]
        await upsert_bypass(
            telegram_id, panel_uuid=row["panel_uuid"], subscription_url=url,
            traffic_limit_bytes=new_limit, reset_notify=True,
        )
        return new_limit

    # First pack — create the entity.
    uuid, url = await _create_or_adopt(telegram_id, int(extra_bytes))
    await upsert_bypass(
        telegram_id, panel_uuid=uuid, subscription_url=url,
        traffic_limit_bytes=int(extra_bytes), reset_notify=True,
    )
    return int(extra_bytes)


async def get_usage(telegram_id: int) -> dict | None:
    """Live bypass usage: {used, limit, remaining, subscription_url}, or None if
    the user has no bypass entity. Syncs the cached link/limit on the way."""
    row = await get_bypass(telegram_id)
    if not row or not row["panel_uuid"]:
        return None
    try:
        user = await remnawave.find_user_by_username(
            config.build_bypass_username(telegram_id)
        )
    except Exception:  # noqa: BLE001 - never let a usage read break the cabinet
        logger.warning("Bypass usage read failed for %s; using cached", telegram_id)
        user = None
    if user is None:
        limit = int(row["traffic_limit_bytes"] or 0)
        return {
            "used": 0, "limit": limit, "remaining": limit,
            "subscription_url": row["subscription_url"],
        }
    e = _extract(user)
    used, limit = int(e["used"]), int(e["limit"])
    url = e["url"] or row["subscription_url"]
    await set_bypass_meta(telegram_id, subscription_url=url, traffic_limit_bytes=limit)
    return {
        "used": used, "limit": limit,
        "remaining": max(0, limit - used), "subscription_url": url,
    }
