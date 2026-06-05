"""/help, subscription status and shared menu navigation.

The onboarding flow (/start, welcome, device screens) lives in
``app.handlers.onboarding``; this router keeps the cross-cutting bits that the
purchase/trial/admin screens link back to (``menu:home`` is owned by
onboarding).
"""
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.format import subscription_text
from app.keyboards import back_to_menu
from app.utils import safe_edit
from database import get_subscription

logger = logging.getLogger(__name__)
router = Router(name="common")

HELP = (
    "❓ <b>Помощь по ELMA VPN</b>\n\n"
    "• /start — забрать бесплатный доступ и подключить устройство.\n"
    "• /buy — тарифы и оплата (1 / 3 / 6 / 12 месяцев).\n"
    "• /invite — пригласить друзей и получить бонусные дни.\n"
    "• «🔗 Активировать ELMA VPN» — добавить подписку в приложение Happ.\n"
    "• «➕ Добавить устройство» — ссылка и QR-код для второго устройства.\n\n"
    "До 5 устройств: iOS, Android, MacOS, Windows, Android TV, Apple TV.\n\n"
    "Вопросы? Напиши в поддержку."
)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP, reply_markup=back_to_menu())


@router.callback_query(F.data == "menu:help")
async def cb_help(call: CallbackQuery) -> None:
    await safe_edit(call.message, HELP, reply_markup=back_to_menu())
    await call.answer()


@router.callback_query(F.data == "menu:connect")
async def cb_connect(call: CallbackQuery) -> None:
    sub = await get_subscription(call.from_user.id)
    await safe_edit(call.message, subscription_text(sub), reply_markup=back_to_menu())
    await call.answer()
