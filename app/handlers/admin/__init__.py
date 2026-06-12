"""Admin dashboard: stats, find user (grant/revoke/history), broadcast.

Access is gated by a router-level filter — only ADMIN_TELEGRAM_ID reaches any
handler here; everyone else falls through to the other routers.
"""
import asyncio
import html
import logging
import re
from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.format import fmt_dt, fmt_rub, subscription_text
from app.keyboards import (
    admin_broadcast_confirm,
    admin_broadcast_segments,
    admin_dashboard_actions,
    admin_grant_cancel,
    admin_menu,
    admin_user_actions,
)
from app.services import broadcaster, subscription_service
from app.utils import safe_edit, safe_send
from config import ADMIN_TELEGRAM_ID, SUPPORT_USERNAME
from database import (
    find_user_by_username,
    get_subscription,
    get_user,
    payment_history,
    recipients,
    revoke_subscription,
    stats,
)

logger = logging.getLogger(__name__)

router = Router(name="admin")
router.message.filter(F.from_user.id == ADMIN_TELEGRAM_ID)
router.callback_query.filter(F.from_user.id == ADMIN_TELEGRAM_ID)

# Instruction shown to the admin when composing a broadcast. Tags are written
# escaped so they render literally (the admin sees the actual tags to type).
BROADCAST_HELP = (
    "📋 <b>Как оформить рассылку</b>\n\n"
    "• <b>Фото с текстом:</b> прикрепите фото и напишите текст в подписи под ним.\n"
    "• <b>Только текст:</b> просто отправьте сообщение.\n\n"
    "<b>Форматирование (HTML):</b>\n"
    "<code>&lt;b&gt;жирный&lt;/b&gt;</code>\n"
    "<code>&lt;i&gt;курсив&lt;/i&gt;</code>\n"
    "<code>&lt;u&gt;подчёркнутый&lt;/u&gt;</code>\n"
    "<code>&lt;s&gt;зачёркнутый&lt;/s&gt;</code>\n"
    "<code>&lt;tg-spoiler&gt;спойлер&lt;/tg-spoiler&gt;</code>\n"
    "<code>&lt;code&gt;моноширинный&lt;/code&gt;</code>\n"
    "<code>&lt;a href=\"https://site.ru\"&gt;ссылка&lt;/a&gt;</code>\n"
    "<code>&lt;blockquote&gt;цитата&lt;/blockquote&gt;</code>\n\n"
    "⚠️ Пишите теги <b>текстом</b>, а не через меню форматирования Telegram.\n"
    "Символы <code>&lt;</code> <code>&gt;</code> <code>&amp;</code> вне тегов "
    "экранируйте: <code>&amp;lt;</code> <code>&amp;gt;</code> <code>&amp;amp;</code>.\n\n"
    "После отправки я покажу превью — проверьте, как увидят пользователи."
)


class FindUser(StatesGroup):
    waiting_query = State()


class GrantAccess(StatesGroup):
    waiting_duration = State()


class Broadcast(StatesGroup):
    waiting_message = State()


# --- Flexible duration parsing (admin grant) -------------------------------

_DUR_RE = re.compile(r"(\d+)\s*([a-zа-яё]*)", re.IGNORECASE)


def parse_duration(text: str) -> timedelta | None:
    """Parse a free-form duration into a timedelta.

    Accepts months / days / hours / minutes in RU or EN, combined freely; a bare
    number means days. Examples: ``30``, ``1 мес 10 дней``, ``12 часов``,
    ``90 мин``, ``2mo 5d 3h 30min``. Months are treated as 30 days.
    """
    total = timedelta()
    matched = False
    for num, unit in _DUR_RE.findall((text or "").strip().lower()):
        n = int(num)
        u = unit
        if u in ("", "д", "дн", "день", "дня", "дней", "d", "day", "days"):
            total += timedelta(days=n)
        elif u.startswith("мес") or u in ("mo", "mon", "month", "months"):
            total += timedelta(days=30 * n)
        elif u.startswith("час") or u in ("ч", "h", "hr", "hour", "hours"):
            total += timedelta(hours=n)
        elif u.startswith("мин") or u in ("min", "minute", "minutes", "m"):
            total += timedelta(minutes=n)
        else:
            return None  # unknown unit -> reject the whole input
        matched = True
    return total if matched and total > timedelta() else None


def fmt_duration(td: timedelta) -> str:
    total_min = int(td.total_seconds() // 60)
    days, rem = divmod(total_min, 24 * 60)
    hours, mins = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days} дн")
    if hours:
        parts.append(f"{hours} ч")
    if mins:
        parts.append(f"{mins} мин")
    return " ".join(parts) or "0 мин"


# --- Menu ------------------------------------------------------------------

@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🛠 <b>Админ-панель</b>", parse_mode="HTML", reply_markup=admin_menu())


BLOCK_TEXT = (
    "🚫 <b>Доступ приостановлен</b>\n\n"
    "Ваш доступ ограничен за нарушение\n"
    "условий использования ELMA.\n\n"
    "Причина: превышение лимита устройств.\n"
    "Максимум по тарифу — 5 устройств.\n\n"
    "Возврат средств и восстановление доступа\n"
    "не предусмотрены.\n\n"
    f"С вопросами: @{SUPPORT_USERNAME}"
)


@router.message(Command("block"))
async def cmd_block(message: Message) -> None:
    """Revoke access and send the block screen. Usage: /block <telegram_id>."""
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        await message.answer("Использование: <code>/block &lt;telegram_id&gt;</code>")
        return
    target = int(parts[1])
    sub = await revoke_subscription(target)
    if sub is not None:
        await subscription_service.deprovision(sub["panel_uuid"])
    await safe_send(message.bot, target, BLOCK_TEXT)
    await message.answer(f"🚫 Доступ пользователя {target} ограничен, он уведомлён.")


@router.callback_query(F.data == "admin:home")
async def cb_admin_home(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text(
        "🛠 <b>Админ-панель</b>", parse_mode="HTML", reply_markup=admin_menu()
    )
    await call.answer()


# --- Stats -----------------------------------------------------------------

@router.callback_query(F.data == "admin:stats")
async def cb_stats(call: CallbackQuery) -> None:
    s = await stats()
    text = (
        "📊 <b>Дашборд ELMA</b>\n\n"
        "👥 <b>Пользователи</b>\n"
        f"• Новые сегодня: <b>{s['users_today']}</b>\n"
        f"• Всего: <b>{s['users_total']}</b> (на связи: {s['users_reachable']})\n\n"
        "🚀 <b>Активации подписки</b> (вкл. триал)\n"
        f"• Всего активаций: <b>{s['activated_total']}</b>\n"
        f"• 🆓 Триал: <b>{s['trials_used']}</b>\n"
        f"• 💳 Купили: <b>{s['buyers']}</b>\n"
        f"• ✅ Активны сейчас: <b>{s['subs_active']}</b>\n\n"
        "💰 <b>Финансы</b> (все платёжные системы)\n"
        f"• Заработано сегодня: <b>{fmt_rub(s['revenue_today'])}</b>\n"
        f"• Всего: <b>{fmt_rub(s['revenue_total'])}</b>\n"
        f"• Платежей: <b>{s['payments_paid']}</b>"
    )
    await safe_edit(call.message, text, reply_markup=admin_dashboard_actions())
    await call.answer()


# --- Find user -------------------------------------------------------------

@router.callback_query(F.data == "admin:find")
async def cb_find(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FindUser.waiting_query)
    await call.message.edit_text(
        "👤 Пришлите <b>telegram_id</b> или <b>@username</b> пользователя.",
        parse_mode="HTML",
    )
    await call.answer()


@router.message(StateFilter(FindUser.waiting_query))
async def on_find_query(message: Message, state: FSMContext) -> None:
    await state.clear()
    query = (message.text or "").strip()
    user = None
    if query.lstrip("-").isdigit():
        user = await get_user(int(query))
    elif query.startswith("@") or query.isalnum():
        user = await find_user_by_username(query)

    if user is None:
        await message.answer("Пользователь не найден.", reply_markup=admin_menu())
        return

    await _show_user_card(message, user["telegram_id"])


async def _show_user_card(message: Message, telegram_id: int) -> None:
    user = await get_user(telegram_id)
    sub = await get_subscription(telegram_id)
    text = (
        f"👤 <b>{telegram_id}</b> (@{user['username'] or '—'})\n"
        f"Создан: {fmt_dt(user['created_at'])}\n"
        f"Триал: {fmt_dt(user['trial_used_at']) if user['trial_used_at'] else 'не использован'}\n"
        f"Доступен: {'да' if user['is_reachable'] else 'нет'}\n\n"
        + subscription_text(sub)
    )
    await message.answer(
        text, parse_mode="HTML", reply_markup=admin_user_actions(telegram_id)
    )


@router.callback_query(F.data.startswith("admin:card:"))
async def cb_card(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    target = int(call.data.split(":")[2])
    await _show_user_card(call.message, target)
    await call.answer()


@router.callback_query(F.data.startswith("admin:grant:"))
async def cb_grant(call: CallbackQuery, state: FSMContext) -> None:
    """Ask for a flexible duration; the grant itself happens on the reply."""
    target = int(call.data.split(":")[2])
    await state.set_state(GrantAccess.waiting_duration)
    await state.update_data(target=target)
    await call.message.edit_text(
        f"⏳ На какой срок выдать доступ пользователю <b>{target}</b>?\n\n"
        "Примеры: <code>30</code> (дней), <code>1 мес 10 дней</code>, "
        "<code>12 часов</code>, <code>90 мин</code>, <code>2mo 5d 3h</code>",
        parse_mode="HTML",
        reply_markup=admin_grant_cancel(target),
    )
    await call.answer()


@router.message(StateFilter(GrantAccess.waiting_duration))
async def on_grant_duration(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    target = data.get("target")
    delta = parse_duration(message.text or "")
    if target is None or delta is None:
        await message.answer(
            "Не понял срок. Примеры: <code>1 мес 10 дней</code>, <code>30</code>, "
            "<code>12 часов</code>, <code>90 мин</code>.",
            parse_mode="HTML",
        )
        return
    await state.clear()
    try:
        current = await get_subscription(target)
        new_expires = subscription_service.next_expiry_delta(current, delta)
        # create_or_renew provisions a new panel user if there was none, or
        # PATCHes the existing one's expiry — i.e. a clean extend/renew.
        await subscription_service.create_or_renew(target, new_expires, source="admin")
    except Exception:  # noqa: BLE001
        logger.exception("Admin grant failed for %s", target)
        await message.answer(
            "⚠️ Не удалось выдать доступ (панель недоступна?). Попробуйте ещё раз.",
            reply_markup=admin_menu(),
        )
        return

    human = fmt_duration(delta)
    renewed = current is not None and current["status"] == "active"
    await safe_send(
        message.bot,
        target,
        f"🎁 Тебе {'продлён' if renewed else 'выдан'} доступ к ELMA на {human}. "
        "Приятного пользования! ☁️",
    )
    await message.answer(
        f"✅ {'Продлено' if renewed else 'Выдано'}: <b>{human}</b>\n"
        f"📅 Новая дата окончания: <b>{fmt_dt(new_expires)}</b>",
        parse_mode="HTML",
    )
    await _show_user_card(message, target)


@router.callback_query(F.data.startswith("admin:revoke:"))
async def cb_revoke(call: CallbackQuery) -> None:
    target = int(call.data.split(":")[2])
    sub = await revoke_subscription(target)
    if sub is not None:
        await subscription_service.deprovision(sub["panel_uuid"])
        await safe_send(
            call.bot, target, "⛔️ Доступ к ELMA отключён."
        )
        await call.answer("Доступ отозван")
    else:
        await call.answer("У пользователя нет активного доступа", show_alert=True)
    await _show_user_card(call.message, target)


@router.callback_query(F.data.startswith("admin:history:"))
async def cb_history(call: CallbackQuery) -> None:
    target = int(call.data.split(":")[2])
    rows = await payment_history(target)
    if not rows:
        await call.answer("Платежей нет", show_alert=True)
        return
    lines = ["🧾 <b>История платежей</b>", ""]
    for r in rows:
        lines.append(
            f"{fmt_dt(r['created_at'])} — {r['amount_kopecks']}⭐ — {r['status']}"
        )
    await call.message.edit_text(
        "\n".join(lines), parse_mode="HTML", reply_markup=admin_user_actions(target)
    )
    await call.answer()


# --- Broadcast -------------------------------------------------------------

@router.callback_query(F.data == "admin:broadcast")
async def cb_broadcast(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text(
        "📢 Выберите сегмент рассылки:", reply_markup=admin_broadcast_segments()
    )
    await call.answer()


@router.callback_query(F.data.startswith("bcast:") & ~(F.data == "bcast:send"))
async def cb_segment(call: CallbackQuery, state: FSMContext) -> None:
    segment = call.data.split(":")[1]
    await state.update_data(segment=segment)
    await state.set_state(Broadcast.waiting_message)
    await call.message.edit_text(
        f"📢 Сегмент: <b>{segment}</b>\n\n{BROADCAST_HELP}",
        parse_mode="HTML",
    )
    await call.answer()


@router.message(StateFilter(Broadcast.waiting_message))
async def on_broadcast_message(message: Message, state: FSMContext) -> None:
    """Capture the broadcast content, render an HTML preview (which also
    validates the markup), and ask for confirmation."""
    photo_id = message.photo[-1].file_id if message.photo else None
    text = (message.caption if photo_id else message.text) or ""

    if not photo_id and not text.strip():
        await message.answer(
            "⚠️ Пустое сообщение. Пришлите текст или фото с подписью.\n\n"
            + BROADCAST_HELP
        )
        return

    # Preview = exactly what recipients will get. A bad HTML tag raises here
    # (shown to the admin) instead of failing for 50k users.
    try:
        if photo_id:
            await message.bot.send_photo(
                message.chat.id, photo_id, caption=text or None, parse_mode="HTML"
            )
        else:
            await message.bot.send_message(message.chat.id, text, parse_mode="HTML")
    except TelegramBadRequest as exc:
        await message.answer(
            "❌ <b>Ошибка в HTML-разметке:</b>\n"
            f"<code>{html.escape(str(exc))}</code>\n\n"
            "Исправьте теги и пришлите сообщение заново.",
            parse_mode="HTML",
        )
        return

    await state.update_data(photo_id=photo_id, text=text)
    data = await state.get_data()
    count = len(await recipients(data["segment"]))
    await message.answer(
        "👆 Так увидят получатели.\n\n"
        f"Сегмент: <b>{data['segment']}</b> · получателей: <b>{count}</b>.\n"
        "Отправить рассылку?",
        parse_mode="HTML",
        reply_markup=admin_broadcast_confirm(),
    )


@router.callback_query(F.data == "bcast:send")
async def cb_send_broadcast(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    if "segment" not in data or "text" not in data:
        await call.answer("Нет данных рассылки", show_alert=True)
        return
    await call.message.edit_text("📤 Рассылка запущена…")
    await call.answer()
    asyncio.create_task(
        _run_broadcast(
            call.bot,
            data["segment"],
            data.get("photo_id"),
            data["text"],
            call.from_user.id,
        )
    )


async def _run_broadcast(
    bot: Bot, segment: str, photo_id: str | None, text: str, admin_id: int
) -> None:
    ids = await recipients(segment)
    total = len(ids)

    async def send_one(uid: int) -> None:
        if photo_id:
            await bot.send_photo(
                uid, photo_id, caption=text or None, parse_mode="HTML"
            )
        else:
            await bot.send_message(uid, text, parse_mode="HTML")

    async def progress(res: broadcaster.BroadcastResult) -> None:
        await safe_send(
            bot,
            admin_id,
            f"📤 Рассылка: {res.processed}/{total} "
            f"(✅ {res.sent} · 🚫 {res.blocked} · ⚠️ {res.failed})",
        )

    res = await broadcaster.broadcast(ids, send_one, progress=progress)
    logger.info(
        "Broadcast '%s' done: %d sent, %d blocked, %d failed",
        segment, res.sent, res.blocked, res.failed,
    )
    await safe_send(
        bot,
        admin_id,
        "✅ <b>Рассылка завершена</b>\n\n"
        f"Всего: {total}\n"
        f"Доставлено: {res.sent}\n"
        f"Заблокировали бота: {res.blocked}\n"
        f"Ошибки: {res.failed}",
    )
