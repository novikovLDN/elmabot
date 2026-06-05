"""Admin dashboard: stats, find user (grant/revoke/history), broadcast.

Access is gated by a router-level filter — only ADMIN_TELEGRAM_ID reaches any
handler here; everyone else falls through to the other routers.
"""
import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.format import fmt_dt, subscription_text
from app.keyboards import (
    admin_broadcast_confirm,
    admin_broadcast_segments,
    admin_menu,
    admin_user_actions,
)
from app.services import access
from app.utils import safe_send
from config import ADMIN_TELEGRAM_ID, PRICE_STARS
from database import (
    find_user_by_username,
    get_subscription,
    get_user,
    grant_days,
    mark_unreachable,
    payment_history,
    recipients,
    revoke_subscription,
    stats,
)

logger = logging.getLogger(__name__)

router = Router(name="admin")
router.message.filter(F.from_user.id == ADMIN_TELEGRAM_ID)
router.callback_query.filter(F.from_user.id == ADMIN_TELEGRAM_ID)

ADMIN_GRANT_DAYS = 30

# Broadcast tuning (§9): stay under Telegram's ~30 msg/s.
BROADCAST_CONCURRENCY = 15
BROADCAST_BATCH = 200
BROADCAST_PAUSE = 2.0


class FindUser(StatesGroup):
    waiting_query = State()


class Broadcast(StatesGroup):
    waiting_message = State()


# --- Menu ------------------------------------------------------------------

@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🛠 <b>Админ-панель</b>", parse_mode="HTML", reply_markup=admin_menu())


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
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: <b>{s['users_total']}</b> "
        f"(доступны: {s['users_reachable']})\n"
        f"🆓 Использовали триал: <b>{s['trials_used']}</b>\n"
        f"✅ Активных подписок: <b>{s['subs_active']}</b>\n"
        f"💳 Платежей: <b>{s['payments_paid']}</b>\n"
        f"⭐ Выручка: <b>{s['revenue_total']}</b>\n"
        f"📈 MRR (оценка): <b>{s['subs_active'] * PRICE_STARS}</b> ⭐"
    )
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=admin_menu())
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


@router.callback_query(F.data.startswith("admin:grant:"))
async def cb_grant(call: CallbackQuery) -> None:
    target = int(call.data.split(":")[2])
    try:
        await grant_days(
            target,
            ADMIN_GRANT_DAYS,
            source="admin_grant",
            provision=access.extend_provision(target),
        )
    except Exception:  # noqa: BLE001
        logger.exception("Admin grant failed for %s", target)
        await call.answer("Ошибка выдачи доступа", show_alert=True)
        return
    await call.answer(f"Выдано {ADMIN_GRANT_DAYS} дней")
    await safe_send(
        call.bot, target, f"🎁 Вам выдан VPN-доступ на {ADMIN_GRANT_DAYS} дней!"
    )
    await _show_user_card(call.message, target)


@router.callback_query(F.data.startswith("admin:revoke:"))
async def cb_revoke(call: CallbackQuery) -> None:
    target = int(call.data.split(":")[2])
    sub = await revoke_subscription(target)
    if sub is not None:
        await access.deprovision(sub["vpn_uuid"])
    await call.answer("Доступ отозван")
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
        f"Сегмент: <b>{segment}</b>\n\n"
        "Пришлите сообщение (текст или фото с подписью), которое нужно разослать.",
        parse_mode="HTML",
    )
    await call.answer()


@router.message(StateFilter(Broadcast.waiting_message))
async def on_broadcast_message(message: Message, state: FSMContext) -> None:
    await state.update_data(src_chat=message.chat.id, src_msg=message.message_id)
    data = await state.get_data()
    count = len(await recipients(data["segment"]))
    await message.answer(
        f"Получателей в сегменте <b>{data['segment']}</b>: <b>{count}</b>.\n"
        "Отправить рассылку?",
        parse_mode="HTML",
        reply_markup=admin_broadcast_confirm(),
    )


@router.callback_query(F.data == "bcast:send")
async def cb_send_broadcast(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    if "segment" not in data or "src_msg" not in data:
        await call.answer("Нет данных рассылки", show_alert=True)
        return
    await call.message.edit_text("📤 Рассылка запущена…")
    await call.answer()
    asyncio.create_task(
        _run_broadcast(
            call.bot,
            data["segment"],
            data["src_chat"],
            data["src_msg"],
            call.from_user.id,
        )
    )


async def _run_broadcast(
    bot: Bot, segment: str, src_chat: int, src_msg: int, admin_id: int
) -> None:
    ids = await recipients(segment)
    sem = asyncio.Semaphore(BROADCAST_CONCURRENCY)
    sent = 0
    failed = 0

    async def _one(uid: int) -> bool:
        async with sem:
            try:
                await bot.copy_message(
                    chat_id=uid, from_chat_id=src_chat, message_id=src_msg
                )
                return True
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after)
                try:
                    await bot.copy_message(
                        chat_id=uid, from_chat_id=src_chat, message_id=src_msg
                    )
                    return True
                except Exception:  # noqa: BLE001
                    return False
            except TelegramForbiddenError:
                await mark_unreachable(uid)
                return False
            except Exception:  # noqa: BLE001
                logger.exception("Broadcast send failed for %s", uid)
                return False

    for i in range(0, len(ids), BROADCAST_BATCH):
        batch = ids[i : i + BROADCAST_BATCH]
        results = await asyncio.gather(
            *(_one(uid) for uid in batch), return_exceptions=True
        )
        for r in results:
            if r is True:
                sent += 1
            else:
                failed += 1
        await asyncio.sleep(BROADCAST_PAUSE)

    logger.info("Broadcast '%s' done: %d sent, %d failed", segment, sent, failed)
    await safe_send(
        bot, admin_id, f"✅ Рассылка завершена.\nОтправлено: {sent}\nОшибок: {failed}"
    )
