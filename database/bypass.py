"""Bypass (traffic-metered) subscription storage.

A second, independent Remnawave entity per user, sold by GB packs. Kept entirely
separate from the premium ``subscriptions`` row so premium can never be touched
by a traffic purchase.
"""
import asyncpg

from .core import get_pool


async def get_bypass(telegram_id: int) -> asyncpg.Record | None:
    pool = get_pool()
    return await pool.fetchrow(
        "SELECT * FROM bypass_subscriptions WHERE telegram_id = $1", telegram_id
    )


async def upsert_bypass(
    telegram_id: int,
    *,
    panel_uuid: str | None,
    subscription_url: str | None,
    traffic_limit_bytes: int,
    reset_notify: bool = False,
) -> asyncpg.Record:
    """Insert/refresh the bypass row. ``reset_notify`` re-arms the low-traffic
    pushes (used right after a top-up)."""
    pool = get_pool()
    notify_clause = "-1" if reset_notify else "bypass_subscriptions.notify_level"
    return await pool.fetchrow(
        f"""
        INSERT INTO bypass_subscriptions
            (telegram_id, panel_uuid, subscription_url, traffic_limit_bytes,
             notify_level, updated_at)
        VALUES ($1, $2, $3, $4, -1, NOW())
        ON CONFLICT (telegram_id) DO UPDATE SET
            panel_uuid          = COALESCE(EXCLUDED.panel_uuid, bypass_subscriptions.panel_uuid),
            subscription_url    = COALESCE(EXCLUDED.subscription_url, bypass_subscriptions.subscription_url),
            traffic_limit_bytes = EXCLUDED.traffic_limit_bytes,
            notify_level        = {notify_clause},
            updated_at          = NOW()
        RETURNING *
        """,
        telegram_id,
        panel_uuid,
        subscription_url,
        traffic_limit_bytes,
    )


async def set_bypass_meta(
    telegram_id: int, *, subscription_url: str | None, traffic_limit_bytes: int
) -> None:
    """Sync the cached link/limit from a fresh panel read (no notify reset)."""
    pool = get_pool()
    await pool.execute(
        """
        UPDATE bypass_subscriptions
        SET subscription_url = COALESCE($2, subscription_url),
            traffic_limit_bytes = $3,
            updated_at = NOW()
        WHERE telegram_id = $1
        """,
        telegram_id,
        subscription_url,
        traffic_limit_bytes,
    )


async def set_bypass_notify_level(telegram_id: int, level: int) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE bypass_subscriptions SET notify_level = $2 WHERE telegram_id = $1",
        telegram_id,
        level,
    )


async def clear_bypass_panel(telegram_id: int) -> None:
    """Forget a stale panel uuid (404) so the next top-up recreates the entity."""
    pool = get_pool()
    await pool.execute(
        "UPDATE bypass_subscriptions SET panel_uuid = NULL WHERE telegram_id = $1",
        telegram_id,
    )


async def all_bypass() -> list[asyncpg.Record]:
    """Bypass rows with a provisioned entity (for the traffic monitor)."""
    pool = get_pool()
    return await pool.fetch(
        "SELECT telegram_id, panel_uuid, traffic_limit_bytes, notify_level "
        "FROM bypass_subscriptions WHERE panel_uuid IS NOT NULL"
    )


async def record_traffic_purchase(
    telegram_id: int,
    gb_amount: int,
    price_kopecks: int,
    provider: str,
    invoice_id: str | None,
) -> None:
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO traffic_purchases
            (telegram_id, gb_amount, price_kopecks, provider, invoice_id)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (invoice_id) DO NOTHING
        """,
        telegram_id,
        gb_amount,
        price_kopecks,
        provider,
        invoice_id,
    )
