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
    status, source, reminder_24h_sent, reminder_3h_sent, reminder_1h_sent,
    activated_at
) VALUES ($1, $2, $3, $4, $5, 'active', $6, FALSE, FALSE, FALSE, NOW())
ON CONFLICT (telegram_id) DO UPDATE SET
    panel_uuid        = EXCLUDED.panel_uuid,
    vless_uuid        = EXCLUDED.vless_uuid,
    subscription_url  = EXCLUDED.subscription_url,
    expires_at        = EXCLUDED.expires_at,
    status            = 'active',
    source            = EXCLUDED.source,
    reminder_24h_sent = FALSE,
    reminder_3h_sent  = FALSE,
    reminder_1h_sent  = FALSE,
    react_offer_sent  = FALSE,
    react_stage       = 0,
    trial_1h_sent     = FALSE,
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


async def set_panel_uuid(telegram_id: int, panel_uuid: str) -> None:
    """Store the panel identifier (3.x numeric id) — used by the backfill."""
    pool = get_pool()
    await pool.execute(
        "UPDATE subscriptions SET panel_uuid = $2 WHERE telegram_id = $1",
        telegram_id, panel_uuid,
    )


async def all_provisioned() -> list[asyncpg.Record]:
    """Every subscription with a panel entity (for the panel backfill / re-sync)."""
    pool = get_pool()
    return await pool.fetch(
        "SELECT telegram_id, panel_uuid, expires_at, status "
        "FROM subscriptions WHERE panel_uuid IS NOT NULL"
    )


# --- Payments --------------------------------------------------------------

async def create_pending_payment(
    telegram_id: int,
    invoice_id: str,
    amount: int,
    *,
    provider: str = "unknown",
    tariff_code: str | None = None,
    confirm_message_id: int | None = None,
) -> None:
    """Journal a payment as 'pending' at invoice-creation time (§5.3).

    ``tariff_code`` lets an async provider callback (Platega webhook) recover
    what was bought from just the transaction id. ``confirm_message_id`` is the
    «Проверьте заказ» message to remove once the payment confirms.
    """
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO payments (telegram_id, invoice_id, amount_kopecks, status,
                              provider, tariff_code, confirm_message_id)
        VALUES ($1, $2, $3, 'pending', $4, $5, $6)
        ON CONFLICT (invoice_id) DO NOTHING
        """,
        telegram_id,
        invoice_id,
        amount,
        provider,
        tariff_code,
        confirm_message_id,
    )


async def get_payment(invoice_id: str) -> asyncpg.Record | None:
    """Full payment row by invoice id (used by the Platega webhook)."""
    pool = get_pool()
    return await pool.fetchrow(
        "SELECT * FROM payments WHERE invoice_id = $1", invoice_id
    )


async def pending_payments_recent(min_age_min: int, max_age_min: int) -> list[asyncpg.Record]:
    """Pending payments aged between min/max minutes — reconcile candidates for
    when the provider webhook was missed (the min age avoids racing the webhook)."""
    pool = get_pool()
    return await pool.fetch(
        """
        SELECT * FROM payments
        WHERE status = 'pending'
          AND created_at <= NOW() - make_interval(mins => $1)
          AND created_at >= NOW() - make_interval(mins => $2)
        ORDER BY created_at
        """,
        min_age_min,
        max_age_min,
    )


async def is_payment_paid(invoice_id: str) -> bool:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT 1 FROM payments WHERE invoice_id = $1 AND status = 'paid'", invoice_id
    )
    return row is not None


async def has_paid_payment(telegram_id: int) -> bool:
    """True if the user has ever completed a paid purchase (for first-purchase
    discounts and referral crediting)."""
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT 1 FROM payments WHERE telegram_id = $1 AND status = 'paid' LIMIT 1",
        telegram_id,
    )
    return row is not None


# --- Gifts -----------------------------------------------------------------

async def create_gift(code: str, tariff_code: str, created_by: int) -> None:
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO gifts (code, tariff_code, created_by)
        VALUES ($1, $2, $3)
        """,
        code,
        tariff_code,
        created_by,
    )


async def redeem_gift_record(code: str, redeemed_by: int) -> asyncpg.Record | None:
    """Atomically mark a gift redeemed. Returns the gift row (with tariff_code
    and created_by) on success, or None if unknown / already redeemed."""
    pool = get_pool()
    return await pool.fetchrow(
        """
        UPDATE gifts
        SET status = 'redeemed', redeemed_by = $2, redeemed_at = NOW()
        WHERE code = $1 AND status = 'pending'
        RETURNING tariff_code, created_by
        """,
        code,
        redeemed_by,
    )


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
        ON CONFLICT (invoice_id) DO UPDATE
            SET status = 'paid', paid_at = NOW(), fail_reason = NULL
        """,
        telegram_id,
        invoice_id,
        amount or 0,
    )


async def mark_payment_failed(invoice_id: str, reason: str) -> None:
    """Record a failed/cancelled payment with the reason for the admin tab."""
    pool = get_pool()
    await pool.execute(
        """
        UPDATE payments SET status = 'failed', fail_reason = $2
        WHERE invoice_id = $1 AND status <> 'paid'
        """,
        invoice_id,
        reason[:500],
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

# Columns repurposed for the approved timeline: 3 days before / day of expiry.
_REMINDER_COLUMNS = {
    "reminder_24h_sent": "3 days",
    "reminder_3h_sent": "1 day",
    "reminder_1h_sent": "1 hour",
}


async def due_reminders(flag_column: str, hours: int | None = None) -> list[asyncpg.Record]:
    if flag_column not in _REMINDER_COLUMNS:
        raise ValueError(f"unknown reminder column {flag_column!r}")
    window = f"{int(hours)} hours" if hours else _REMINDER_COLUMNS[flag_column]
    pool = get_pool()
    # Paid subscriptions only: the time-based "подписка заканчивается" reminders
    # are renewal nudges. Trials get their own −10% trial-end offer instead, and
    # a fresh 2-day trial would otherwise fall straight into the 3-day window.
    return await pool.fetch(
        f"""
        SELECT telegram_id, expires_at, source
        FROM subscriptions
        WHERE status = 'active'
          AND source <> 'trial'
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


async def due_trial_1h_reminders() -> list[asyncpg.Record]:
    """Active trial subscriptions activated 1h+ ago and not yet reminded once
    (the 'продли заранее' nudge an hour into the trial)."""
    pool = get_pool()
    return await pool.fetch(
        """
        SELECT telegram_id, expires_at
        FROM subscriptions
        WHERE status = 'active' AND source = 'trial'
          AND activated_at < NOW() - INTERVAL '1 hour'
          AND NOT trial_1h_sent
        """
    )


async def mark_trial_1h_sent(telegram_id: int) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE subscriptions SET trial_1h_sent = TRUE WHERE telegram_id = $1",
        telegram_id,
    )


async def expired_active() -> list[asyncpg.Record]:
    pool = get_pool()
    return await pool.fetch(
        """
        SELECT telegram_id, panel_uuid, source
        FROM subscriptions
        WHERE status = 'active' AND expires_at < NOW()
        """
    )


async def active_paid_for_reconcile(limit: int) -> list[asyncpg.Record]:
    """Active paid subscriptions (newest first) for the panel↔DB expiry check."""
    pool = get_pool()
    return await pool.fetch(
        """
        SELECT telegram_id, expires_at, panel_uuid
        FROM subscriptions
        WHERE status = 'active' AND source <> 'trial'
        ORDER BY expires_at DESC
        LIMIT $1
        """,
        limit,
    )


async def mark_expired(telegram_id: int) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE subscriptions SET status = 'expired' WHERE telegram_id = $1",
        telegram_id,
    )


# --- Discount-offer scheduler ---------------------------------------------

async def due_trial_end_offers() -> list[asyncpg.Record]:
    """Users whose trial has ended, never bought, with no active subscription —
    candidates for the one-day −10% first-purchase offer."""
    pool = get_pool()
    return await pool.fetch(
        """
        SELECT u.telegram_id
        FROM users u
        LEFT JOIN subscriptions s ON s.telegram_id = u.telegram_id
        WHERE u.trial_used_at IS NOT NULL
          AND u.trial_expires_at IS NOT NULL
          AND u.trial_expires_at < NOW()
          AND NOT u.trial_offer_sent
          AND u.is_reachable
          AND (s.telegram_id IS NULL OR s.status <> 'active')
          AND NOT EXISTS (
              SELECT 1 FROM payments p
              WHERE p.telegram_id = u.telegram_id AND p.status = 'paid'
          )
        """
    )


async def due_reactivation_ladder(
    min_hours: int, max_days: int = 14
) -> list[asyncpg.Record]:
    """Expired paid, reachable subs eligible for the win-back ladder: lapsed at
    least ``min_hours`` ago (the earliest ladder step) but no more than
    ``max_days`` ago, and not yet through all three steps (``react_stage`` < 3).

    The upper bound keeps a first deploy / long outage from blasting the whole
    historical backlog; ``react_stage`` guarantees each step fires at most once.
    """
    pool = get_pool()
    return await pool.fetch(
        f"""
        SELECT s.telegram_id, s.expires_at, s.react_stage
        FROM subscriptions s
        JOIN users u ON u.telegram_id = s.telegram_id
        WHERE s.status = 'expired'
          AND s.source <> 'trial'
          AND s.react_stage < 3
          AND u.is_reachable
          AND s.expires_at <  NOW() - INTERVAL '{int(min_hours)} hours'
          AND s.expires_at >= NOW() - INTERVAL '{int(max_days)} days'
        """
    )


async def set_react_stage(telegram_id: int, stage: int) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE subscriptions SET react_stage = $2 WHERE telegram_id = $1",
        telegram_id,
        int(stage),
    )


# --- Admin / stats ---------------------------------------------------------

async def stats() -> dict:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT
            (SELECT COUNT(*) FROM users)                                    AS users_total,
            (SELECT COUNT(*) FROM users
                 WHERE created_at >= date_trunc('day', now()))             AS users_today,
            (SELECT COUNT(*) FROM users WHERE is_reachable)                 AS users_reachable,
            -- any activation (trial / payment / admin) leaves a subscriptions row
            (SELECT COUNT(*) FROM subscriptions)                            AS activated_total,
            (SELECT COUNT(*) FROM users WHERE trial_used_at IS NOT NULL)    AS trials_used,
            (SELECT COUNT(DISTINCT telegram_id) FROM payments
                 WHERE status = 'paid')                                     AS buyers,
            (SELECT COUNT(*) FROM subscriptions WHERE status = 'active')    AS subs_active,
            (SELECT COUNT(*) FROM payments WHERE status = 'paid')           AS payments_paid,
            -- revenue across ALL payment providers (in kopecks)
            (SELECT COALESCE(SUM(amount_kopecks), 0) FROM payments
                 WHERE status = 'paid')                                     AS revenue_total,
            (SELECT COALESCE(SUM(amount_kopecks), 0) FROM payments
                 WHERE status = 'paid'
                   AND paid_at >= date_trunc('day', now()))                 AS revenue_today
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


async def payments_count() -> int:
    pool = get_pool()
    return await pool.fetchval("SELECT COUNT(*) FROM payments")


async def payments_page(offset: int, limit: int) -> list[asyncpg.Record]:
    """One page of payments (newest first) joined with the buyer's username, for
    the admin Payments tab."""
    pool = get_pool()
    return await pool.fetch(
        """
        SELECT p.telegram_id, u.username, p.amount_kopecks, p.provider,
               p.status, p.tariff_code, p.fail_reason, p.created_at, p.paid_at
        FROM payments p
        LEFT JOIN users u ON u.telegram_id = p.telegram_id
        ORDER BY p.created_at DESC
        OFFSET $1 LIMIT $2
        """,
        offset,
        limit,
    )


# Revenue windows shown on the dashboard: label -> day count.
REVENUE_WINDOWS: list[tuple[str, int]] = [
    ("3 дня", 3),
    ("7 дней", 7),
    ("14 дней", 14),
    ("30 дней", 30),
    ("3 месяца", 90),
    ("6 месяцев", 180),
    ("1 год", 365),
]


async def revenue_windows() -> dict:
    """Paid revenue (kopecks) and purchase counts per time window, across ALL
    providers. Amounts are true rubles ×100 (see billing: every provider stores
    the charged ruble price in ``amount_kopecks``)."""
    pool = get_pool()
    parts = []
    for _, days in REVENUE_WINDOWS:
        parts.append(
            f"COALESCE(SUM(amount_kopecks) FILTER "
            f"(WHERE paid_at >= now() - interval '{days} days'), 0) AS rev_{days}"
        )
        parts.append(
            f"COUNT(*) FILTER "
            f"(WHERE paid_at >= now() - interval '{days} days') AS cnt_{days}"
        )
    parts.append("COALESCE(SUM(amount_kopecks), 0) AS rev_total")
    parts.append("COUNT(*) AS cnt_total")
    row = await pool.fetchrow(
        f"SELECT {', '.join(parts)} FROM payments WHERE status = 'paid'"
    )
    return dict(row)


# Activity windows for the dashboard: label -> hours.
ACTIVITY_WINDOWS: list[tuple[str, int]] = [
    ("24 часа", 24),
    ("7 дней", 24 * 7),
    ("30 дней", 24 * 30),
]


async def activity_windows() -> dict:
    """New signups and trial activations per window (24h / 7d / 30d)."""
    pool = get_pool()
    parts = []
    for _, hours in ACTIVITY_WINDOWS:
        parts.append(
            f"COUNT(*) FILTER (WHERE created_at >= now() - interval '{hours} hours') "
            f"AS signup_{hours}"
        )
        parts.append(
            f"COUNT(*) FILTER (WHERE trial_used_at >= now() - interval '{hours} hours') "
            f"AS trial_{hours}"
        )
    row = await pool.fetchrow(f"SELECT {', '.join(parts)} FROM users")
    return dict(row)


# --- Broadcast segments ----------------------------------------------------

# Broadcast segments: code -> (human label, SQL WHERE over `users u`).
# All filtered to reachable users. "bought" = a paid payment exists; a paid
# purchase always leaves a subscriptions row, so "no sub at all" implies no buy.
_PAID_EXISTS = "EXISTS (SELECT 1 FROM payments p WHERE p.telegram_id = u.telegram_id AND p.status = 'paid')"
_SUB_EXISTS = "EXISTS (SELECT 1 FROM subscriptions s WHERE s.telegram_id = u.telegram_id)"
_ACTIVE_SUB = "EXISTS (SELECT 1 FROM subscriptions s WHERE s.telegram_id = u.telegram_id AND s.status = 'active')"
# Active subscription split by source: 'trial' is the free trial, anything else
# ('payment'/'admin'/'gift'/'referral') is real paid/granted access.
_ACTIVE_PAID = (
    "EXISTS (SELECT 1 FROM subscriptions s WHERE s.telegram_id = u.telegram_id "
    "AND s.status = 'active' AND s.source <> 'trial')"
)
_ACTIVE_TRIAL = (
    "EXISTS (SELECT 1 FROM subscriptions s WHERE s.telegram_id = u.telegram_id "
    "AND s.status = 'active' AND s.source = 'trial')"
)

# Curated broadcast segments — each targets a distinct, actionable audience
# (no overlaps). All implicitly filtered to reachable users in recipients().
_ACTIVE_TRIAL_ENDING_1D = (
    "EXISTS (SELECT 1 FROM subscriptions s WHERE s.telegram_id = u.telegram_id "
    "AND s.status = 'active' AND s.source = 'trial' "
    "AND s.expires_at > now() AND s.expires_at <= now() + interval '1 day')"
)


def _paid_expiring_within(days: int) -> str:
    return (
        "EXISTS (SELECT 1 FROM subscriptions s WHERE s.telegram_id = u.telegram_id "
        "AND s.status = 'active' AND s.source <> 'trial' "
        f"AND s.expires_at > now() AND s.expires_at <= now() + interval '{days} days')"
    )


def _expired_within(days: int) -> str:
    return (
        "EXISTS (SELECT 1 FROM subscriptions s WHERE s.telegram_id = u.telegram_id "
        f"AND s.status = 'expired' AND s.expires_at > now() - interval '{days} days')"
    )


def _trial_expired_within(days: int) -> str:
    return (
        f"u.trial_used_at IS NOT NULL AND NOT {_PAID_EXISTS} "
        f"AND u.trial_expires_at > now() - interval '{days} days' "
        "AND u.trial_expires_at <= now()"
    )


def _cold_since(days: int) -> str:
    return (
        f"u.trial_used_at IS NULL AND NOT {_SUB_EXISTS} "
        f"AND u.created_at <= now() - interval '{days} days'"
    )


_NO_ACTIVE = f"NOT {_ACTIVE_SUB}"
_IS_REFERRER = "EXISTS (SELECT 1 FROM referrals r WHERE r.referrer_id = u.telegram_id)"
_LOYAL_2PLUS = (
    "(SELECT COUNT(*) FROM payments p "
    "WHERE p.telegram_id = u.telegram_id AND p.status = 'paid') >= 2"
)
_NO_TRIAL = "u.trial_used_at IS NULL"
_REFERRED = "u.referred_by IS NOT NULL"
_VIA_LINK = "u.acquired_via_stat_link_id IS NOT NULL"
_ONE_TIME = (
    "(SELECT COUNT(*) FROM payments p "
    "WHERE p.telegram_id = u.telegram_id AND p.status = 'paid') = 1"
)
_BYPASS_USER = (
    "EXISTS (SELECT 1 FROM bypass_subscriptions b "
    "WHERE b.telegram_id = u.telegram_id AND b.panel_uuid IS NOT NULL)"
)


def _signup_within(days: int) -> str:
    return f"u.created_at >= now() - interval '{days} days'"


# code -> (label, SQL WHERE over `users u`, human description shown as a hint).
# All implicitly filtered to reachable users in recipients().
SEGMENTS: dict[str, tuple[str, str, str]] = {
    # --- База ---
    "all": ("Все пользователи", "TRUE",
            "Абсолютно все, кому бот может доставить сообщение."),
    "active": ("✅ Активная подписка (все)", _ACTIVE_SUB,
               "У кого сейчас есть активный доступ — платный или триал."),
    "active_paid": ("💳 Платная активная", _ACTIVE_PAID,
                    "Активная ПЛАТНАЯ подписка (без триалов)."),
    "active_trial": ("🆓 Триал активный", _ACTIVE_TRIAL,
                     "Сейчас на бесплатном пробном периоде."),
    "paid_ever": ("💎 Покупали хоть раз", _PAID_EXISTS,
                  "Хоть раз оплачивали — тёплая база для апселла."),
    "no_sub": ("🚫 Без активной подписки", _NO_ACTIVE,
               "Сейчас нет активного доступа (были клиентами или нет)."),
    # --- Онбординг (новые) ---
    "signup_1d": ("🆕 Новые за 24ч", _signup_within(1),
                  "Зарегистрировались за последние сутки."),
    "signup_7d": ("🆕 Новые за 7 дней", _signup_within(7),
                  "Зарегистрировались за последнюю неделю."),
    "signup_30d": ("🆕 Новые за 30 дней", _signup_within(30),
                   "Зарегистрировались за последний месяц."),
    "no_trial": ("🎁 Не брали пробный", _NO_TRIAL,
                 "Ещё ни разу не активировали пробный период — предложить триал."),
    # --- Триал-воронка (конверсия) ---
    "trial_ending_1d": ("⏳ Триал кончается ≤24ч", _ACTIVE_TRIAL_ENDING_1D,
                        "Триал закончится в ближайшие 24 часа — момент для оффера."),
    "trial_no_buy": ("Триал без покупки",
                     f"u.trial_used_at IS NOT NULL AND NOT {_PAID_EXISTS}",
                     "Брали триал, но так и не купили."),
    "trial_expired_recent": (
        "Триал истёк ≤3 дн, без покупки",
        f"u.trial_used_at IS NOT NULL AND NOT {_PAID_EXISTS} "
        "AND u.trial_expires_at > now() - interval '3 days' "
        "AND u.trial_expires_at <= now()",
        "Триал закончился ≤3 дней назад, покупки не было — горячий момент."),
    "trial_expired_7d": ("Триал истёк ≤7 дн, без покупки", _trial_expired_within(7),
                         "Триал закончился ≤7 дней назад, без покупки."),
    "trial_expired_30d": ("Триал истёк ≤30 дн, без покупки", _trial_expired_within(30),
                          "Триал закончился ≤30 дней назад, без покупки."),
    "cold": ("❄️ Холодные (без триала и покупок)",
             f"u.trial_used_at IS NULL AND NOT {_SUB_EXISTS}",
             "Пришли, но не брали триал и не покупали."),
    "cold_7d": ("❄️ Холодные ≥7 дней", _cold_since(7),
                "Холодные, зарегистрированы ≥7 дней назад."),
    "cold_30d": ("❄️ Холодные ≥30 дней", _cold_since(30),
                 "Холодные, зарегистрированы ≥30 дней назад."),
    # --- Продление (платные, истекают скоро) ---
    "exp_in_1d": ("🔔 Платная истекает ≤24ч", _paid_expiring_within(1),
                  "Платная подписка закончится в ближайшие 24 часа."),
    "exp_in_3d": ("🔔 Платная истекает ≤3 дней", _paid_expiring_within(3),
                  "Платная подписка закончится в ближайшие 3 дня."),
    "exp_in_7d": ("🔔 Платная истекает ≤7 дней", _paid_expiring_within(7),
                  "Платная подписка закончится в ближайшую неделю."),
    # --- Возврат (истёкшие) ---
    "expd_3d": ("🔚 Истекла ≤3 дней назад", _expired_within(3),
                "Платная закончилась ≤3 дней назад — легко вернуть."),
    "expd_7d": ("🔚 Истекла ≤7 дней назад", _expired_within(7),
                "Платная закончилась ≤7 дней назад."),
    "expd_14d": ("🔚 Истекла ≤14 дней назад", _expired_within(14),
                 "Платная закончилась ≤14 дней назад."),
    "expd_30d": ("🔚 Истекла ≤30 дней назад", _expired_within(30),
                 "Платная закончилась ≤30 дней назад."),
    "expd_60d": ("🔚 Истекла ≤60 дней назад", _expired_within(60),
                 "Платная закончилась ≤60 дней назад — глубокая реактивация."),
    "expd_90d": ("🔚 Истекла ≤90 дней назад", _expired_within(90),
                 "Платная закончилась ≤90 дней назад."),
    "paid_lapsed": ("💔 Платили, сейчас не активны", f"{_PAID_EXISTS} AND NOT {_ACTIVE_SUB}",
                    "Когда-то платили, сейчас доступа нет — реактивация."),
    # --- Апселл / особые ---
    "loyal": ("🏆 Постоянные (2+ оплаты)", _LOYAL_2PLUS,
              "Оплатили 2 и более раз — самые лояльные."),
    "one_time": ("1️⃣ Купили один раз", _ONE_TIME,
                 "Оплатили ровно один раз — цель для повторной продажи."),
    "bypass_users": ("🌐 Пользуются обходом", _BYPASS_USER,
                     "Есть активный ключ обхода блокировок."),
    "referrers": ("🫂 Пригласившие друзей", _IS_REFERRER,
                  "Уже приглашали друзей — амбассадоры."),
    # --- Источник привлечения ---
    "referred": ("🤝 Пришли по приглашению", _REFERRED,
                 "Зарегистрировались по реферальной ссылке друга."),
    "via_link": ("🔗 Пришли по ссылке продвижения", _VIA_LINK,
                 "Атрибутированы к маркетинговой stats-ссылке."),
}



async def recipients(segment: str) -> list[int]:
    """Return reachable telegram_ids for a broadcast segment."""
    entry = SEGMENTS.get(segment)
    if entry is None:
        raise ValueError(f"unknown segment {segment!r}")
    where = entry[1]
    pool = get_pool()
    rows = await pool.fetch(
        f"SELECT u.telegram_id FROM users u WHERE u.is_reachable AND ({where})"
    )
    return [r["telegram_id"] for r in rows]


async def segment_count(segment: str) -> int:
    """Count of recipients in a segment (cheap preview, no id list)."""
    entry = SEGMENTS.get(segment)
    if entry is None:
        raise ValueError(f"unknown segment {segment!r}")
    pool = get_pool()
    return await pool.fetchval(
        f"SELECT COUNT(*) FROM users u WHERE u.is_reachable AND ({entry[1]})"
    )
