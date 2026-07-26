"""Admin web-push subscriptions + revenue-milestone bookkeeping."""
import asyncpg

from .core import get_pool


async def save_push_sub(endpoint: str, admin_id: int, p256dh: str, auth: str) -> None:
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO admin_push_subscriptions (endpoint, admin_id, p256dh, auth)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (endpoint) DO UPDATE SET
            admin_id = EXCLUDED.admin_id, p256dh = EXCLUDED.p256dh, auth = EXCLUDED.auth
        """,
        endpoint, admin_id, p256dh, auth,
    )


async def list_push_subs() -> list[asyncpg.Record]:
    pool = get_pool()
    return await pool.fetch("SELECT endpoint, p256dh, auth FROM admin_push_subscriptions")


async def delete_push_sub(endpoint: str) -> None:
    pool = get_pool()
    await pool.execute("DELETE FROM admin_push_subscriptions WHERE endpoint = $1", endpoint)


async def push_sub_count() -> int:
    pool = get_pool()
    return await pool.fetchval("SELECT COUNT(*) FROM admin_push_subscriptions")


async def revenue_kopecks_since(dt) -> int:
    """Sum of paid payments since ``dt`` (UTC) — for today's MSK revenue."""
    pool = get_pool()
    return int(await pool.fetchval(
        "SELECT COALESCE(SUM(amount_kopecks), 0) FROM payments "
        "WHERE status = 'paid' AND paid_at >= $1",
        dt,
    ))


async def claim_milestone(day_key: str, milestone: int) -> bool:
    """Atomically claim a (day, milestone). Returns True only for the first
    caller — used to fire each milestone push exactly once per MSK day."""
    pool = get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO push_milestones (day_key, milestone)
        VALUES ($1, $2)
        ON CONFLICT (day_key, milestone) DO NOTHING
        RETURNING milestone
        """,
        day_key, milestone,
    )
    return row is not None
