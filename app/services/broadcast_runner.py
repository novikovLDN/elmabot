"""One place that actually *runs* a broadcast — used by the dashboard "send"
button, the "resend" action and the scheduler — plus the schedule-time maths.

Timezone policy: the bot stores every timestamp as UTC (TIMESTAMPTZ). Admins
think in **Moscow time (MSK, UTC+3, no DST)** — that's what the dashboard shows
(``format.ts`` renders Europe/Moscow) and what schedule inputs mean. We convert
MSK↔UTC here so the DB stays UTC-only.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import database
from app.events import bus
from app.utils import safe_send

from . import broadcaster

logger = logging.getLogger(__name__)

# Admin-facing timezone. Moscow is UTC+3 year-round (Russia dropped DST in 2014).
MSK = timezone(timedelta(hours=3))

# How often the scheduler wakes to fire due broadcasts.
SCHEDULE_CHECK_SECONDS = 30

# Max lead time for a one-off schedule ("до недели").
MAX_SCHEDULE_DAYS = 7

_SRC_LABEL = {"manual": "", "resend": " (повтор)", "scheduled": " (по расписанию)"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- Sending ---------------------------------------------------------------

# Preset CTA buttons the dashboard wizard can attach (key -> label).
BUTTON_PRESETS = {
    "buy": "🛒 Купить доступ",
    "channel": "📣 Перейти в канал",
    "referral": "🫂 Пригласить друга",
}


def build_markup(
    button_text: str | None, button_url: str | None, buttons: str | None = None
):
    """Recipient keyboard: an optional custom URL button plus any preset CTAs
    (``buttons`` is a CSV of BUTTON_PRESETS keys). None if nothing to attach."""
    kb = InlineKeyboardBuilder()
    has_any = False
    if button_text and button_url:
        kb.button(text=button_text, url=button_url)
        has_any = True
    for key in (buttons or "").split(","):
        key = key.strip()
        if key == "buy":
            kb.button(text=BUTTON_PRESETS["buy"], callback_data="buyaccess")
            has_any = True
        elif key == "channel":
            from config import CHANNEL_URL

            if CHANNEL_URL:
                kb.button(text=BUTTON_PRESETS["channel"], url=CHANNEL_URL)
            else:
                kb.button(text=BUTTON_PRESETS["channel"], callback_data="chan:soon")
            has_any = True
        elif key == "referral":
            kb.button(text=BUTTON_PRESETS["referral"], callback_data="menu:referral")
            has_any = True
    if not has_any:
        return None
    kb.adjust(1)
    return kb.as_markup()


def build_sender(bot, text: str, photo: str | None, markup):
    async def send_one(uid: int) -> None:
        if photo:
            await bot.send_photo(
                uid, photo, caption=text or None, parse_mode="HTML",
                reply_markup=markup,
            )
        else:
            await bot.send_message(
                uid, text, parse_mode="HTML", reply_markup=markup,
                disable_web_page_preview=True,
            )

    return send_one


async def run_broadcast(
    bot,
    *,
    admin_id: int | None,
    segment: str,
    text: str,
    photo_file_id: str | None = None,
    button_text: str | None = None,
    button_url: str | None = None,
    buttons: str | None = None,
    source: str = "manual",
) -> dict:
    """Journal, fan out, record the result and DM every admin the summary.
    Returns ``{id, total}``. Streams live progress on the event bus."""
    text = (text or "").strip()
    user_ids = await database.recipients(segment)
    total = len(user_ids)
    bid = await database.record_broadcast(
        admin_id=admin_id, segment=segment, text=text, photo_file_id=photo_file_id,
        button_text=button_text, button_url=button_url, buttons=buttons,
        total=total, source=source,
    )
    label = database.SEGMENTS.get(segment, (segment, ""))[0]
    markup = build_markup(button_text, button_url, buttons)
    send_one = build_sender(bot, text, photo_file_id, markup)

    bus.publish({
        "type": "broadcast:created", "id": bid, "segment": segment,
        "total": total, "source": source,
    })

    async def progress(res) -> None:
        bus.publish({
            "type": "broadcast:progress", "id": bid, "segment": segment,
            "sent": res.sent, "blocked": res.blocked, "failed": res.failed,
            "total": total,
        })

    res = await broadcaster.broadcast(user_ids, send_one, progress=progress)
    await database.finish_broadcast(
        bid, sent=res.sent, blocked=res.blocked, failed=res.failed
    )
    bus.publish({
        "type": "broadcast:done", "id": bid, "segment": segment,
        "sent": res.sent, "blocked": res.blocked, "failed": res.failed,
        "total": total,
    })
    logger.info(
        "Broadcast %s (%s) to %s done: sent=%d blocked=%d failed=%d",
        bid, source, segment, res.sent, res.blocked, res.failed,
    )

    summary = (
        f"✅ <b>Рассылка завершена{_SRC_LABEL.get(source, '')}</b>\n\n"
        f"Сегмент: <b>{label}</b>\n"
        f"Получателей: {total}\n"
        f"📨 Доставлено: {res.sent}\n"
        f"🚫 Заблокировали: {res.blocked}\n"
        f"⚠️ Ошибок: {res.failed}"
    )
    for aid in config.ADMIN_IDS:
        await safe_send(bot, aid, summary)

    # Best-effort admin web-push (no-op if push disabled/unavailable).
    from . import push_service

    await push_service.notify_broadcast_done(res.sent, total, res.failed)
    return {"id": bid, "total": total}


# --- Schedule-time maths (MSK <-> UTC) -------------------------------------

def parse_hhmm(s: str) -> tuple[int, int]:
    hh, mm = str(s).split(":")
    h, m = int(hh), int(mm)
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError("время должно быть в формате ЧЧ:ММ")
    return h, m


def parse_weekdays(csv: str | None) -> set[int]:
    """CSV of 0..6 (Mon..Sun) → a set. Rejects empty/invalid."""
    days: set[int] = set()
    for p in str(csv or "").split(","):
        p = p.strip()
        if not p:
            continue
        if not (p.isdigit() and 0 <= int(p) <= 6):
            raise ValueError("дни недели: числа 0..6 через запятую")
        days.add(int(p))
    if not days:
        raise ValueError("выберите хотя бы один день недели")
    return days


def _parse_msk_local(iso: str) -> datetime:
    """'YYYY-MM-DDTHH:MM' from an admin (interpreted as Moscow time) → aware UTC."""
    naive = datetime.strptime(str(iso)[:16], "%Y-%m-%dT%H:%M")
    return naive.replace(tzinfo=MSK).astimezone(timezone.utc)


def compute_next_run(
    kind: str, time_msk: str | None, weekdays: str | None, after: datetime
) -> datetime | None:
    """Next fire time (UTC) strictly after ``after``, or None for a one-off."""
    if kind == "once":
        return None
    h, m = parse_hhmm(time_msk or "")
    base = after.astimezone(MSK)
    if kind == "daily":
        cand = base.replace(hour=h, minute=m, second=0, microsecond=0)
        if cand <= base:
            cand += timedelta(days=1)
        return cand.astimezone(timezone.utc)
    if kind == "weekly":
        days = parse_weekdays(weekdays)
        for add in range(0, 8):
            cand = (base + timedelta(days=add)).replace(
                hour=h, minute=m, second=0, microsecond=0
            )
            if cand.weekday() in days and cand > base:
                return cand.astimezone(timezone.utc)
    return None


def initial_run_at(
    kind: str,
    *,
    run_at_local: str | None = None,
    time_msk: str | None = None,
    weekdays: str | None = None,
) -> datetime:
    """First fire time (UTC) for a new schedule; raises ValueError on bad input."""
    now = _now()
    if kind == "once":
        if not run_at_local:
            raise ValueError("укажите дату и время")
        dt = _parse_msk_local(run_at_local)
        if dt <= now:
            raise ValueError("время уже прошло")
        if dt > now + timedelta(days=MAX_SCHEDULE_DAYS):
            raise ValueError(f"не дальше {MAX_SCHEDULE_DAYS} дней")
        return dt
    nxt = compute_next_run(kind, time_msk, weekdays, now)
    if nxt is None:
        raise ValueError("не удалось вычислить ближайший запуск")
    return nxt


# --- Scheduler loop --------------------------------------------------------

async def scheduled_broadcast_loop(bot) -> None:
    """Fire due scheduled broadcasts and re-arm recurring ones."""
    while True:
        try:
            due = await database.due_scheduled()
            for row in due:
                # Re-arm (or deactivate) *first* so a long send can't double-fire.
                nxt = compute_next_run(
                    row["kind"], row["time_msk"], row["weekdays"], _now()
                )
                await database.advance_scheduled(row["id"], nxt)
                asyncio.create_task(run_broadcast(
                    bot,
                    admin_id=row["admin_id"],
                    segment=row["segment"],
                    text=row["text"],
                    photo_file_id=row["photo_file_id"],
                    button_text=row["button_text"],
                    button_url=row["button_url"],
                    buttons=row["buttons"],
                    source="scheduled",
                ))
                logger.info("Fired scheduled broadcast %s (%s)", row["id"], row["kind"])
        except Exception:  # noqa: BLE001 - keep the loop alive
            logger.exception("scheduled_broadcast_loop iteration failed")
        await asyncio.sleep(SCHEDULE_CHECK_SECONDS)
