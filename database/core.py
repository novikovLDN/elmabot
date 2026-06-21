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
    offer_expires_at TIMESTAMPTZ
);
ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by      BIGINT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_offer_sent BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS offer_code       TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS offer_pct        INTEGER;
ALTER TABLE users ADD COLUMN IF NOT EXISTS offer_expires_at TIMESTAMPTZ;

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
