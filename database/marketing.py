"""Marketing stats-links — acquisition attribution + funnel metrics."""
import asyncpg

from .core import get_pool


async def create_stat_link(slug: str, name: str, created_by: int | None) -> asyncpg.Record:
    pool = get_pool()
    return await pool.fetchrow(
        "INSERT INTO stats_links (slug, name, created_by) VALUES ($1, $2, $3) RETURNING *",
        slug, name, created_by,
    )


async def list_stat_links() -> list[asyncpg.Record]:
    pool = get_pool()
    return await pool.fetch("SELECT * FROM stats_links ORDER BY created_at DESC")


async def get_stat_link_by_slug(slug: str) -> asyncpg.Record | None:
    pool = get_pool()
    return await pool.fetchrow("SELECT * FROM stats_links WHERE slug = $1", slug)


async def set_stat_link_active(link_id: int, active: bool) -> None:
    pool = get_pool()
    await pool.execute("UPDATE stats_links SET active = $2 WHERE id = $1", link_id, active)


async def delete_stat_link(link_id: int) -> None:
    pool = get_pool()
    await pool.execute("DELETE FROM stats_links WHERE id = $1", link_id)


async def bump_stat_link_click(slug: str) -> int | None:
    """Count a click; returns the link id if active, else None (missing/inactive)."""
    pool = get_pool()
    return await pool.fetchval(
        "UPDATE stats_links SET clicks = clicks + 1 "
        "WHERE slug = $1 AND active RETURNING id",
        slug,
    )


async def attribute_user(telegram_id: int, link_id: int) -> None:
    """Stamp acquisition source — only if not already set (immutable)."""
    pool = get_pool()
    await pool.execute(
        "UPDATE users SET acquired_via_stat_link_id = $2 "
        "WHERE telegram_id = $1 AND acquired_via_stat_link_id IS NULL",
        telegram_id, link_id,
    )


async def stat_link_funnel(link_id: int) -> dict:
    """Signup → trial → paid → revenue for one link."""
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT
            COUNT(*) AS new_users,
            COUNT(*) FILTER (WHERE u.trial_used_at IS NOT NULL) AS trials,
            COUNT(*) FILTER (WHERE EXISTS (
                SELECT 1 FROM payments p
                WHERE p.telegram_id = u.telegram_id AND p.status = 'paid')) AS paid,
            COALESCE((
                SELECT SUM(p.amount_kopecks) FROM payments p
                JOIN users uu ON uu.telegram_id = p.telegram_id
                WHERE p.status = 'paid' AND uu.acquired_via_stat_link_id = $1
            ), 0) AS revenue_kopecks
        FROM users u
        WHERE u.acquired_via_stat_link_id = $1
        """,
        link_id,
    )
    return dict(row)
