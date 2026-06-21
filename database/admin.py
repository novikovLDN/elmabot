"""Database helpers for the admin web dashboard.

Auth (password + magic-link + WebAuthn credentials), the audit log, user
search/detail and the time-series used by the charts. Every datetime column is
TIMESTAMPTZ (aware UTC), so plain ``now()`` comparisons are correct; we only
convert with ``AT TIME ZONE`` when bucketing into UTC days / Moscow hours.
"""
import secrets
from datetime import timedelta
from typing import Any

import asyncpg

from .core import get_pool, utcnow

# --- Admin auth -----------------------------------------------------------


async def get_admin_password_hash(telegram_id: int) -> str | None:
    pool = get_pool()
    return await pool.fetchval(
        "SELECT password_hash FROM admin_auth WHERE telegram_id = $1", telegram_id
    )


async def set_admin_password(telegram_id: int, password_hash: str) -> None:
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO admin_auth (telegram_id, password_hash, updated_at)
        VALUES ($1, $2, NOW())
        ON CONFLICT (telegram_id)
        DO UPDATE SET password_hash = EXCLUDED.password_hash, updated_at = NOW()
        """,
        telegram_id,
        password_hash,
    )


async def create_login_token(
    telegram_id: int, purpose: str = "setup", ttl_seconds: int = 900
) -> str:
    """Issue a one-time magic-link token (default 15 min)."""
    token = secrets.token_urlsafe(32)
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO admin_login_tokens (token, telegram_id, purpose, expires_at)
        VALUES ($1, $2, $3, $4)
        """,
        token,
        telegram_id,
        purpose,
        utcnow() + timedelta(seconds=ttl_seconds),
    )
    return token


async def peek_login_token(token: str) -> asyncpg.Record | None:
    """Validate a token without consuming it (for the setup page load)."""
    pool = get_pool()
    return await pool.fetchrow(
        """
        SELECT token, telegram_id, purpose
        FROM admin_login_tokens
        WHERE token = $1 AND used_at IS NULL AND expires_at > NOW()
        """,
        token,
    )


async def consume_login_token(token: str) -> asyncpg.Record | None:
    """Atomically mark a valid token used and return it, or None if invalid."""
    pool = get_pool()
    return await pool.fetchrow(
        """
        UPDATE admin_login_tokens
        SET used_at = NOW()
        WHERE token = $1 AND used_at IS NULL AND expires_at > NOW()
        RETURNING token, telegram_id, purpose
        """,
        token,
    )


# --- Audit log ------------------------------------------------------------


async def log_audit(
    admin_id: int, action: str, target_id: int | None = None, detail: str | None = None
) -> None:
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO audit_log (admin_id, action, target_id, detail)
        VALUES ($1, $2, $3, $4)
        """,
        admin_id,
        action,
        target_id,
        detail,
    )


async def audit_count() -> int:
    pool = get_pool()
    return await pool.fetchval("SELECT COUNT(*) FROM audit_log")


async def audit_page(offset: int, limit: int) -> list[asyncpg.Record]:
    pool = get_pool()
    return await pool.fetch(
        """
        SELECT a.id, a.admin_id, a.action, a.target_id, a.detail, a.created_at,
               u.username AS target_username
        FROM audit_log a
        LEFT JOIN users u ON u.telegram_id = a.target_id
        ORDER BY a.created_at DESC
        OFFSET $1 LIMIT $2
        """,
        offset,
        limit,
    )


# --- Users (search + detail) ---------------------------------------------


async def users_count(q: str = "") -> int:
    pool = get_pool()
    return await pool.fetchval(
        """
        SELECT COUNT(*) FROM users u
        WHERE ($1 = ''
               OR u.username ILIKE '%' || $1 || '%'
               OR CAST(u.telegram_id AS TEXT) LIKE '%' || $1 || '%')
        """,
        q,
    )


async def users_search(q: str, offset: int, limit: int) -> list[asyncpg.Record]:
    pool = get_pool()
    return await pool.fetch(
        """
        SELECT u.telegram_id, u.username, u.created_at, u.is_reachable,
               u.trial_used_at, u.referred_by,
               s.status AS sub_status, s.source AS sub_source, s.expires_at,
               (SELECT COUNT(*) FROM payments p
                WHERE p.telegram_id = u.telegram_id AND p.status = 'paid')
                   AS payments_paid
        FROM users u
        LEFT JOIN subscriptions s ON s.telegram_id = u.telegram_id
        WHERE ($1 = ''
               OR u.username ILIKE '%' || $1 || '%'
               OR CAST(u.telegram_id AS TEXT) LIKE '%' || $1 || '%')
        ORDER BY u.created_at DESC
        OFFSET $2 LIMIT $3
        """,
        q,
        offset,
        limit,
    )


async def user_detail(telegram_id: int) -> dict[str, Any] | None:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT u.telegram_id, u.username, u.language, u.created_at, u.is_reachable,
               u.trial_used_at, u.trial_expires_at, u.referred_by,
               u.offer_code, u.offer_pct, u.offer_expires_at,
               s.status AS sub_status, s.source AS sub_source, s.expires_at,
               s.subscription_url, s.panel_uuid, s.created_at AS sub_created_at,
               (SELECT COUNT(*) FROM payments p
                WHERE p.telegram_id = u.telegram_id AND p.status = 'paid')
                   AS payments_paid,
               (SELECT COALESCE(SUM(amount_kopecks), 0) FROM payments p
                WHERE p.telegram_id = u.telegram_id AND p.status = 'paid')
                   AS spent_kopecks,
               (SELECT COUNT(*) FROM referrals r
                WHERE r.referrer_id = u.telegram_id) AS invited,
               (SELECT COUNT(*) FROM referrals r
                WHERE r.referrer_id = u.telegram_id AND r.status = 'credited')
                   AS invited_credited
        FROM users u
        LEFT JOIN subscriptions s ON s.telegram_id = u.telegram_id
        WHERE u.telegram_id = $1
        """,
        telegram_id,
    )
    return dict(row) if row else None


# --- Subscription health (dashboard) -------------------------------------


async def subscription_health() -> dict[str, Any]:
    """Active/trial/paid counts, lifetime and renewal/conversion metrics."""
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT
            (SELECT COUNT(*) FROM subscriptions WHERE status = 'active')
                AS active_total,
            (SELECT COUNT(*) FROM subscriptions
                 WHERE status = 'active' AND source = 'trial')   AS active_trial,
            (SELECT COUNT(*) FROM subscriptions
                 WHERE status = 'active' AND source <> 'trial')  AS active_paid,
            (SELECT COUNT(DISTINCT telegram_id) FROM payments
                 WHERE status = 'paid')                          AS paying_users,
            (SELECT COUNT(*) FROM payments WHERE status = 'paid') AS payments_paid,
            (SELECT COUNT(*) FROM users WHERE trial_used_at IS NOT NULL)
                AS trials_used,
            (SELECT COUNT(*) FROM users) AS users_total
        """
    )
    return dict(row)


# --- Time-series (charts) -------------------------------------------------


async def daily_timeseries(days: int = 30) -> list[asyncpg.Record]:
    """One row per UTC day for the last ``days``: revenue (kopecks), payments,
    new users, new subscriptions and new paid subscriptions."""
    pool = get_pool()
    return await pool.fetch(
        """
        WITH spine AS (
            SELECT generate_series(
                date_trunc('day', (NOW() AT TIME ZONE 'UTC')) - ($1 - 1) * interval '1 day',
                date_trunc('day', (NOW() AT TIME ZONE 'UTC')),
                interval '1 day'
            )::date AS day
        ),
        pay AS (
            SELECT (paid_at AT TIME ZONE 'UTC')::date AS day,
                   SUM(amount_kopecks) AS revenue, COUNT(*) AS payments
            FROM payments
            WHERE status = 'paid' AND paid_at >= NOW() - $1 * interval '1 day'
            GROUP BY 1
        ),
        usr AS (
            SELECT (created_at AT TIME ZONE 'UTC')::date AS day, COUNT(*) AS new_users
            FROM users WHERE created_at >= NOW() - $1 * interval '1 day' GROUP BY 1
        ),
        sub AS (
            SELECT (created_at AT TIME ZONE 'UTC')::date AS day,
                   COUNT(*) AS new_subs,
                   COUNT(*) FILTER (WHERE source <> 'trial') AS new_paid_subs
            FROM subscriptions
            WHERE created_at >= NOW() - $1 * interval '1 day' GROUP BY 1
        )
        SELECT spine.day,
               COALESCE(pay.revenue, 0)        AS revenue,
               COALESCE(pay.payments, 0)       AS payments,
               COALESCE(usr.new_users, 0)      AS new_users,
               COALESCE(sub.new_subs, 0)       AS new_subs,
               COALESCE(sub.new_paid_subs, 0)  AS new_paid_subs
        FROM spine
        LEFT JOIN pay ON pay.day = spine.day
        LEFT JOIN usr ON usr.day = spine.day
        LEFT JOIN sub ON sub.day = spine.day
        ORDER BY spine.day
        """,
        days,
    )


async def hourly_timeseries(days: int = 7) -> list[asyncpg.Record]:
    """24 rows by hour-of-day (Europe/Moscow) over the last ``days``."""
    pool = get_pool()
    return await pool.fetch(
        """
        WITH spine AS (SELECT generate_series(0, 23) AS hour),
        pay AS (
            SELECT EXTRACT(HOUR FROM (paid_at AT TIME ZONE 'Europe/Moscow'))::int AS hour,
                   SUM(amount_kopecks) AS revenue, COUNT(*) AS payments
            FROM payments
            WHERE status = 'paid' AND paid_at >= NOW() - $1 * interval '1 day'
            GROUP BY 1
        ),
        usr AS (
            SELECT EXTRACT(HOUR FROM (created_at AT TIME ZONE 'Europe/Moscow'))::int AS hour,
                   COUNT(*) AS new_users
            FROM users WHERE created_at >= NOW() - $1 * interval '1 day' GROUP BY 1
        ),
        sub AS (
            SELECT EXTRACT(HOUR FROM (created_at AT TIME ZONE 'Europe/Moscow'))::int AS hour,
                   COUNT(*) AS new_subs,
                   COUNT(*) FILTER (WHERE source <> 'trial') AS new_paid_subs
            FROM subscriptions
            WHERE created_at >= NOW() - $1 * interval '1 day' GROUP BY 1
        )
        SELECT spine.hour,
               COALESCE(pay.revenue, 0)       AS revenue,
               COALESCE(pay.payments, 0)      AS payments,
               COALESCE(usr.new_users, 0)     AS new_users,
               COALESCE(sub.new_subs, 0)      AS new_subs,
               COALESCE(sub.new_paid_subs, 0) AS new_paid_subs
        FROM spine
        LEFT JOIN pay ON pay.hour = spine.hour
        LEFT JOIN usr ON usr.hour = spine.hour
        LEFT JOIN sub ON sub.hour = spine.hour
        ORDER BY spine.hour
        """,
        days,
    )


async def revenue_by_provider(hours: int = 24 * 30) -> list[asyncpg.Record]:
    pool = get_pool()
    return await pool.fetch(
        """
        SELECT provider,
               COUNT(*) AS payments,
               COALESCE(SUM(amount_kopecks), 0) AS revenue
        FROM payments
        WHERE status = 'paid' AND paid_at >= NOW() - $1 * interval '1 hour'
        GROUP BY provider
        ORDER BY revenue DESC
        """,
        hours,
    )


async def purchase_breakdown(hours: int = 24 * 30) -> list[asyncpg.Record]:
    """Paid purchases split by tariff_code over a window."""
    pool = get_pool()
    return await pool.fetch(
        """
        SELECT COALESCE(tariff_code, '—') AS tariff_code,
               COUNT(*) AS payments,
               COALESCE(SUM(amount_kopecks), 0) AS revenue
        FROM payments
        WHERE status = 'paid' AND paid_at >= NOW() - $1 * interval '1 hour'
        GROUP BY 1
        ORDER BY revenue DESC
        """,
        hours,
    )


# --- Referrals & gifts (dashboard) ---------------------------------------


async def referrals_overview() -> dict[str, Any]:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT
            (SELECT COUNT(*) FROM referrals)                          AS total,
            (SELECT COUNT(*) FROM referrals WHERE status = 'credited') AS credited,
            (SELECT COUNT(DISTINCT referrer_id) FROM referrals)       AS referrers
        """
    )
    return dict(row)


async def gifts_count() -> int:
    pool = get_pool()
    return await pool.fetchval("SELECT COUNT(*) FROM gifts")


async def gifts_page(offset: int, limit: int) -> list[asyncpg.Record]:
    pool = get_pool()
    return await pool.fetch(
        """
        SELECT g.code, g.tariff_code, g.status, g.created_by, g.redeemed_by,
               g.created_at, g.redeemed_at,
               cu.username AS created_by_username,
               ru.username AS redeemed_by_username
        FROM gifts g
        LEFT JOIN users cu ON cu.telegram_id = g.created_by
        LEFT JOIN users ru ON ru.telegram_id = g.redeemed_by
        ORDER BY g.created_at DESC
        OFFSET $1 LIMIT $2
        """,
        offset,
        limit,
    )


# --- WebAuthn / Passkey ---------------------------------------------------


async def webauthn_list(telegram_id: int) -> list[asyncpg.Record]:
    pool = get_pool()
    return await pool.fetch(
        """
        SELECT credential_id, label, created_at, last_used_at
        FROM webauthn_credentials WHERE telegram_id = $1
        ORDER BY created_at DESC
        """,
        telegram_id,
    )


async def webauthn_get(credential_id: str) -> asyncpg.Record | None:
    pool = get_pool()
    return await pool.fetchrow(
        "SELECT * FROM webauthn_credentials WHERE credential_id = $1", credential_id
    )


async def webauthn_add(
    telegram_id: int, credential_id: str, public_key: str,
    sign_count: int, label: str | None = None,
) -> None:
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO webauthn_credentials
            (credential_id, telegram_id, public_key, sign_count, label)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (credential_id) DO NOTHING
        """,
        credential_id,
        telegram_id,
        public_key,
        sign_count,
        label,
    )


async def webauthn_touch(credential_id: str, sign_count: int) -> None:
    pool = get_pool()
    await pool.execute(
        """
        UPDATE webauthn_credentials
        SET sign_count = $2, last_used_at = NOW()
        WHERE credential_id = $1
        """,
        credential_id,
        sign_count,
    )


async def webauthn_delete(telegram_id: int, credential_id: str) -> bool:
    pool = get_pool()
    res = await pool.execute(
        "DELETE FROM webauthn_credentials WHERE telegram_id = $1 AND credential_id = $2",
        telegram_id,
        credential_id,
    )
    return res.endswith(" 1")
