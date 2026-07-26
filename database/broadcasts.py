"""Broadcast history + scheduled/recurring broadcasts storage.

Every send is journaled in ``broadcast_history`` (so the dashboard can list the
last N and re-send any). ``scheduled_broadcasts`` holds future/recurring sends;
the scheduler loop fires the ones whose ``run_at`` (UTC) is due and re-arms them.
"""
import asyncpg

from .core import get_pool


# --- History ---------------------------------------------------------------

async def record_broadcast(
    *,
    admin_id: int | None,
    segment: str,
    text: str,
    photo_file_id: str | None,
    button_text: str | None,
    button_url: str | None,
    total: int,
    source: str = "manual",
) -> int:
    """Journal a broadcast at start (status 'running'); returns its id."""
    pool = get_pool()
    return await pool.fetchval(
        """
        INSERT INTO broadcast_history
            (admin_id, segment, text, photo_file_id, button_text, button_url,
             source, status, total)
        VALUES ($1, $2, $3, $4, $5, $6, $7, 'running', $8)
        RETURNING id
        """,
        admin_id, segment, text, photo_file_id, button_text, button_url,
        source, total,
    )


async def finish_broadcast(
    broadcast_id: int, *, sent: int, blocked: int, failed: int
) -> None:
    pool = get_pool()
    await pool.execute(
        """
        UPDATE broadcast_history
        SET status = 'done', sent = $2, blocked = $3, failed = $4,
            finished_at = NOW()
        WHERE id = $1
        """,
        broadcast_id, sent, blocked, failed,
    )


async def list_broadcasts(limit: int = 500) -> list[asyncpg.Record]:
    pool = get_pool()
    return await pool.fetch(
        """
        SELECT id, admin_id, segment, text, photo_file_id, button_text,
               button_url, source, status, total, sent, blocked, failed,
               created_at, finished_at
        FROM broadcast_history
        ORDER BY created_at DESC
        LIMIT $1
        """,
        max(1, min(int(limit), 500)),
    )


async def get_broadcast(broadcast_id: int) -> asyncpg.Record | None:
    pool = get_pool()
    return await pool.fetchrow(
        "SELECT * FROM broadcast_history WHERE id = $1", broadcast_id
    )


# --- Scheduled / recurring -------------------------------------------------

async def create_scheduled(
    *,
    admin_id: int | None,
    segment: str,
    text: str,
    photo_file_id: str | None,
    button_text: str | None,
    button_url: str | None,
    kind: str,
    run_at,
    time_msk: str | None,
    weekdays: str | None,
) -> asyncpg.Record:
    pool = get_pool()
    return await pool.fetchrow(
        """
        INSERT INTO scheduled_broadcasts
            (admin_id, segment, text, photo_file_id, button_text, button_url,
             kind, run_at, time_msk, weekdays)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        RETURNING *
        """,
        admin_id, segment, text, photo_file_id, button_text, button_url,
        kind, run_at, time_msk, weekdays,
    )


async def list_scheduled() -> list[asyncpg.Record]:
    pool = get_pool()
    return await pool.fetch(
        "SELECT * FROM scheduled_broadcasts ORDER BY active DESC, run_at ASC"
    )


async def get_scheduled(scheduled_id: int) -> asyncpg.Record | None:
    pool = get_pool()
    return await pool.fetchrow(
        "SELECT * FROM scheduled_broadcasts WHERE id = $1", scheduled_id
    )


async def delete_scheduled(scheduled_id: int) -> None:
    pool = get_pool()
    await pool.execute("DELETE FROM scheduled_broadcasts WHERE id = $1", scheduled_id)


async def set_scheduled_active(scheduled_id: int, active: bool) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE scheduled_broadcasts SET active = $2 WHERE id = $1",
        scheduled_id, active,
    )


async def set_scheduled_run_at(scheduled_id: int, run_at) -> None:
    """Move the next fire time without touching run counters (used on resume)."""
    pool = get_pool()
    await pool.execute(
        "UPDATE scheduled_broadcasts SET run_at = $2 WHERE id = $1",
        scheduled_id, run_at,
    )


async def due_scheduled() -> list[asyncpg.Record]:
    """Active scheduled broadcasts whose next fire time has passed."""
    pool = get_pool()
    return await pool.fetch(
        "SELECT * FROM scheduled_broadcasts WHERE active AND run_at <= NOW() "
        "ORDER BY run_at ASC"
    )


async def advance_scheduled(scheduled_id: int, next_run_at) -> None:
    """After a fire: bump counters and either re-arm (next_run_at) or, for a
    one-off (next_run_at is None), deactivate it."""
    pool = get_pool()
    if next_run_at is None:
        await pool.execute(
            """
            UPDATE scheduled_broadcasts
            SET active = FALSE, last_run_at = NOW(), run_count = run_count + 1
            WHERE id = $1
            """,
            scheduled_id,
        )
    else:
        await pool.execute(
            """
            UPDATE scheduled_broadcasts
            SET run_at = $2, last_run_at = NOW(), run_count = run_count + 1
            WHERE id = $1
            """,
            scheduled_id, next_run_at,
        )
