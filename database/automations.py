"""Automations: overrides for built-in lifecycle messages + custom automations.

* ``automation_overrides`` — per-key enable/disable + text override for the
  bot's built-in automatic messages (reminders, trial funnel, win-back…).
* ``automations`` — admin-created automations on parameterised triggers, with a
  once-per-user guarantee via ``automation_sends``.
"""
import asyncpg

from .core import get_pool


# --- Built-in overrides ----------------------------------------------------

async def list_overrides() -> dict[str, dict]:
    pool = get_pool()
    rows = await pool.fetch("SELECT key, enabled, text FROM automation_overrides")
    return {r["key"]: {"enabled": r["enabled"], "text": r["text"]} for r in rows}


async def set_override(key: str, *, enabled: bool, text: str | None) -> None:
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO automation_overrides (key, enabled, text, updated_at)
        VALUES ($1, $2, $3, NOW())
        ON CONFLICT (key) DO UPDATE SET
            enabled = EXCLUDED.enabled, text = EXCLUDED.text, updated_at = NOW()
        """,
        key, enabled, (text or None),
    )


# --- Custom automations ----------------------------------------------------

async def create_automation(
    *, name: str, trigger_type: str, delay_hours: int, text: str,
    discount_pct: int | None, discount_hours: int | None, discount_scope: str | None,
    buttons: str | None,
) -> asyncpg.Record:
    pool = get_pool()
    return await pool.fetchrow(
        """
        INSERT INTO automations
            (name, trigger_type, delay_hours, text, discount_pct, discount_hours,
             discount_scope, buttons)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING *
        """,
        name, trigger_type, delay_hours, text, discount_pct, discount_hours,
        discount_scope, buttons,
    )


async def update_automation(automation_id: int, **fields) -> None:
    if not fields:
        return
    cols, vals = [], []
    for i, (k, v) in enumerate(fields.items(), start=2):
        cols.append(f"{k} = ${i}")
        vals.append(v)
    pool = get_pool()
    await pool.execute(
        f"UPDATE automations SET {', '.join(cols)}, updated_at = NOW() WHERE id = $1",
        automation_id, *vals,
    )


async def list_automations() -> list[asyncpg.Record]:
    pool = get_pool()
    return await pool.fetch(
        """
        SELECT a.*,
               (SELECT COUNT(*) FROM automation_sends s WHERE s.automation_id = a.id) AS sent_count
        FROM automations a ORDER BY a.created_at DESC
        """
    )


async def enabled_automations() -> list[asyncpg.Record]:
    pool = get_pool()
    return await pool.fetch("SELECT * FROM automations WHERE enabled")


async def delete_automation(automation_id: int) -> None:
    pool = get_pool()
    await pool.execute("DELETE FROM automations WHERE id = $1", automation_id)
    await pool.execute("DELETE FROM automation_sends WHERE automation_id = $1", automation_id)


async def automation_due_users(
    trigger_type: str, delay_hours: int, since, automation_id: int, limit: int = 500
) -> list[int]:
    """Users who crossed the trigger threshold (event within
    [since=automation.created_at, now - delay]) and haven't been sent yet."""
    pool = get_pool()
    unsent = (
        "AND NOT EXISTS (SELECT 1 FROM automation_sends s "
        "WHERE s.automation_id = $2 AND s.telegram_id = u.telegram_id)"
    )
    hrs = int(delay_hours)
    if trigger_type == "after_signup":
        sql = (
            "SELECT u.telegram_id FROM users u WHERE u.is_reachable "
            f"AND u.created_at <= now() - interval '{hrs} hours' "
            "AND u.created_at >= $1 " + unsent + " LIMIT $3"
        )
        rows = await pool.fetch(sql, since, automation_id, limit)
    elif trigger_type == "after_trial_expire":
        sql = (
            "SELECT u.telegram_id FROM users u WHERE u.is_reachable "
            "AND u.trial_expires_at IS NOT NULL "
            f"AND u.trial_expires_at <= now() - interval '{hrs} hours' "
            "AND u.trial_expires_at >= $1 "
            "AND NOT EXISTS (SELECT 1 FROM payments p WHERE p.telegram_id = u.telegram_id AND p.status='paid') "
            + unsent + " LIMIT $3"
        )
        rows = await pool.fetch(sql, since, automation_id, limit)
    elif trigger_type == "before_sub_expire":
        sql = (
            "SELECT u.telegram_id FROM users u "
            "JOIN subscriptions sub ON sub.telegram_id = u.telegram_id "
            "WHERE u.is_reachable AND sub.status = 'active' AND sub.source <> 'trial' "
            f"AND sub.expires_at <= now() + interval '{hrs} hours' "
            "AND sub.expires_at > now() AND sub.expires_at >= $1 "
            + unsent + " LIMIT $3"
        )
        rows = await pool.fetch(sql, since, automation_id, limit)
    elif trigger_type == "after_sub_expire":
        sql = (
            "SELECT u.telegram_id FROM users u "
            "JOIN subscriptions sub ON sub.telegram_id = u.telegram_id "
            "WHERE u.is_reachable AND sub.status = 'expired' AND sub.source <> 'trial' "
            f"AND sub.expires_at <= now() - interval '{hrs} hours' "
            "AND sub.expires_at >= $1 "
            + unsent + " LIMIT $3"
        )
        rows = await pool.fetch(sql, since, automation_id, limit)
    elif trigger_type == "after_first_purchase":
        first = ("(SELECT MIN(p.paid_at) FROM payments p "
                 "WHERE p.telegram_id = u.telegram_id AND p.status = 'paid')")
        sql = (
            "SELECT u.telegram_id FROM users u WHERE u.is_reachable "
            f"AND {first} <= now() - interval '{hrs} hours' AND {first} >= $1 "
            + unsent + " LIMIT $3"
        )
        rows = await pool.fetch(sql, since, automation_id, limit)
    elif trigger_type == "after_bypass_purchase":
        # Bought a GB pack but has no active premium — cross-sell premium.
        first = ("(SELECT MIN(tp.created_at) FROM traffic_purchases tp "
                 "WHERE tp.telegram_id = u.telegram_id)")
        sql = (
            "SELECT u.telegram_id FROM users u WHERE u.is_reachable "
            f"AND {first} <= now() - interval '{hrs} hours' AND {first} >= $1 "
            "AND NOT EXISTS (SELECT 1 FROM subscriptions s WHERE s.telegram_id = u.telegram_id "
            "AND s.status = 'active' AND s.source <> 'trial') "
            + unsent + " LIMIT $3"
        )
        rows = await pool.fetch(sql, since, automation_id, limit)
    else:
        return []
    return [r["telegram_id"] for r in rows]


async def mark_automation_sent(automation_id: int, telegram_id: int) -> None:
    pool = get_pool()
    await pool.execute(
        "INSERT INTO automation_sends (automation_id, telegram_id) VALUES ($1, $2) "
        "ON CONFLICT DO NOTHING",
        automation_id, telegram_id,
    )
