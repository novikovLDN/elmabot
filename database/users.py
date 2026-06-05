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


async def claim_trial(telegram_id: int, trial_expires_at) -> bool:
    """Atomically reserve the one-time trial slot.

    Returns True if this call won the slot (``trial_used_at`` was NULL), False
    if the trial was already used. On a provisioning failure the caller must
    call :func:`release_trial` to free the slot for a retry.
    """
    pool = get_pool()
    row = await pool.fetchrow(
        """
        UPDATE users
        SET trial_used_at = NOW(), trial_expires_at = $2
        WHERE telegram_id = $1 AND trial_used_at IS NULL
        RETURNING telegram_id
        """,
        telegram_id,
        trial_expires_at,
    )
    return row is not None


async def release_trial(telegram_id: int) -> None:
    """Undo a trial claim when provisioning ultimately failed."""
    pool = get_pool()
    await pool.execute(
        """
        UPDATE users
        SET trial_used_at = NULL, trial_expires_at = NULL
        WHERE telegram_id = $1
        """,
        telegram_id,
    )
