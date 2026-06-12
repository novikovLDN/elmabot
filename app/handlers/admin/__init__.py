"""Admin dashboard: stats, find user (grant/revoke/history), broadcast.

Access is gated by a router-level filter — only ADMIN_IDS reach any handler
here; everyone else falls through to the other routers.
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
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.format import fmt_dt, fmt_rub, subscription_text
from app.keyboards import (
    admin_broadcast_builder,
    admin_broadcast_segments,
    admin_dashboard_actions,
    admin_grant_cancel,
    admin_menu,
    admin_pager,
    admin_user_actions,
    broadcast_user_markup,
)
from app.services import broadcaster, subscription_service
from app.tariffs import get_tariff
from app.utils import safe_edit, safe_send
from config import ADMIN_IDS, REFERRAL_BONUS_DAYS, SUPPORT_USERNAME
from database import (
    ACTIVITY_WINDOWS,
    REVENUE_WINDOWS,
    SEGMENTS,
    activity_windows,
    find_user_by_username,
    get_subscription,
    get_user,
    payment_history,
    payments_count,
    payments_page,
    recipients,
    referral_leaderboard,
    referral_leaderboard_count,
    referral_stats,
    revenue_windows,
    segment_count,
    revoke_subscription,
    stats,
)

logger = logging.getLogger(__name__)

router = Router(name="admin")
router.message.filter(F.from_user.id.in_(ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(ADMIN_IDS))

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
    waiting_discount_pct = State()
    waiting_discount_days = State()


class RefFind(StatesGroup):
    waiting_query = State()


PAGE_SIZE = 10

_PROVIDER_LABEL = {"sbp": "СБП", "card": "Карта", "stars": "Stars", "unknown": "—"}
_STATUS_LABEL = {
    "paid": "🟢 Успешно",
    "failed": "🔴 Ошибка",
    "pending": "🟡 Ожидает",
    "refunded": "↩️ Возврат",
}


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
    act = await activity_windows()
    rev = await revenue_windows()

    # New users / trial activations per window (24h / 7d / 30d).
    activity_lines = []
    for label, hours in ACTIVITY_WINDOWS:
        activity_lines.append(
            f"• {label}: 👥 {act[f'signup_{hours}']} · 🆓 {act[f'trial_{hours}']}"
        )

    # Revenue per window across all providers (true rubles).
    revenue_lines = []
    for label, days in REVENUE_WINDOWS:
        revenue_lines.append(
            f"• {label}: <b>{fmt_rub(rev[f'rev_{days}'])}</b> ({rev[f'cnt_{days}']} шт.)"
        )

    text = (
        "📊 <b>Дашборд ELMA</b>\n\n"
        "👥 <b>Пользователи</b>\n"
        f"• Новые сегодня: <b>{s['users_today']}</b>\n"
        f"• Всего: <b>{s['users_total']}</b> (на связи: {s['users_reachable']})\n\n"
        "📈 <b>Приходят / активируют триал</b> (👥 новые · 🆓 триал)\n"
        + "\n".join(activity_lines) + "\n\n"
        "🚀 <b>Активации подписки</b> (вкл. триал)\n"
        f"• Всего активаций: <b>{s['activated_total']}</b>\n"
        f"• 🆓 Триал всего: <b>{s['trials_used']}</b>\n"
        f"• 💳 Купили: <b>{s['buyers']}</b>\n"
        f"• ✅ Активны сейчас: <b>{s['subs_active']}</b>\n\n"
        "💰 <b>Выручка по периодам</b> (все платёжные системы)\n"
        + "\n".join(revenue_lines) + "\n"
        f"• <b>Всего:</b> <b>{fmt_rub(rev['rev_total'])}</b> ({rev['cnt_total']} платежей)"
    )
    await safe_edit(call.message, text, reply_markup=admin_dashboard_actions())
    await call.answer()


# --- Helpers ---------------------------------------------------------------

def _who(username: str | None, tg_id: int) -> str:
    return f"@{username}" if username else f"id{tg_id}"


async def _resolve_user(query: str):
    """Look up a user by telegram_id or @username (shared by the find screens)."""
    query = query.strip()
    if query.lstrip("-").isdigit():
        return await get_user(int(query))
    if query.startswith("@") or query.isalnum():
        return await find_user_by_username(query)
    return None


def _back_kb(*buttons: tuple[str, str]) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for text, cb in buttons:
        kb.button(text=text, callback_data=cb)
    kb.adjust(1)
    return kb


# --- Payments tab ----------------------------------------------------------

@router.callback_query(F.data.startswith("admin:pay:"))
async def cb_payments(call: CallbackQuery) -> None:
    page = max(0, int(call.data.rsplit(":", 1)[1]))
    total = await payments_count()
    offset = page * PAGE_SIZE
    rows = await payments_page(offset, PAGE_SIZE)

    if not rows:
        text = "💳 <b>Платежи</b>\n\nПока нет платежей."
    else:
        blocks = [f"💳 <b>Платежи</b> · {offset + 1}–{offset + len(rows)} из {total}"]
        for r in rows:
            status = _STATUS_LABEL.get(r["status"], r["status"])
            provider = _PROVIDER_LABEL.get(r["provider"], r["provider"] or "—")
            tariff = get_tariff(r["tariff_code"]) if r["tariff_code"] else None
            term = tariff.title if tariff else "—"
            who = _who(r["username"], r["telegram_id"])
            when = fmt_dt(r["paid_at"] or r["created_at"])
            block = (
                f"{status} · <b>{fmt_rub(r['amount_kopecks'])}</b> · {provider} · {term}\n"
                f"{html.escape(who)} · <code>{r['telegram_id']}</code> · {when}"
            )
            if r["status"] == "failed" and r["fail_reason"]:
                block += f"\n🔴 <i>{html.escape(r['fail_reason'])}</i>"
            blocks.append(block)
        text = "\n\n".join(blocks)

    await safe_edit(
        call.message,
        text,
        reply_markup=admin_pager(
            "admin:pay", page, has_prev=page > 0, has_next=offset + PAGE_SIZE < total
        ),
    )
    await call.answer()


# --- Referrals tab ---------------------------------------------------------

def _ref_block(r) -> str:
    earned = r["purchased"] * REFERRAL_BONUS_DAYS
    return (
        f"{html.escape(_who(r['username'], r['referrer_id']))} · "
        f"<code>{r['referrer_id']}</code>\n"
        f"  👥 приглашено: <b>{r['invited']}</b> · 💳 оплатили: "
        f"<b>{r['purchased']}</b> · 🎁 заработал: <b>{earned} дн.</b>"
    )


@router.callback_query(F.data.startswith("admin:ref:"))
async def cb_referrals(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    page = max(0, int(call.data.rsplit(":", 1)[1]))
    total = await referral_leaderboard_count()
    offset = page * PAGE_SIZE
    rows = await referral_leaderboard(offset, PAGE_SIZE)

    if not rows:
        text = "🫂 <b>Рефералы</b>\n\nПока никто никого не пригласил."
    else:
        head = (
            f"🫂 <b>Реферальная статистика</b> · {offset + 1}–{offset + len(rows)} из {total}\n"
            f"<i>+{REFERRAL_BONUS_DAYS} дн. за каждого оплатившего друга</i>"
        )
        text = head + "\n\n" + "\n\n".join(_ref_block(r) for r in rows)

    await safe_edit(
        call.message,
        text,
        reply_markup=admin_pager(
            "admin:ref",
            page,
            has_prev=page > 0,
            has_next=offset + PAGE_SIZE < total,
            extra=[("🔍 Найти пользователя", "admin:reffind")],
        ),
    )
    await call.answer()


@router.callback_query(F.data == "admin:reffind")
async def cb_ref_find(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(RefFind.waiting_query)
    await call.message.edit_text(
        "🔍 <b>Реферальная статистика пользователя</b>\n\n"
        "Пришлите <b>telegram_id</b> или <b>@username</b> — покажу только его "
        "реферальную статистику.\n\n"
        "<i>Это отдельный поиск: основной поиск пользователя в дашборде он не "
        "затрагивает.</i>",
        parse_mode="HTML",
        reply_markup=_back_kb(("⬅️ К рефералам", "admin:ref:0")).as_markup(),
    )
    await call.answer()


@router.message(StateFilter(RefFind.waiting_query))
async def on_ref_find(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await _resolve_user(message.text or "")
    back = _back_kb(
        ("⬅️ К рефералам", "admin:ref:0"), ("🏠 Админка", "admin:home")
    ).as_markup()
    if user is None:
        await message.answer("Пользователь не найден.", reply_markup=back)
        return
    rs = await referral_stats(user["telegram_id"])
    earned = rs["purchased"] * REFERRAL_BONUS_DAYS
    await message.answer(
        "🫂 <b>Реферальная статистика</b>\n\n"
        f"{html.escape(_who(user['username'], user['telegram_id']))} · "
        f"<code>{user['telegram_id']}</code>\n\n"
        f"👥 Приглашено: <b>{rs['invited']}</b>\n"
        f"💳 Оплатили: <b>{rs['purchased']}</b>\n"
        f"🎁 Заработал: <b>{earned} дн.</b>",
        parse_mode="HTML",
        reply_markup=back,
    )


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
        status = _STATUS_LABEL.get(r["status"], r["status"])
        lines.append(
            f"{fmt_dt(r['created_at'])} — {fmt_rub(r['amount_kopecks'])} — {status}"
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
        "📢 <b>Рассылка</b>\n\nВыберите сегмент получателей 👇\n\n"
        "<i>На следующем шаге пришлёте сообщение и при желании добавите кнопки "
        "(скидка / канал).</i>",
        parse_mode="HTML",
        reply_markup=admin_broadcast_segments(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("bcast:") & ~(F.data == "bcast:send"))
async def cb_segment(call: CallbackQuery, state: FSMContext) -> None:
    segment = call.data.split(":")[1]
    if segment not in SEGMENTS:
        await call.answer()
        return
    label = SEGMENTS[segment][0]
    count = await segment_count(segment)
    await state.update_data(
        segment=segment, disc_pct=None, disc_days=None, channel=False
    )
    await state.set_state(Broadcast.waiting_message)
    await call.message.edit_text(
        f"📢 Сегмент: <b>{label}</b> · получателей: <b>{count}</b>\n\n{BROADCAST_HELP}",
        parse_mode="HTML",
    )
    await call.answer()


async def _builder_view(state: FSMContext) -> tuple[str, object]:
    """Text + keyboard for the compose step (after the message is captured)."""
    data = await state.get_data()
    label = SEGMENTS.get(data["segment"], (data["segment"],))[0]
    count = await segment_count(data["segment"])
    lines = [
        "📢 <b>Готово к отправке</b>",
        f"Сегмент: <b>{label}</b> · получателей: <b>{count}</b>",
        "",
    ]
    if data.get("disc_pct"):
        lines.append(
            f"🔥 Кнопка скидки: <b>−{data['disc_pct']}%</b> на {data['disc_days']} дн."
        )
    if data.get("channel"):
        lines.append("📣 Кнопка «Перейти в канал»: <b>вкл.</b>")
    lines.append("")
    lines.append(
        "<i>Добавьте кнопки к сообщению (по желанию) и нажмите «Отправить». "
        "Скидка применится ко всем тарифам у того, кто нажмёт кнопку.</i>"
    )
    markup = admin_broadcast_builder(
        disc_pct=data.get("disc_pct"),
        disc_days=data.get("disc_days"),
        channel=data.get("channel", False),
    )
    return "\n".join(lines), markup


@router.message(StateFilter(Broadcast.waiting_message))
async def on_broadcast_message(message: Message, state: FSMContext) -> None:
    """Capture the broadcast content, render an HTML preview (which also
    validates the markup), then open the button builder."""
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
    await state.set_state(None)  # button builder is callback-driven
    body, markup = await _builder_view(state)
    await message.answer("👆 Так увидят получатели.\n\n" + body, reply_markup=markup)


@router.callback_query(F.data == "bcastbtn:disc")
async def cb_btn_discount(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Broadcast.waiting_discount_pct)
    await call.message.edit_text(
        "💸 <b>Кнопка «Купить со скидкой»</b>\n\n"
        "Введите <b>размер скидки в процентах</b> (1–99).\n"
        "Например: <code>20</code>\n\n"
        "<i>Скидка применится ко всем тарифам у пользователя, который нажмёт "
        "кнопку.</i>",
        parse_mode="HTML",
    )
    await call.answer()


@router.message(StateFilter(Broadcast.waiting_discount_pct))
async def on_discount_pct(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip().rstrip("%")
    if not raw.isdigit() or not (0 < int(raw) < 100):
        await message.answer("⚠️ Нужно целое число 1–99. Попробуйте ещё раз.")
        return
    await state.update_data(disc_pct=int(raw))
    await state.set_state(Broadcast.waiting_discount_days)
    await message.answer(
        "📅 Теперь введите, <b>на сколько дней</b> действует скидка (1–365).\n"
        "Например: <code>3</code>",
        parse_mode="HTML",
    )


@router.message(StateFilter(Broadcast.waiting_discount_days))
async def on_discount_days(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or not (0 < int(raw) <= 365):
        await message.answer("⚠️ Нужно целое число 1–365. Попробуйте ещё раз.")
        return
    await state.update_data(disc_days=int(raw))
    await state.set_state(None)
    body, markup = await _builder_view(state)
    await message.answer(body, reply_markup=markup)


@router.callback_query(F.data == "bcastbtn:chan")
async def cb_btn_channel(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(channel=not data.get("channel", False))
    body, markup = await _builder_view(state)
    await safe_edit(call.message, body, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data == "bcast:send")
async def cb_send_broadcast(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    if "segment" not in data or "text" not in data:
        await call.answer("Нет данных рассылки", show_alert=True)
        return
    markup = broadcast_user_markup(
        data.get("disc_pct"), data.get("disc_days"), data.get("channel", False)
    )
    await call.message.edit_text("📤 Рассылка запущена…")
    await call.answer()
    asyncio.create_task(
        _run_broadcast(
            call.bot,
            data["segment"],
            data.get("photo_id"),
            data["text"],
            call.from_user.id,
            markup,
        )
    )


async def _run_broadcast(
    bot: Bot,
    segment: str,
    photo_id: str | None,
    text: str,
    admin_id: int,
    markup=None,
) -> None:
    ids = await recipients(segment)
    total = len(ids)

    async def send_one(uid: int) -> None:
        if photo_id:
            await bot.send_photo(
                uid, photo_id, caption=text or None, parse_mode="HTML",
                reply_markup=markup,
            )
        else:
            await bot.send_message(
                uid, text, parse_mode="HTML", reply_markup=markup
            )

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
