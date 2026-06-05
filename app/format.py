"""Small presentation helpers shared across handlers."""
from datetime import datetime

import asyncpg

from database import utcnow


def fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%d.%m.%Y %H:%M UTC")


def fmt_date(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%d.%m.%Y")


def time_left(expires_at: datetime) -> str:
    delta = expires_at - utcnow()
    if delta.total_seconds() <= 0:
        return "истекла"
    days = delta.days
    hours = delta.seconds // 3600
    if days > 0:
        return f"{days} дн. {hours} ч."
    minutes = (delta.seconds % 3600) // 60
    return f"{hours} ч. {minutes} мин."


def subscription_text(sub: asyncpg.Record | None) -> str:
    if sub is None or sub["status"] != "active":
        return (
            "У вас нет активной подписки.\n\n"
            "Активируйте бесплатный триал или оформите подписку."
        )
    lines = [
        "✅ <b>Подписка активна</b>",
        f"Осталось: <b>{time_left(sub['expires_at'])}</b>",
        f"Действует до: {fmt_dt(sub['expires_at'])}",
    ]
    if sub["subscription_url"]:
        lines.append("")
        lines.append("🔗 Ваша ссылка для подключения:")
        lines.append(f"<code>{sub['subscription_url']}</code>")
    return "\n".join(lines)
