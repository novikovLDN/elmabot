"""Gift a subscription.

Flow: intro → pick a tariff → payment screen (СБП / Карта). Payments are not
wired yet, so the method buttons land on a placeholder. Once a provider is
connected, the success handler calls ``billing.create_gift_code`` and shows the
one-time gift link (recipient activates via ``?start=gift_<code>``).
"""
import logging

from aiogram import F, Router
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import CallbackQuery

from app import tariffs
from app.keyboards import back_to_menu, payment_methods_keyboard
from app.utils import safe_edit

logger = logging.getLogger(__name__)
router = Router(name="gift")

INTRO = (
    "🎁 <b>Подарить ELMA VPN</b>\n\n"
    "Стабильный интернет без нервов —\n"
    "лучшая забота о близких.\n\n"
    "Выбери тариф → оплати →\n"
    "получатель нажмёт ссылку и всё заработает."
)


@router.callback_query(F.data == "gift:open")
async def cb_gift(call: CallbackQuery) -> None:
    kb = InlineKeyboardBuilder()
    kb.button(text="📅 Выбрать срок", callback_data="gift:tariffs")
    kb.button(text="🔙 Назад", callback_data="menu:main")
    kb.adjust(1)
    await safe_edit(call.message, INTRO, reply_markup=kb.as_markup())
    await call.answer()


@router.callback_query(F.data == "gift:tariffs")
async def cb_gift_tariffs(call: CallbackQuery) -> None:
    kb = InlineKeyboardBuilder()
    for t in tariffs.TARIFFS:
        label = f"🗝️ {t.title} — {t.price_rub} ₽"
        if t.save_label:
            label += f"  {t.save_label}"
        kb.button(text=label, callback_data=f"gift:tariff:{t.code}")
    kb.button(text="🔙 Назад", callback_data="gift:open")
    kb.adjust(1)
    await safe_edit(
        call.message,
        "🎁 <b>Подарок ELMA VPN</b>\n\nВыбери период 👇",
        reply_markup=kb.as_markup(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("gift:tariff:"))
async def cb_gift_tariff(call: CallbackQuery) -> None:
    code = call.data.split(":")[2]
    tariff = tariffs.get_tariff(code)
    if tariff is None:
        await call.answer()
        return
    text = (
        "⭐️ <b>Оформление подарка ELMA VPN</b>\n\n"
        f"💰 Стоимость: {tariff.price_rub} ₽\n"
        f"📅 Период: {tariff.title}\n"
        "🌐 Устройств: до 5\n\n"
        "Как оплатить? 👇"
    )
    await safe_edit(
        call.message,
        text,
        reply_markup=payment_methods_keyboard(
            code, back_data="gift:tariffs", prefix="giftpay"
        ),
    )
    await call.answer()


@router.callback_query(F.data.startswith("giftpay:"))
async def cb_gift_pay(call: CallbackQuery) -> None:
    """Placeholder — the payment provider is not connected yet."""
    code = call.data.split(":")[2]
    tariff = tariffs.get_tariff(code)
    if tariff is None:
        await call.answer()
        return
    await safe_edit(
        call.message,
        f"🎁 <b>Оплата подарка «{tariff.title}» — {tariff.price_rub} ₽</b>\n\n"
        "⏳ Приём платежей скоро подключим. Загляни чуть позже 🙌",
        reply_markup=back_to_menu(),
    )
    await call.answer()
