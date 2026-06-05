"""CRUD for users."""
import asyncpg

from .core import get_pool


async def upsert_user(
    telegram_id: int, username: str | None, language: str = "ru"
) -> bool:
    """Insert the user if absent, refresh username/reachable if present.

    Returns True when a brand-new user row was created (useful for onboarding).
    """
    pool = get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO users (telegram_id, username, language, is_reachable)
        VALUES ($1, $2, $3, TRUE)
        ON CONFLICT (telegram_id) DO UPDATE
            SET username = EXCLUDED.username,
                is_reachable = TRUE
        RETURNING (xmax = 0) AS inserted
        """,
        telegram_id,
        username,
        language,
    )
    return bool(row["inserted"])


async def get_user(telegram_id: int) -> asyncpg.Record | None:
    pool = get_pool()
    return await pool.fetchrow(
        "SELECT * FROM users WHERE telegram_id = $1", telegram_id
    )


async def find_user_by_username(username: str) -> asyncpg.Record | None:
    pool = get_pool()
    return await pool.fetchrow(
        "SELECT * FROM users WHERE lower(username) = lower($1)", username.lstrip("@")
    )


async def mark_unreachable(telegram_id: int) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE users SET is_reachable = FALSE WHERE telegram_id = $1", telegram_id
    )


async def mark_reachable(telegram_id: int) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE users SET is_reachable = TRUE WHERE telegram_id = $1", telegram_id
    )


async def trial_available(telegram_id: int) -> bool:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT trial_used_at FROM users WHERE telegram_id = $1", telegram_id
    )
    return bool(row) and row["trial_used_at"] is None
