"""User balance (kopecks), VIP flag, fixed-cashback override + balance ledger."""
import asyncpg

from .core import get_pool


async def get_balance(telegram_id: int) -> int:
    pool = get_pool()
    val = await pool.fetchval(
        "SELECT balance_kopecks FROM users WHERE telegram_id = $1", telegram_id
    )
    return int(val or 0)


async def adjust_balance(
    telegram_id: int, delta_kopecks: int, reason: str, meta: str | None = None
) -> int:
    """Apply ``delta_kopecks`` (may be negative) and journal it. Returns the new
    balance. Atomic: balance update + ledger insert in one transaction."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            new_balance = await conn.fetchval(
                "UPDATE users SET balance_kopecks = balance_kopecks + $2 "
                "WHERE telegram_id = $1 RETURNING balance_kopecks",
                telegram_id, delta_kopecks,
            )
            if new_balance is None:
                raise ValueError(f"unknown user {telegram_id}")
            await conn.execute(
                "INSERT INTO balance_ledger (telegram_id, delta_kopecks, reason, meta) "
                "VALUES ($1, $2, $3, $4)",
                telegram_id, delta_kopecks, reason, meta,
            )
            return int(new_balance)


async def try_spend_balance(telegram_id: int, amount_kopecks: int, meta: str | None = None) -> bool:
    """Deduct ``amount_kopecks`` only if the balance covers it. Returns success."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            bal = await conn.fetchval(
                "SELECT balance_kopecks FROM users WHERE telegram_id = $1 FOR UPDATE",
                telegram_id,
            )
            if bal is None or int(bal) < amount_kopecks:
                return False
            await conn.execute(
                "UPDATE users SET balance_kopecks = balance_kopecks - $2 WHERE telegram_id = $1",
                telegram_id, amount_kopecks,
            )
            await conn.execute(
                "INSERT INTO balance_ledger (telegram_id, delta_kopecks, reason, meta) "
                "VALUES ($1, $2, 'purchase', $3)",
                telegram_id, -amount_kopecks, meta,
            )
            return True


async def balance_ledger(telegram_id: int, limit: int = 20) -> list[asyncpg.Record]:
    pool = get_pool()
    return await pool.fetch(
        "SELECT delta_kopecks, reason, meta, created_at FROM balance_ledger "
        "WHERE telegram_id = $1 ORDER BY created_at DESC LIMIT $2",
        telegram_id, limit,
    )


async def set_vip(telegram_id: int, is_vip: bool) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE users SET is_vip = $2 WHERE telegram_id = $1", telegram_id, is_vip
    )


async def set_cashback_fixed(telegram_id: int, percent: int | None) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE users SET cashback_fixed_percent = $2 WHERE telegram_id = $1",
        telegram_id, percent,
    )
