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
    is_reachable     BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS subscriptions (
    telegram_id       BIGINT PRIMARY KEY REFERENCES users(telegram_id),
    vpn_uuid          TEXT,
    vpn_url           TEXT,
    expires_at        TIMESTAMPTZ NOT NULL,
    status            TEXT NOT NULL,
    source            TEXT NOT NULL,
    reminder_24h_sent BOOLEAN DEFAULT FALSE,
    reminder_3h_sent  BOOLEAN DEFAULT FALSE,
    activated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS payments (
    id             BIGSERIAL PRIMARY KEY,
    telegram_id    BIGINT NOT NULL REFERENCES users(telegram_id),
    invoice_id     TEXT UNIQUE,
    amount_kopecks BIGINT NOT NULL,
    status         TEXT NOT NULL,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    paid_at        TIMESTAMPTZ
);

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
