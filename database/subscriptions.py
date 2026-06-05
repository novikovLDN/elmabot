"""Subscriptions and payments — the persistence layer.

Provisioning is orchestrated by ``app.services.subscription_service``: it calls
the Remnawave panel *first* and then writes the result here via
``upsert_subscription``. The panel is the source of truth for the VPN entity;
the DB mirrors it. If a panel call fails the service raises and nothing is
written, so a half-finished run is recoverable (find-by-username adopts the
panel record on the next attempt — docs/ARCHITECTURE.md §10.2).
"""
import logging
from datetime import datetime

import asyncpg

from .core import get_pool

logger = logging.getLogger(__name__)

_UPSERT_SUB = """
INSERT INTO subscriptions (
    telegram_id, panel_uuid, vless_uuid, subscription_url, expires_at,
    status, source, reminder_24h_sent, reminder_3h_sent, activated_at
) VALUES ($1, $2, $3, $4, $5, 'active', $6, FALSE, FALSE, NOW())
ON CONFLICT (telegram_id) DO UPDATE SET
    panel_uuid        = EXCLUDED.panel_uuid,
    vless_uuid        = EXCLUDED.vless_uuid,
    subscription_url  = EXCLUDED.subscription_url,
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


async def upsert_subscription(
    telegram_id: int,
    *,
    panel_uuid: str | None,
    vless_uuid: str | None,
    subscription_url: str | None,
    expires_at: datetime,
    source: str,
) -> asyncpg.Record:
    """Mirror a provisioned panel entity into the DB and mark it active."""
    pool = get_pool()
    return await pool.fetchrow(
        _UPSERT_SUB,
        telegram_id,
        panel_uuid,
        vless_uuid,
        subscription_url,
        expires_at,
        source,
    )


async def clear_panel_uuid(telegram_id: int) -> None:
    """Forget a stale panel uuid (the panel returned 404 on PATCH)."""
    pool = get_pool()
    await pool.execute(
        "UPDATE subscriptions SET panel_uuid = NULL WHERE telegram_id = $1",
        telegram_id,
    )


# --- Payments --------------------------------------------------------------

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


async def is_payment_paid(invoice_id: str) -> bool:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT 1 FROM payments WHERE invoice_id = $1 AND status = 'paid'", invoice_id
    )
    return row is not None


async def mark_payment_paid(
    telegram_id: int, invoice_id: str, amount: int | None = None
) -> None:
    """Mark a payment paid *after* provisioning succeeded (§10.1).

    Upserts so the admin path (no pre-journaled pending row) also works.
    """
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO payments (telegram_id, invoice_id, amount_kopecks, status, paid_at)
        VALUES ($1, $2, $3, 'paid', NOW())
        ON CONFLICT (invoice_id) DO UPDATE SET status = 'paid', paid_at = NOW()
        """,
        telegram_id,
        invoice_id,
        amount or 0,
    )


async def mark_payment_refunded(invoice_id: str) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE payments SET status = 'refunded' WHERE invoice_id = $1", invoice_id
    )


async def revoke_subscription(telegram_id: int) -> asyncpg.Record | None:
    """Mark a subscription expired (admin revoke / cleanup). Returns the row so
    the caller can delete the panel user by ``panel_uuid``."""
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
        SELECT telegram_id, panel_uuid
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
