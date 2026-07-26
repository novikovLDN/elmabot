"""Admin web-push: VAPID sends + daily revenue-milestone notifications.

Everything here is best-effort and fully optional:
* if VAPID keys aren't set (``config.PUSH_ENABLED`` is False) → no-op;
* if ``pywebpush`` (or its native deps) isn't importable → no-op + one warning.
So a missing dependency or unset keys can never break the bot or a payment.
"""
import asyncio
import json
import logging
import random
from datetime import datetime, timedelta, timezone

import config
import database

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))

_PHRASES = [
    "Отличный день! Так держать 🚀",
    "Касса звенит — красавчики 💪",
    "Деньги идут, аудитория любит вас ❤️",
    "Ещё один рубеж взят 🏆",
    "Так и до рекорда недалеко 📈",
]

_warned = False


def _webpush():
    """Import pywebpush lazily; None (once-warned) if unavailable."""
    global _warned
    try:
        from pywebpush import WebPushException, webpush
        return webpush, WebPushException
    except Exception:  # noqa: BLE001 - missing package / native deps
        if not _warned:
            logger.warning("pywebpush unavailable; admin web-push disabled")
            _warned = True
        return None


async def send_to_admins(title: str, body: str, url: str = "/dashboard/") -> None:
    if not config.PUSH_ENABLED:
        return
    imported = _webpush()
    if imported is None:
        return
    webpush, WebPushException = imported
    subs = await database.list_push_subs()
    payload = json.dumps({"title": title, "body": body, "url": url})
    for s in subs:
        info = {
            "endpoint": s["endpoint"],
            "keys": {"p256dh": s["p256dh"], "auth": s["auth"]},
        }
        try:
            await asyncio.to_thread(
                webpush,
                subscription_info=info,
                data=payload,
                vapid_private_key=config.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": config.VAPID_SUBJECT},
            )
        except WebPushException as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            if code in (404, 410):  # subscription gone — prune it
                await database.delete_push_sub(s["endpoint"])
            else:
                logger.warning("web-push failed for %s: %s", s["endpoint"][:40], exc)
        except Exception:  # noqa: BLE001
            logger.exception("web-push error")


def _msk_day() -> tuple[str, datetime]:
    """(YYYY-MM-DD MSK, UTC datetime of MSK midnight today)."""
    now_msk = datetime.now(timezone.utc).astimezone(MSK)
    midnight_msk = now_msk.replace(hour=0, minute=0, second=0, microsecond=0)
    return now_msk.strftime("%Y-%m-%d"), midnight_msk.astimezone(timezone.utc)


async def check_revenue_milestones() -> None:
    """Fire a push for each daily revenue milestone crossed (once per MSK day)."""
    if not config.PUSH_ENABLED:
        return
    try:
        day_key, start_utc = _msk_day()
        rub = await database.revenue_kopecks_since(start_utc) // 100
        for m in config.REVENUE_MILESTONES:
            if rub >= m and await database.claim_milestone(day_key, m):
                pretty = f"{m:,}".replace(",", " ")
                await send_to_admins(f"🎉 {pretty} ₽ за сегодня", random.choice(_PHRASES))
    except Exception:  # noqa: BLE001 - never let a milestone check break a payment
        logger.exception("revenue milestone check failed")


async def notify_broadcast_done(sent: int, total: int, failed: int) -> None:
    await send_to_admins(
        "📢 Рассылка завершена",
        f"Доставлено {sent}/{total}" + (f", ошибок {failed}" if failed else ""),
    )
