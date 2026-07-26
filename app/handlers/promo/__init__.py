"""Promo-code redemption: /promo, the menu button, and /start promo_<code>.

A code gives either bonus subscription days or a personal discount. Discounts
land the user on the tariff screen with the price already reduced.
"""
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.services import promo_service
from app.utils import safe_edit

logger = logging.getLogger(__name__)
router = Router(name="promo")


class PromoStates(StatesGroup):
    waiting_code = State()


PROMPT = (
    "🎟 <b>Промокод</b>\n\n"
    "Пришли код одним сообщением — активирую скидку или бонусные дни."
)


def _result_kb(show_buy: bool):
    kb = InlineKeyboardBuilder()
    if show_buy:
        kb.button(text="Выбрать тариф", callback_data="menu:buy")
    kb.button(text="🏠 Главное меню", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


async def _redeem(bot, user_id: int, code: str) -> tuple[str, object]:
    ok, message, show_buy = await promo_service.apply_promo(bot, user_id, code)
    return message, _result_kb(show_buy and ok)


@router.message(Command("promo"))
async def cmd_promo(message: Message, command: CommandObject, state: FSMContext) -> None:
    arg = (command.args or "").strip()
    if arg:
        text, kb = await _redeem(message.bot, message.from_user.id, arg)
        await message.answer(text, reply_markup=kb)
        return
    await state.set_state(PromoStates.waiting_code)
    await message.answer(PROMPT)


@router.callback_query(F.data == "promo:enter")
async def cb_promo_enter(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PromoStates.waiting_code)
    await safe_edit(call.message, PROMPT, reply_markup=None)
    await call.answer()


@router.message(StateFilter(PromoStates.waiting_code))
async def on_promo_code(message: Message, state: FSMContext) -> None:
    await state.clear()
    text, kb = await _redeem(message.bot, message.from_user.id, message.text or "")
    await message.answer(text, reply_markup=kb)
