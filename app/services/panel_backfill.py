"""One-shot panel backfill (Remnawave 3.x migration helper).

For every user we've provisioned, this:
  1. locates the panel entity (by username, then by telegramId);
  2. stores the entity's numeric 3.x ``id`` in our DB (completes the uuid->id
     migration so renewals PATCH by the right identifier);
  3. sets ``telegramId`` on the panel entity if it's missing/wrong.

Admin-triggered from Telegram (``/panelbackfill``). Idempotent and paced so it's
safe to run on a loaded panel.
"""
import asyncio
import logging

import config
from database import (
    all_bypass,
    all_provisioned,
    set_bypass_panel_uuid,
    set_panel_uuid,
)

from . import remnawave

logger = logging.getLogger(__name__)


async def _fix_one(username: str, telegram_id: int, *, bypass: bool) -> str:
    found = await remnawave.find_user_by_username(username)
    if found is None:
        found = await remnawave.find_user_by_telegram_id(telegram_id, username=username)
    if found is None:
        return "not_found"
    pid = found.get("id")
    if pid is None:
        return "no_id"
    pid = str(pid)
    # Store the numeric id in our DB (uuid -> id migration).
    if bypass:
        await set_bypass_panel_uuid(telegram_id, pid)
    else:
        await set_panel_uuid(telegram_id, pid)
    # Fill telegramId on the panel entity if it's absent or wrong.
    if found.get("telegramId") != telegram_id:
        await remnawave.update_user(pid, telegramId=telegram_id)
        return "tg_fixed"
    return "ok"


async def run(progress=None) -> dict:
    """Backfill every provisioned premium + bypass entity. ``progress(done,
    total, stats)`` is awaited periodically for a live status. Returns stats."""
    subs = await all_provisioned()
    byps = await all_bypass()
    targets = [
        (config.build_username(r["telegram_id"]), r["telegram_id"], False) for r in subs
    ] + [
        (config.build_bypass_username(r["telegram_id"]), r["telegram_id"], True) for r in byps
    ]

    stats = {"total": 0, "ok": 0, "tg_fixed": 0, "not_found": 0, "no_id": 0, "error": 0}
    total = len(targets)
    for i, (username, tg, is_bp) in enumerate(targets, 1):
        stats["total"] += 1
        try:
            res = await _fix_one(username, tg, bypass=is_bp)
            stats[res] = stats.get(res, 0) + 1
        except Exception:  # noqa: BLE001 - keep going; one bad user mustn't stop it
            logger.exception("panel backfill failed for tg=%s", tg)
            stats["error"] += 1
        if progress is not None and i % 25 == 0:
            try:
                await progress(i, total, stats)
            except Exception:  # noqa: BLE001
                pass
        await asyncio.sleep(0.03)  # gentle pacing on the panel
    logger.info("panel backfill done: %s", stats)
    return stats
