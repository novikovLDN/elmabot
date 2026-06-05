"""/start, /help, profile screen and main-menu navigation."""
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.format import subscription_text
from app.keyboards import back_to_menu, main_menu
from app.utils import safe_edit
from config import PRICE_STARS, SUBSCRIPTION_DAYS, TRIAL_DAYS
from database import get_subscription, trial_available, upsert_user

logger = logging.getLogger(__name__)
router = Router(name="common")

WELCOME = (
    "👋 <b>Добро пожаловать в Атлас Lite VPN!</b>\n\n"
    "Быстрый и безлимитный VPN на одном сервере. "
    f"Попробуйте бесплатно {TRIAL_DAYS} дня, затем "
    f"{PRICE_STARS}⭐ за {SUBSCRIPTION_DAYS} дней.\n\n"
    "Выберите действие:"
)

HELP = (
    "❓ <b>Помощь</b>\n\n"
    "• «📲 Подключить VPN» — ваша ссылка и статус подписки.\n"
    "• «🆓 Триал» — бесплатный доступ на 3 дня (один раз).\n"
    "• «💳 Купить» — оплата подписки звёздами Telegram.\n\n"
    "Скопируйте ссылку из раздела «Подключить VPN» и вставьте её в "
    "VPN-клиент (v2RayTun, Hiddify, Streisand).\n\n"
    "Вопросы? Напишите в поддержку."
)


async def _menu_markup(telegram_id: int):
    return main_menu(trial_available=await trial_available(telegram_id))


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user = message.from_user
    is_new = await upsert_user(user.id, user.username, user.language_code or "ru")
    if is_new:
        logger.info("New user onboarded: %s (@%s)", user.id, user.username)
    await message.answer(WELCOME, parse_mode="HTML", reply_markup=await _menu_markup(user.id))


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP, parse_mode="HTML", reply_markup=back_to_menu())


@router.callback_query(F.data == "menu:home")
async def cb_home(call: CallbackQuery) -> None:
    await safe_edit(call.message, WELCOME, reply_markup=await _menu_markup(call.from_user.id))
    await call.answer()


@router.callback_query(F.data == "menu:help")
async def cb_help(call: CallbackQuery) -> None:
    await safe_edit(call.message, HELP, reply_markup=back_to_menu())
    await call.answer()


@router.callback_query(F.data == "menu:connect")
async def cb_connect(call: CallbackQuery) -> None:
    sub = await get_subscription(call.from_user.id)
    await safe_edit(call.message, subscription_text(sub), reply_markup=back_to_menu())
    await call.answer()
