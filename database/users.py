"""CRUD for users."""
import secrets

import asyncpg

from .core import get_pool


def _new_sub_token() -> str:
    return secrets.token_urlsafe(24)


async def ensure_sub_token(telegram_id: int) -> str:
    """The user's aggregator subscription token, creating a random one on first
    use. Stable until reissued — this is what makes each /sub link unique and
    revocable per user."""
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT sub_token FROM users WHERE telegram_id = $1", telegram_id
    )
    if row and row["sub_token"]:
        return row["sub_token"]
    token = _new_sub_token()
    await pool.execute(
        "UPDATE users SET sub_token = $2 WHERE telegram_id = $1", telegram_id, token
    )
    return token


async def reissue_sub_token(telegram_id: int) -> str:
    """Rotate the user's subscription token: the old /sub link dies immediately
    and a fresh one is returned."""
    pool = get_pool()
    token = _new_sub_token()
    await pool.execute(
        "UPDATE users SET sub_token = $2 WHERE telegram_id = $1", telegram_id, token
    )
    return token


async def user_by_sub_token(token: str) -> int | None:
    """Telegram id behind a subscription token, or None if it's unknown/revoked."""
    if not token:
        return None
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT telegram_id FROM users WHERE sub_token = $1", token
    )
    return row["telegram_id"] if row else None


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


# --- Referrals -------------------------------------------------------------

async def set_referral(referred_id: int, referrer_id: int) -> bool:
    """Record that ``referred_id`` was invited by ``referrer_id``.

    Recorded once per invited user; self-invites and unknown referrers are
    rejected. The +days bonus is granted later, on the friend's first purchase.
    """
    if referred_id == referrer_id:
        return False
    pool = get_pool()
    if await pool.fetchrow("SELECT 1 FROM users WHERE telegram_id = $1", referrer_id) is None:
        return False
    row = await pool.fetchrow(
        """
        INSERT INTO referrals (referred_id, referrer_id)
        VALUES ($1, $2)
        ON CONFLICT (referred_id) DO NOTHING
        RETURNING referred_id
        """,
        referred_id,
        referrer_id,
    )
    if row is None:
        return False
    await pool.execute(
        "UPDATE users SET referred_by = $2 WHERE telegram_id = $1 AND referred_by IS NULL",
        referred_id,
        referrer_id,
    )
    return True


async def credit_referral(referred_id: int) -> int | None:
    """Mark a pending referral credited (idempotent). Returns the referrer's id
    to reward, or None if there was no pending referral."""
    pool = get_pool()
    row = await pool.fetchrow(
        """
        UPDATE referrals
        SET status = 'credited', credited_at = NOW()
        WHERE referred_id = $1 AND status = 'pending'
        RETURNING referrer_id
        """,
        referred_id,
    )
    return row["referrer_id"] if row else None


async def referral_stats(referrer_id: int) -> dict:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT COUNT(*)                                  AS invited,
               COUNT(*) FILTER (WHERE status = 'credited') AS purchased
        FROM referrals WHERE referrer_id = $1
        """,
        referrer_id,
    )
    return dict(row)


async def referral_leaderboard_count() -> int:
    """Number of users who invited at least one friend (for pagination)."""
    pool = get_pool()
    return await pool.fetchval(
        "SELECT COUNT(DISTINCT referrer_id) FROM referrals"
    )


async def referral_leaderboard(offset: int, limit: int) -> list[asyncpg.Record]:
    """One page of referrers with invited / purchased counts (biggest impact
    first), joined with their username, for the admin Referrals tab."""
    pool = get_pool()
    return await pool.fetch(
        """
        SELECT r.referrer_id,
               u.username,
               COUNT(*)                                      AS invited,
               COUNT(*) FILTER (WHERE r.status = 'credited') AS purchased
        FROM referrals r
        LEFT JOIN users u ON u.telegram_id = r.referrer_id
        GROUP BY r.referrer_id, u.username
        ORDER BY purchased DESC, invited DESC, r.referrer_id
        OFFSET $1 LIMIT $2
        """,
        offset,
        limit,
    )


# --- Personal offers / discounts ------------------------------------------

async def set_offer(telegram_id: int, code: str, pct: int, expires_at) -> None:
    pool = get_pool()
    await pool.execute(
        """
        UPDATE users
        SET offer_code = $2, offer_pct = $3, offer_expires_at = $4
        WHERE telegram_id = $1
        """,
        telegram_id,
        code,
        pct,
        expires_at,
    )


async def clear_offer(telegram_id: int) -> None:
    pool = get_pool()
    await pool.execute(
        """
        UPDATE users
        SET offer_code = NULL, offer_pct = NULL, offer_expires_at = NULL
        WHERE telegram_id = $1
        """,
        telegram_id,
    )


async def mark_trial_offer_sent(telegram_id: int) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE users SET trial_offer_sent = TRUE WHERE telegram_id = $1", telegram_id
    )


# --- Trial conversion funnel ----------------------------------------------

async def due_trial_funnel() -> list[asyncpg.Record]:
    """Trial users still in the conversion funnel: used the trial, never paid,
    no active paid/gift access, reachable, and not past the last stage."""
    pool = get_pool()
    return await pool.fetch(
        """
        SELECT u.telegram_id, u.trial_used_at, u.trial_expires_at,
               u.trial_funnel_stage
        FROM users u
        WHERE u.trial_used_at IS NOT NULL
          AND u.trial_expires_at IS NOT NULL
          AND u.is_reachable
          AND u.trial_funnel_stage < 7
          AND NOT EXISTS (
              SELECT 1 FROM payments p
              WHERE p.telegram_id = u.telegram_id AND p.status = 'paid'
          )
          AND NOT EXISTS (
              SELECT 1 FROM subscriptions s
              WHERE s.telegram_id = u.telegram_id
                AND s.status = 'active' AND s.source <> 'trial'
          )
        """
    )


async def set_trial_funnel_stage(telegram_id: int, stage: int) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE users SET trial_funnel_stage = $2 WHERE telegram_id = $1",
        telegram_id,
        stage,
    )
