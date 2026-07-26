"""Promo codes — admin-created codes users redeem for a discount or bonus days.

``redeem_promo`` is atomic (row lock + per-user check + usage bump in one
transaction) so a code with a limited number of uses can't be over-redeemed
under concurrency.
"""
from typing import Any

import asyncpg

from .core import get_pool, utcnow


async def create_promo(
    *,
    code: str,
    kind: str,
    discount_pct: int | None,
    discount_days: int | None,
    grant_days: int | None,
    max_uses: int | None,
    per_user_limit: int,
    expires_at,
    created_by: int | None,
) -> asyncpg.Record:
    pool = get_pool()
    return await pool.fetchrow(
        """
        INSERT INTO promo_codes
            (code, kind, discount_pct, discount_days, grant_days,
             max_uses, per_user_limit, expires_at, created_by)
        VALUES (lower($1), $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING *
        """,
        code, kind, discount_pct, discount_days, grant_days,
        max_uses, per_user_limit, expires_at, created_by,
    )


async def list_promos() -> list[asyncpg.Record]:
    pool = get_pool()
    return await pool.fetch("SELECT * FROM promo_codes ORDER BY created_at DESC")


async def get_promo(code: str) -> asyncpg.Record | None:
    pool = get_pool()
    return await pool.fetchrow("SELECT * FROM promo_codes WHERE code = lower($1)", code)


async def set_promo_active(code: str, active: bool) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE promo_codes SET active = $2 WHERE code = lower($1)", code, active
    )


async def delete_promo(code: str) -> None:
    pool = get_pool()
    await pool.execute("DELETE FROM promo_codes WHERE code = lower($1)", code)


async def redeem_promo(code: str, telegram_id: int) -> dict[str, Any]:
    """Atomically redeem ``code`` for ``telegram_id``.

    Returns ``{"ok": True, "promo": {...}}`` on success, else
    ``{"ok": False, "reason": <str>}`` with reason in: not_found | inactive |
    expired | exhausted | already_used.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM promo_codes WHERE code = lower($1) FOR UPDATE", code
            )
            if row is None:
                return {"ok": False, "reason": "not_found"}
            if not row["active"]:
                return {"ok": False, "reason": "inactive"}
            if row["expires_at"] is not None and row["expires_at"] <= utcnow():
                return {"ok": False, "reason": "expired"}
            if row["max_uses"] is not None and row["uses"] >= row["max_uses"]:
                return {"ok": False, "reason": "exhausted"}
            used = await conn.fetchval(
                "SELECT COUNT(*) FROM promo_redemptions "
                "WHERE code = $1 AND telegram_id = $2",
                row["code"], telegram_id,
            )
            if used >= row["per_user_limit"]:
                return {"ok": False, "reason": "already_used"}
            await conn.execute(
                "INSERT INTO promo_redemptions (code, telegram_id) VALUES ($1, $2)",
                row["code"], telegram_id,
            )
            await conn.execute(
                "UPDATE promo_codes SET uses = uses + 1 WHERE code = $1", row["code"]
            )
            return {"ok": True, "promo": dict(row)}
