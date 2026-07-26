"""Background scheduler loops: expiry reminders, cleanup and discount offers.

Each loop is a plain ``while True: sleep; work`` wrapped in try/except so one
failure never kills the cycle. No APScheduler/Celery — a single process covers
the whole lite build.

Timelines:
- PAID subs: 3 days before / day-of renewal reminders, "приостановлен" + −20% at
  expiry, −20% reactivation 3 days after expiry.
- TRIAL users: a dedicated 7-step conversion funnel (see ``_trial_funnel``) with
  escalating discounts; nothing else messages trial users.
"""
import asyncio
import logging
from datetime import timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from config import (
    DISCOUNT_REACTIVATION_PCT,
    DISCOUNT_SUB_END_PCT,
    EXPIRY_INTERVAL_SECONDS,
    REACTIVATION_AFTER_DAYS,
    REMINDER_INTERVAL_SECONDS,
)
from database import (
    all_bypass,
    automation_due_users,
    due_reactivation_offers,
    due_reminders,
    due_trial_funnel,
    enabled_automations,
    expired_active,
    is_payment_paid,
    list_overrides,
    mark_automation_sent,
    mark_expired,
    mark_react_offer_sent,
    mark_reminder_sent,
    mark_unreachable,
    pending_payments_recent,
    set_bypass_notify_level,
    set_offer,
    set_trial_funnel_stage,
    utcnow,
)

from . import (
    billing,
    broadcast_runner,
    bypass_service,
    discounts,
    platega,
    subscription_service,
)
from ..keyboards import offer_keyboard
from ..utils import convert_tg_emoji, safe_send, strip_tg_emoji

logger = logging.getLogger(__name__)

# --- Built-in automation overrides (editable text + on/off from the dashboard).
# Cache refreshed each loop tick; helpers fall back to the hardcoded default.
_ov: dict[str, dict] = {}


async def _refresh_ov() -> None:
    global _ov
    try:
        _ov = await list_overrides()
    except Exception:  # noqa: BLE001 - never break a loop on a config read
        pass


def _enabled(key: str) -> bool:
    return bool(_ov.get(key, {}).get("enabled", True))


def _text(key: str, default: str) -> str:
    return (_ov.get(key) or {}).get("text") or default


async def _send_auto(bot: Bot, uid: int, raw: str, kb) -> None:
    """Send an automation message, converting premium-emoji markdown."""
    await safe_send(bot, uid, convert_tg_emoji(raw), reply_markup=kb)


# Default texts for the built-in automatic messages (admin can override each).
_DEF_SUB_3DAY = (
    "⚡️ <b>Подписка заканчивается через 2 дня</b>\n\n"
    "Продли сейчас — срок добавится к текущему.\n"
    "Не теряй доступ 💎"
)
_DEF_SUB_DAYOF = (
    "⏳ <b>Подписка заканчивается сегодня</b>\n\n"
    "Не теряй доступ — продли за минуту."
)
_DEF_SUB_EXPIRED = (
    "😔 <b>Доступ приостановлен</b>\n\n"
    "Подписка закончилась.\n"
    "Но всё легко исправить — один клик\n"
    "и ты снова в сети 🤍"
)
_DEF_REACT = (
    "☁️ <b>Соскучился по свободному интернету?</b>\n\n"
    "Ты был с нами — и мы помним 🤍\n\n"
    f"Возвращайся со скидкой {DISCOUNT_REACTIVATION_PCT}% —\n"
    "это только для тебя."
)


def builtin_registry() -> list[dict]:
    """Metadata for the dashboard: every built-in automatic message."""
    items = [
        {"key": "sub_3day", "name": "Продление · за 2 дня",
         "when": "За ~2 дня до конца платной подписки", "default": _DEF_SUB_3DAY},
        {"key": "sub_dayof", "name": "Продление · в день окончания",
         "when": "В день окончания платной подписки (даёт −%)", "default": _DEF_SUB_DAYOF},
        {"key": "sub_expired", "name": "Платная истекла",
         "when": "Сразу при окончании платной подписки (даёт −%)", "default": _DEF_SUB_EXPIRED},
        {"key": "reactivation", "name": "Возврат через 3 дня",
         "when": f"Через {REACTIVATION_AFTER_DAYS} дня после окончания (−%)", "default": _DEF_REACT},
        {"key": "traffic", "name": "Обход · мало трафика",
         "when": "При низком остатке ГБ обхода (6 уровней)", "default": "(системные уровни, текст не редактируется)"},
    ]
    funnel_when = {
        1: "Через 4 часа после старта триала", 2: "За 24 часа до конца триала",
        3: "За 7 часов до конца триала (−10%)", 4: "За 1 час до конца триала (−15%)",
        5: "В момент окончания триала (−20%)", 6: "Через 3 дня после триала (−30%)",
        7: "Через 7 дней после триала (−50%)",
    }
    for stage in range(1, 8):
        items.append({
            "key": f"funnel_{stage}", "name": f"Триал-воронка · шаг {stage}",
            "when": funnel_when[stage], "default": _FUNNEL_TEXT[stage][0],
        })
    return items


async def _send_3day(bot: Bot) -> None:
    if not _enabled("sub_3day"):
        return
    rows = await due_reminders("reminder_24h_sent")  # column repurposed: 3 days
    for row in rows:
        await _send_auto(
            bot, row["telegram_id"], _text("sub_3day", _DEF_SUB_3DAY),
            offer_keyboard("🔄 Продлить подписку"),
        )
        await mark_reminder_sent(row["telegram_id"], "reminder_24h_sent")
    if rows:
        logger.info("Sent %d 3-day reminders", len(rows))


async def _send_day_of(bot: Bot) -> None:
    if not _enabled("sub_dayof"):
        return
    rows = await due_reminders("reminder_3h_sent")  # column repurposed: day-of
    for row in rows:
        uid = row["telegram_id"]
        # −20% renewal offer for paid subscriptions (trials get their own −10%).
        if row["source"] != "trial":
            await set_offer(uid, "sub_end", DISCOUNT_SUB_END_PCT, utcnow() + timedelta(days=1))
        await _send_auto(bot, uid, _text("sub_dayof", _DEF_SUB_DAYOF),
                         offer_keyboard("🔄 Продлить подписку", pct=DISCOUNT_SUB_END_PCT))
        await mark_reminder_sent(uid, "reminder_3h_sent")
    if rows:
        logger.info("Sent %d day-of reminders", len(rows))


async def reminder_loop(bot: Bot) -> None:
    while True:
        try:
            await _refresh_ov()
            await _send_3day(bot)
            await _send_day_of(bot)
        except Exception:  # noqa: BLE001 - keep the loop alive
            logger.exception("reminder_loop iteration failed")
        await asyncio.sleep(REMINDER_INTERVAL_SECONDS)


async def expiry_cleanup_loop(bot: Bot) -> None:
    while True:
        try:
            await _refresh_ov()
            rows = await expired_active()
            for row in rows:
                uid = row["telegram_id"]
                await subscription_service.deprovision(row["panel_uuid"])
                await mark_expired(uid)
                # Trials are converted by the dedicated trial funnel; they must
                # NOT get the paid "Доступ приостановлен" message.
                if row["source"] == "trial":
                    continue
                if not _enabled("sub_expired"):
                    continue  # message off — но деактивация панели уже сделана
                # −20% restore offer right at expiry.
                await set_offer(uid, "sub_end", DISCOUNT_SUB_END_PCT, utcnow() + timedelta(days=1))
                await _send_auto(
                    bot, uid, _text("sub_expired", _DEF_SUB_EXPIRED),
                    offer_keyboard("🔑 Восстановить доступ −20%", pct=DISCOUNT_SUB_END_PCT),
                )
            if rows:
                logger.info("Expired %d subscriptions", len(rows))
        except Exception:  # noqa: BLE001 - keep the loop alive
            logger.exception("expiry_cleanup_loop iteration failed")
        await asyncio.sleep(EXPIRY_INTERVAL_SECONDS)


# --- Trial conversion funnel ----------------------------------------------
#
# Seven escalating steps from trial activation to a week after expiry. Each
# step fires once; if the bot was offline and several elapsed, only the latest
# relevant step is sent. Discounts last 24h. Texts use premium custom emoji
# (![x](tg://emoji?id=…)) with a plain-emoji fallback if the bot can't send them.
# A purchase / paid access drops the user out of the funnel (see due_trial_funnel).

# stage -> (raw text, button label, discount pct or None)
_FUNNEL_TEXT: dict[int, tuple[str, str, int | None]] = {
    1: (
        "![👀](tg://emoji?id=5210956306952758910) <b>Ну как, чувствуешь разницу?</b>\n\n"
        "Вот так и должен работать интернет ![🌎](tg://emoji?id=5224450179368767019)\n"
        "Стабильно, быстро и без нервов\n\n"
        "<b>Оставайся с нами !</b> ![👇](tg://emoji?id=5231102735817918643)",
        "🚀 Купить подписку", None,
    ),
    2: (
        "![⏳](tg://emoji?id=5451732530048802485)<b>Завтра бесплатный период закончится</b>\n\n"
        "Не хочется терять это, правда?\n\n"
        "![🌎](tg://emoji?id=5224450179368767019)<b>Оформи подписку — всё сохранится, "
        "ничего не нужно переустанавливать.</b>",
        "🚀 Купить подписку", None,
    ),
    3: (
        "![🎁](tg://emoji?id=5442939099906325301)<b>Специально для тебя −10%</b>\n\n"
        "Оставайся с нами — интернет который просто работает "
        "![🌎](tg://emoji?id=5224450179368767019)\n\n"
        "<b>Забери скидку !</b> ![👇](tg://emoji?id=5231102735817918643)",
        "🚀 Купить −10%", 10,
    ),
    4: (
        "![‼️](tg://emoji?id=5440660757194744323)<b>Через 1 час доступ отключится</b>\n\n"
        "Сайты и приложения вернутся к блокировкам.\n\n"
        "![💎](tg://emoji?id=5235630047959727475)<b>Специально для тебя −15%</b>\n\n"
        "Оформи сейчас — ключ и настройки сохранятся 😌\n\n"
        "Забери скидку ![👇](tg://emoji?id=5231102735817918643)",
        "⚡️ Не терять доступ −15%", 15,
    ),
    5: (
        "![🆘](tg://emoji?id=5220108512893344933)<b>Бесплатный период закончился</b>\n\n"
        "Бесплатные VPN сейчас блокируют первыми. Ты без защиты — и это опасно"
        "![🛰](tg://emoji?id=5321304062715517873)\n\n"
        "![🌎](tg://emoji?id=5224450179368767019)<b>ELMA хочет тебя защитить.\n"
        "Поэтому держи − 20% только для тебя !</b> ![🎁](tg://emoji?id=5442939099906325301)\n\n"
        "Оставайся с нами ![👇](tg://emoji?id=5231102735817918643)",
        "🚀 Забрать −20%", 20,
    ),
    6: (
        "![🛍](tg://emoji?id=5406683434124859552)<b>-30% специально для тебя</b>\n\n"
        "![🆘](tg://emoji?id=5220108512893344933)Бесплатные VPN блокируют каждый день\n\n"
        "Ты уже 3 дня без защиты.\n"
        "Пока ты думаешь — риски растут.\n\n"
        "![💎](tg://emoji?id=5235630047959727475)<b>Подключайся к ELMA и забирай свою скидку</b> "
        "![👇](tg://emoji?id=5231102735817918643)",
        "🚀 Забрать −30%", 30,
    ),
    7: (
        "![🎁](tg://emoji?id=5442939099906325301)<b>−50% специально для тебя</b>\n\n"
        "Ты пропал 7 дней назад — мы заметили 🫂\n\n"
        "⚡️ Скорость до 75 Гбит/с\n"
        "📱 До 5 устройств\n"
        "🔒 Zero-logs — твои данные только твои\n\n"
        "<b>Возвращайся. Ждём тебя!</b> ![👇](tg://emoji?id=5231102735817918643)",
        "🚀 Забрать −50%", 50,
    ),
}


def _funnel_target_stage(now, activated, expires) -> int:
    """Highest funnel stage whose trigger time has already passed (0 = none)."""
    triggers = {
        1: activated + timedelta(hours=4),
        2: expires - timedelta(hours=24),
        3: expires - timedelta(hours=7),
        4: expires - timedelta(hours=1),
        5: expires,
        6: expires + timedelta(days=3),
        7: expires + timedelta(days=7),
    }
    for stage in range(7, 0, -1):
        if triggers[stage] <= now:
            return stage
    return 0


async def _send_funnel(bot: Bot, uid: int, raw: str, kb) -> None:
    """Send with premium custom emoji; on CUSTOM_EMOJI_INVALID retry plain."""
    for text in (convert_tg_emoji(raw), strip_tg_emoji(raw)):
        try:
            await bot.send_message(
                uid, text, parse_mode="HTML", reply_markup=kb,
                disable_web_page_preview=True,
            )
            return
        except TelegramForbiddenError:
            await mark_unreachable(uid)
            return
        except TelegramBadRequest:
            continue
        except Exception:  # noqa: BLE001 - one bad recipient mustn't break the loop
            logger.exception("trial funnel send failed for %s", uid)
            return


async def _trial_funnel(bot: Bot) -> None:
    rows = await due_trial_funnel()
    now = utcnow()
    advanced = 0
    for row in rows:
        target = _funnel_target_stage(now, row["trial_used_at"], row["trial_expires_at"])
        if target <= row["trial_funnel_stage"]:
            continue
        uid = row["telegram_id"]
        raw, button, pct = _FUNNEL_TEXT[target]
        key = f"funnel_{target}"
        if not _enabled(key):
            # step off — advance so the funnel still progresses to later steps
            await set_trial_funnel_stage(uid, target)
            continue
        if pct:
            await set_offer(uid, "trial", pct, now + timedelta(days=1))
        await _send_funnel(bot, uid, _text(key, raw), offer_keyboard(button, pct=pct))
        await set_trial_funnel_stage(uid, target)
        advanced += 1
    if advanced:
        logger.info("Trial funnel advanced %d users", advanced)


async def _reactivation_offers(bot: Bot) -> None:
    if not _enabled("reactivation"):
        return
    rows = await due_reactivation_offers(REACTIVATION_AFTER_DAYS)
    for row in rows:
        uid = row["telegram_id"]
        await set_offer(uid, "reactivation", DISCOUNT_REACTIVATION_PCT, utcnow() + timedelta(days=1))
        await mark_react_offer_sent(uid)
        await _send_auto(
            bot, uid, _text("reactivation", _DEF_REACT),
            offer_keyboard(
                f"🔑 Купить со скидкой −{DISCOUNT_REACTIVATION_PCT}%",
                pct=DISCOUNT_REACTIVATION_PCT,
            ),
        )
    if rows:
        logger.info("Sent %d reactivation offers", len(rows))


async def offer_loop(bot: Bot) -> None:
    while True:
        try:
            await _refresh_ov()
            await _trial_funnel(bot)          # trial conversion (7 steps)
            await _reactivation_offers(bot)   # paid win-back, 3 days after expiry
            await _run_custom_automations(bot)  # admin-created automations
        except Exception:  # noqa: BLE001 - keep the loop alive
            logger.exception("offer_loop iteration failed")
        await asyncio.sleep(EXPIRY_INTERVAL_SECONDS)


# --- Bypass traffic monitor -----------------------------------------------

_TRAFFIC_MSG: dict[int, str] = {
    0: "🌐 <b>Осталось ~8 ГБ обхода</b>\n\nСкоро стоит пополнить, чтобы доступ не прервался 👇",
    1: "🌐 <b>5 ГБ обхода осталось</b>\n\nПора пополнить запас 👇",
    2: "🌐 <b>3 ГБ обхода осталось</b>\n\nЛучше пополнить заранее 👇",
    3: "⚠️ <b>1 ГБ обхода!</b>\n\nСовсем скоро отключится — пополни 👇",
    4: "⚠️ <b>500 МБ обхода</b>\n\nПочти всё. Пополни, чтобы не потерять доступ 👇",
    5: "🛑 <b>Трафик обхода закончился</b>\n\nОбход отключился. Пополни — и всё снова заработает 👇",
}


def _traffic_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🌐 Купить ГБ обхода", callback_data="tr:open")
    kb.button(text="🏠 Меню", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


async def _traffic_monitor(bot: Bot) -> None:
    if not _enabled("traffic"):
        return
    rows = await all_bypass()
    sent = 0
    for row in rows:
        tg = row["telegram_id"]
        usage = await bypass_service.get_usage(tg)
        if not usage or not usage["limit"]:
            continue
        remaining = usage["remaining"]
        target = -1
        for i, (threshold, _label) in enumerate(config.TRAFFIC_NOTIFY_THRESHOLDS):
            if remaining <= threshold:
                target = i
        current = row["notify_level"] if row["notify_level"] is not None else -1
        if target > current:
            await safe_send(bot, tg, _TRAFFIC_MSG[target], reply_markup=_traffic_kb())
            await set_bypass_notify_level(tg, target)
            sent += 1
    if sent:
        logger.info("Traffic monitor sent %d low-balance pushes", sent)


async def traffic_monitor_loop(bot: Bot) -> None:
    if not config.BYPASS_ENABLED:
        return
    while True:
        try:
            await _refresh_ov()
            await _traffic_monitor(bot)
        except Exception:  # noqa: BLE001 - keep the loop alive
            logger.exception("traffic_monitor_loop iteration failed")
        await asyncio.sleep(config.TRAFFIC_MONITOR_SECONDS)


# --- Custom automations (admin-created lifecycle triggers) -----------------

async def _run_custom_automations(bot: Bot) -> None:
    """Fire admin-created automations: for each enabled one, message users who
    crossed its trigger threshold (once per user), setting a discount if set."""
    autos = await enabled_automations()
    for a in autos:
        try:
            uids = await automation_due_users(
                a["trigger_type"], a["delay_hours"], a["created_at"], a["id"]
            )
        except Exception:  # noqa: BLE001 - a bad automation mustn't stop others
            logger.exception("automation %s eligibility failed", a["id"])
            continue
        if not uids:
            continue
        markup = broadcast_runner.build_markup(None, None, a["buttons"])
        for uid in uids:
            if a["discount_pct"] and a["discount_scope"]:
                code = discounts.SCOPE_TO_CODE.get(a["discount_scope"])
                if code:
                    hours = int(a["discount_hours"] or 24)
                    await set_offer(uid, code, int(a["discount_pct"]),
                                    utcnow() + timedelta(hours=hours))
            await _send_auto(bot, uid, a["text"], markup)
            await mark_automation_sent(a["id"], uid)
        logger.info("Automation %s (%s) sent to %d users", a["id"], a["trigger_type"], len(uids))


# --- Payment reconcile (missed-webhook safety net) ------------------------

async def _reconcile_payments(bot: Bot) -> None:
    rows = await pending_payments_recent(
        config.PAYMENT_RECONCILE_MIN_AGE_MIN, config.PAYMENT_RECONCILE_MAX_AGE_MIN
    )
    fixed = 0
    for payment in rows:
        txn = payment["invoice_id"]
        if not txn or await is_payment_paid(txn):
            continue
        try:
            status = await platega.get_status(txn)
        except Exception:  # noqa: BLE001 - provider hiccup, retry next tick
            logger.warning("Reconcile: status check failed for %s", txn)
            continue
        if status != platega.STATUS_CONFIRMED:
            continue
        try:
            await billing.finalize_confirmed_payment(bot, payment)
            fixed += 1
            logger.info("Reconciled missed payment %s (code=%s)", txn, payment["tariff_code"])
        except Exception:  # noqa: BLE001
            logger.exception("Reconcile finalize failed for %s", txn)
    if fixed:
        logger.info("Payment reconcile finalized %d missed payment(s)", fixed)


async def payment_reconcile_loop(bot: Bot) -> None:
    if not config.PAYMENTS_ENABLED:
        return
    while True:
        try:
            await _reconcile_payments(bot)
        except Exception:  # noqa: BLE001 - keep the loop alive
            logger.exception("payment_reconcile_loop iteration failed")
        await asyncio.sleep(config.PAYMENT_RECONCILE_SECONDS)
