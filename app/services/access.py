"""Provisioning glue between the DB transaction and the VPN panel.

These builders return the ``provision`` callbacks that database.subscriptions
invokes *inside* the transaction, so VPN provisioning and the DB write are
atomic.
"""
import logging
from datetime import datetime

import asyncpg

from . import vpn

logger = logging.getLogger(__name__)


def trial_provision(telegram_id: int):
    async def _provision(expires_at: datetime) -> tuple[str, str]:
        res = await vpn.add_user(telegram_id, expires_at)
        return res["uuid"], res["url"]

    return _provision


def extend_provision(telegram_id: int):
    async def _provision(
        sub: asyncpg.Record | None, new_expires: datetime
    ) -> tuple[str, str]:
        if sub is not None and sub["vpn_uuid"]:
            await vpn.update_user_expiry(sub["vpn_uuid"], new_expires)
            return sub["vpn_uuid"], sub["vpn_url"]
        res = await vpn.add_user(telegram_id, new_expires)
        return res["uuid"], res["url"]

    return _provision


async def deprovision(uuid: str | None) -> None:
    """Best-effort panel delete; never raises (cleanup must not crash loops)."""
    if not uuid:
        return
    try:
        await vpn.delete_user(uuid)
    except Exception:  # noqa: BLE001 - cleanup is best-effort
        logger.exception("Failed to delete panel user %s", uuid)
