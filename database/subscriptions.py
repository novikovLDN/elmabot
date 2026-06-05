"""Subscriptions, payments and the trial — the transactional heart.

The provisioning HTTP call is executed *inside* the DB transaction via a
callback so that "record the access" and "provision the VPN" either both
succeed or both roll back (docs/ARCHITECTURE.md §10.2). If the VPN API does
not answer, the ``await`` raises, the transaction rolls back, and nothing is
half-written.
"""
import logging
from datetime import datetime, timedelta
from typing import Awaitable, Callable

import asyncpg

from .core import get_pool, to_db_utc, utcnow

logger = logging.getLogger(__name__)

# provision(expires_at) -> (vpn_uuid, vpn_url)
TrialProvision = Callable[[datetime], Awaitable[tuple[str, str]]]
# provision(existing_sub | None, new_expires) -> (vpn_uuid, vpn_url)
ExtendProvision = Callable[
    [asyncpg.Record | None, datetime], Awaitable[tuple[str, str]]
]

_UPSERT_SUB = """
INSERT INTO subscriptions (
    telegram_id, vpn_uuid, vpn_url, expires_at, status, source,
    reminder_24h_sent, reminder_3h_sent, activated_at
) VALUES ($1, $2, $3, $4, 'active', $5, FALSE, FALSE, NOW())
ON CONFLICT (telegram_id) DO UPDATE SET
    vpn_uuid          = EXCLUDED.vpn_uuid,
    vpn_url           = EXCLUDED.vpn_url,
    expires_at        = EXCLUDED.expires_at,
    status            = 'active',
    source            = EXCLUDED.source,
    reminder_24h_sent = FALSE,
    reminder_3h_sent  = FALSE,
    activated_at      = NOW()
RETURNING *
"""


async def get_subscription(telegram_id: int) -> asyncpg.Record | None:
    pool = get_pool()
    return await pool.fetchrow(
        "SELECT * FROM subscriptions WHERE telegram_id = $1", telegram_id
    )


async def activate_trial(
    telegram_id: int, trial_days: int, provision: TrialProvision
) -> asyncpg.Record | None:
    """Atomically grant the one-time trial.

    Returns the subscription row, or ``None`` if the trial was already used.
    Raises if VPN provisioning fails (transaction rolls back — the user can
    retry, ``trial_used_at`` stays NULL).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            user = await conn.fetchrow(
                "SELECT trial_used_at FROM users WHERE telegram_id = $1 FOR UPDATE",
                telegram_id,
            )
            if user is None:
                raise ValueError(f"user {telegram_id} not found")
            if user["trial_used_at"] is not None:
                return None

            expires_at = utcnow() + timedelta(days=trial_days)
            vpn_uuid, vpn_url = await provision(expires_at)

            await conn.execute(
                """
                UPDATE users
                SET trial_used_at = NOW(), trial_expires_at = $1
                WHERE telegram_id = $2
                """,
                expires_at,
                telegram_id,
            )
            return await conn.fetchrow(
                _UPSERT_SUB, telegram_id, vpn_uuid, vpn_url, expires_at, "trial"
            )


async def grant_days(
    telegram_id: int,
    days: int,
    source: str,
    provision: ExtendProvision,
    *,
    invoice_id: str | None = None,
    amount: int | None = None,
) -> asyncpg.Record:
    """Extend (or create) a subscription by ``days``, optionally journaling a
    payment in the same transaction.

    Expiry uses ``GREATEST(expires_at, NOW()) + interval`` so paying while the
    subscription is still active never burns the remaining time (§5.4).

    Idempotent on ``invoice_id``: if that invoice was already marked paid the
    function is a no-op and returns the current subscription.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if invoice_id is not None:
                marked = await conn.fetchrow(
                    """
                    UPDATE payments
                    SET status = 'paid', paid_at = NOW()
                    WHERE invoice_id = $1 AND status <> 'paid'
                    RETURNING id
                    """,
                    invoice_id,
                )
                if marked is None:
                    # Either unknown invoice, or already processed.
                    existing_pay = await conn.fetchrow(
                        "SELECT status FROM payments WHERE invoice_id = $1", invoice_id
                    )
                    if existing_pay is not None and existing_pay["status"] == "paid":
                        logger.info("Invoice %s already processed; skipping", invoice_id)
                        return await conn.fetchrow(
                            "SELECT * FROM subscriptions WHERE telegram_id = $1",
                            telegram_id,
                        )
                    # No pending row — create one already-paid (e.g. admin path).
                    await conn.execute(
                        """
                        INSERT INTO payments (telegram_id, invoice_id, amount_kopecks,
                                              status, paid_at)
                        VALUES ($1, $2, $3, 'paid', NOW())
                        ON CONFLICT (invoice_id) DO NOTHING
                        """,
                        telegram_id,
                        invoice_id,
                        amount or 0,
                    )

            sub = await conn.fetchrow(
                "SELECT * FROM subscriptions WHERE telegram_id = $1 FOR UPDATE",
                telegram_id,
            )
            base = utcnow()
            if sub is not None and sub["expires_at"] is not None:
                base = max(base, sub["expires_at"])
            new_expires = base + timedelta(days=days)

            vpn_uuid, vpn_url = await provision(sub, new_expires)
            return await conn.fetchrow(
                _UPSERT_SUB, telegram_id, vpn_uuid, vpn_url, new_expires, source
            )


async def create_pending_payment(
    telegram_id: int, invoice_id: str, amount: int
) -> None:
    """Journal a payment as 'pending' at invoice-creation time (§5.3)."""
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO payments (telegram_id, invoice_id, amount_kopecks, status)
        VALUES ($1, $2, $3, 'pending')
        ON CONFLICT (invoice_id) DO NOTHING
        """,
        telegram_id,
        invoice_id,
        amount,
    )


async def mark_payment_refunded(invoice_id: str) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE payments SET status = 'refunded' WHERE invoice_id = $1", invoice_id
    )


async def revoke_subscription(telegram_id: int) -> asyncpg.Record | None:
    """Mark a subscription expired (admin revoke / cleanup). Returns the row so
    the caller can delete the panel user by uuid."""
    pool = get_pool()
    return await pool.fetchrow(
        """
        UPDATE subscriptions SET status = 'expired'
        WHERE telegram_id = $1
        RETURNING *
        """,
        telegram_id,
    )


# --- Scheduler queries -----------------------------------------------------

_REMINDER_COLUMNS = {
    "reminder_24h_sent": "24 hours",
    "reminder_3h_sent": "3 hours",
}


async def due_reminders(flag_column: str) -> list[asyncpg.Record]:
    if flag_column not in _REMINDER_COLUMNS:
        raise ValueError(f"unknown reminder column {flag_column!r}")
    window = _REMINDER_COLUMNS[flag_column]
    pool = get_pool()
    return await pool.fetch(
        f"""
        SELECT telegram_id, expires_at
        FROM subscriptions
        WHERE status = 'active'
          AND expires_at BETWEEN NOW() AND NOW() + INTERVAL '{window}'
          AND NOT {flag_column}
        """
    )


async def mark_reminder_sent(telegram_id: int, flag_column: str) -> None:
    if flag_column not in _REMINDER_COLUMNS:
        raise ValueError(f"unknown reminder column {flag_column!r}")
    pool = get_pool()
    await pool.execute(
        f"UPDATE subscriptions SET {flag_column} = TRUE WHERE telegram_id = $1",
        telegram_id,
    )


async def expired_active() -> list[asyncpg.Record]:
    pool = get_pool()
    return await pool.fetch(
        """
        SELECT telegram_id, vpn_uuid
        FROM subscriptions
        WHERE status = 'active' AND expires_at < NOW()
        """
    )


async def mark_expired(telegram_id: int) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE subscriptions SET status = 'expired' WHERE telegram_id = $1",
        telegram_id,
    )


# --- Admin / stats ---------------------------------------------------------

async def stats() -> dict:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT
            (SELECT COUNT(*) FROM users)                                    AS users_total,
            (SELECT COUNT(*) FROM users WHERE is_reachable)                 AS users_reachable,
            (SELECT COUNT(*) FROM users WHERE trial_used_at IS NOT NULL)    AS trials_used,
            (SELECT COUNT(*) FROM subscriptions WHERE status = 'active')    AS subs_active,
            (SELECT COUNT(*) FROM payments WHERE status = 'paid')           AS payments_paid,
            (SELECT COALESCE(SUM(amount_kopecks), 0) FROM payments
                 WHERE status = 'paid')                                     AS revenue_total
        """
    )
    return dict(row)


async def payment_history(telegram_id: int, limit: int = 10) -> list[asyncpg.Record]:
    pool = get_pool()
    return await pool.fetch(
        """
        SELECT invoice_id, amount_kopecks, status, created_at, paid_at
        FROM payments
        WHERE telegram_id = $1
        ORDER BY created_at DESC
        LIMIT $2
        """,
        telegram_id,
        limit,
    )


# --- Broadcast segments ----------------------------------------------------

async def recipients(segment: str) -> list[int]:
    """Return reachable telegram_ids for a broadcast segment."""
    pool = get_pool()
    if segment == "all":
        rows = await pool.fetch(
            "SELECT telegram_id FROM users WHERE is_reachable"
        )
    elif segment == "active":
        rows = await pool.fetch(
            """
            SELECT u.telegram_id FROM users u
            JOIN subscriptions s ON s.telegram_id = u.telegram_id
            WHERE u.is_reachable AND s.status = 'active'
            """
        )
    elif segment == "no_sub":
        rows = await pool.fetch(
            """
            SELECT u.telegram_id FROM users u
            LEFT JOIN subscriptions s ON s.telegram_id = u.telegram_id
            WHERE u.is_reachable AND (s.telegram_id IS NULL OR s.status <> 'active')
            """
        )
    else:
        raise ValueError(f"unknown segment {segment!r}")
    return [r["telegram_id"] for r in rows]
