"""Pool management, schema init and datetime helpers.

Rule from production scars (see docs/ARCHITECTURE.md §10.1): we keep *all*
datetime columns as TIMESTAMPTZ and always work with timezone-aware
``datetime`` objects. Never mix naive and aware datetimes.
"""
import logging
from datetime import datetime, timezone

import asyncpg

from config import DATABASE_URL

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


# init_db runs ALTER/CREATE under tight timeouts so a stray ACCESS EXCLUSIVE
# lock can't hang startup on a large table (§10.3).
SCHEMA_SQL = """
SET lock_timeout = '5s';
SET statement_timeout = '20s';

CREATE TABLE IF NOT EXISTS users (
    telegram_id      BIGINT PRIMARY KEY,
    username         TEXT,
    language         TEXT DEFAULT 'ru',
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    trial_used_at    TIMESTAMPTZ,
    trial_expires_at TIMESTAMPTZ,
    is_reachable     BOOLEAN DEFAULT TRUE,
    referred_by      BIGINT,
    trial_offer_sent BOOLEAN DEFAULT FALSE,
    offer_code       TEXT,
    offer_pct        INTEGER,
    offer_expires_at TIMESTAMPTZ,
    trial_funnel_stage SMALLINT NOT NULL DEFAULT 0
);
ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by      BIGINT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_offer_sent BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS offer_code       TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS offer_pct        INTEGER;
ALTER TABLE users ADD COLUMN IF NOT EXISTS offer_expires_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_funnel_stage SMALLINT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS referrals (
    referred_id BIGINT PRIMARY KEY REFERENCES users(telegram_id),
    referrer_id BIGINT NOT NULL REFERENCES users(telegram_id),
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | credited
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    credited_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id);

CREATE TABLE IF NOT EXISTS gifts (
    code        TEXT PRIMARY KEY,
    tariff_code TEXT NOT NULL,
    created_by  BIGINT NOT NULL REFERENCES users(telegram_id),
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | redeemed
    redeemed_by BIGINT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    redeemed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS subscriptions (
    telegram_id       BIGINT PRIMARY KEY REFERENCES users(telegram_id),
    panel_uuid        TEXT,                 -- internal Remnawave uuid (PATCH/DELETE)
    vless_uuid        TEXT,                 -- uuid the client sees in VLESS strings
    subscription_url  TEXT,                 -- ready-made link handed to the user
    expires_at        TIMESTAMPTZ NOT NULL,
    status            TEXT NOT NULL,        -- 'active' | 'expired' | 'pending'
    source            TEXT NOT NULL,        -- 'trial' | 'payment' | 'admin'
    reminder_24h_sent BOOLEAN DEFAULT FALSE,
    reminder_3h_sent  BOOLEAN DEFAULT FALSE,
    react_offer_sent  BOOLEAN DEFAULT FALSE,
    trial_1h_sent     BOOLEAN DEFAULT FALSE,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    activated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Migration from the previous (Атлас Lite) column names, if present.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'subscriptions' AND column_name = 'vpn_uuid')
       AND NOT EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'subscriptions' AND column_name = 'panel_uuid') THEN
        ALTER TABLE subscriptions RENAME COLUMN vpn_uuid TO panel_uuid;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'subscriptions' AND column_name = 'vpn_url')
       AND NOT EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'subscriptions' AND column_name = 'subscription_url') THEN
        ALTER TABLE subscriptions RENAME COLUMN vpn_url TO subscription_url;
    END IF;
END $$;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS panel_uuid       TEXT;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS vless_uuid       TEXT;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS subscription_url TEXT;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS created_at       TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS react_offer_sent BOOLEAN DEFAULT FALSE;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS trial_1h_sent    BOOLEAN DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS payments (
    id             BIGSERIAL PRIMARY KEY,
    telegram_id    BIGINT NOT NULL REFERENCES users(telegram_id),
    invoice_id     TEXT UNIQUE,
    amount_kopecks BIGINT NOT NULL,           -- money amount in kopecks (₽×100)
    provider       TEXT NOT NULL DEFAULT 'unknown',  -- sbp | card | stars | ...
    status         TEXT NOT NULL,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    paid_at        TIMESTAMPTZ
);
ALTER TABLE payments ADD COLUMN IF NOT EXISTS provider TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE payments ADD COLUMN IF NOT EXISTS tariff_code TEXT;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS fail_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_subs_expiry
    ON subscriptions(expires_at) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_payments_status
    ON payments(status);

-- --- Admin web dashboard ------------------------------------------------
-- One password hash per admin telegram_id (set via a bot magic-link).
CREATE TABLE IF NOT EXISTS admin_auth (
    telegram_id   BIGINT PRIMARY KEY,
    password_hash TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- One-time magic-link tokens (set/reset password, issued by the bot).
CREATE TABLE IF NOT EXISTS admin_login_tokens (
    token       TEXT PRIMARY KEY,
    telegram_id BIGINT NOT NULL,
    purpose     TEXT NOT NULL DEFAULT 'setup',   -- setup | reset
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ
);

-- Audit log of admin actions performed from the dashboard.
CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    admin_id    BIGINT NOT NULL,
    action      TEXT NOT NULL,
    target_id   BIGINT,
    detail      TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC);

-- WebAuthn / Passkey credentials, one or more per admin.
CREATE TABLE IF NOT EXISTS webauthn_credentials (
    credential_id TEXT PRIMARY KEY,           -- base64url credential id
    telegram_id   BIGINT NOT NULL,
    public_key    TEXT NOT NULL,              -- base64url COSE public key
    sign_count    BIGINT NOT NULL DEFAULT 0,
    label         TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    last_used_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_webauthn_tg ON webauthn_credentials(telegram_id);

-- --- Bypass (обход) — отдельная Remnawave-entity, оплата по ГБ ----------
-- Fully independent of premium `subscriptions`: a user can have premium,
-- bypass, both or neither. expireAt in the panel is +10y; access ends when GB
-- run out.
CREATE TABLE IF NOT EXISTS bypass_subscriptions (
    telegram_id         BIGINT PRIMARY KEY REFERENCES users(telegram_id),
    panel_uuid          TEXT,                       -- Remnawave bypass entity uuid
    subscription_url    TEXT,                       -- ready client link
    traffic_limit_bytes BIGINT NOT NULL DEFAULT 0,  -- cumulative purchased bytes
    notify_level        SMALLINT NOT NULL DEFAULT -1, -- last low-traffic step sent
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Audit ledger of GB-pack purchases (never deleted).
CREATE TABLE IF NOT EXISTS traffic_purchases (
    id            BIGSERIAL PRIMARY KEY,
    telegram_id   BIGINT NOT NULL REFERENCES users(telegram_id),
    gb_amount     INTEGER NOT NULL,
    price_kopecks BIGINT NOT NULL,
    provider      TEXT NOT NULL DEFAULT 'unknown',
    invoice_id    TEXT UNIQUE,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_traffic_purchases_tg ON traffic_purchases(telegram_id);

-- --- Broadcast history + scheduled/recurring broadcasts -----------------
-- Every send (manual / resend / scheduled) is journaled here so the dashboard
-- can list the last N and re-send any of them. All timestamps TIMESTAMPTZ (UTC).
CREATE TABLE IF NOT EXISTS broadcast_history (
    id             BIGSERIAL PRIMARY KEY,
    admin_id       BIGINT,
    segment        TEXT NOT NULL,
    text           TEXT NOT NULL DEFAULT '',
    photo_file_id  TEXT,
    button_text    TEXT,
    button_url     TEXT,
    source         TEXT NOT NULL DEFAULT 'manual',  -- manual | resend | scheduled
    status         TEXT NOT NULL DEFAULT 'running',  -- running | done
    total          INTEGER NOT NULL DEFAULT 0,
    sent           INTEGER NOT NULL DEFAULT 0,
    blocked        INTEGER NOT NULL DEFAULT 0,
    failed         INTEGER NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    finished_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_broadcast_history_created
    ON broadcast_history(created_at DESC);

-- Scheduled / recurring broadcasts. ``run_at`` is the next fire time (UTC);
-- ``time_msk`` (HH:MM) and ``weekdays`` (CSV of 0=Mon..6=Sun) drive recurrence.
CREATE TABLE IF NOT EXISTS scheduled_broadcasts (
    id             BIGSERIAL PRIMARY KEY,
    admin_id       BIGINT,
    segment        TEXT NOT NULL,
    text           TEXT NOT NULL DEFAULT '',
    photo_file_id  TEXT,
    button_text    TEXT,
    button_url     TEXT,
    kind           TEXT NOT NULL,                    -- once | daily | weekly
    run_at         TIMESTAMPTZ NOT NULL,             -- next fire time (UTC)
    time_msk       TEXT,                             -- 'HH:MM' (recurring display)
    weekdays       TEXT,                             -- CSV 0..6 (weekly)
    active         BOOLEAN NOT NULL DEFAULT TRUE,
    run_count      INTEGER NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    last_run_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_scheduled_due
    ON scheduled_broadcasts(run_at) WHERE active;

-- --- Admin web-push (VAPID) ---------------------------------------------
CREATE TABLE IF NOT EXISTS admin_push_subscriptions (
    endpoint    TEXT PRIMARY KEY,
    admin_id    BIGINT,
    p256dh      TEXT NOT NULL,
    auth        TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
-- One row per (MSK day, milestone) so each revenue milestone pushes once/day.
CREATE TABLE IF NOT EXISTS push_milestones (
    day_key    TEXT NOT NULL,
    milestone  INTEGER NOT NULL,
    fired_at   TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (day_key, milestone)
);
"""


async def init_db() -> asyncpg.Pool:
    """Create the connection pool and ensure the schema exists."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            DATABASE_URL, min_size=1, max_size=10, command_timeout=30
        )
        logger.info("Database pool created")
    async with _pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
    logger.info("Database schema ready")
    return _pool


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool is not initialized; call init_db() first")
    return _pool


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")


def utcnow() -> datetime:
    """Single source of 'now' — always timezone-aware UTC."""
    return datetime.now(timezone.utc)


def to_db_utc(dt: datetime | None) -> datetime | None:
    """Coerce any datetime to an aware UTC value safe for TIMESTAMPTZ."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
