"""Gift a subscription.

Flow: intro → pick a tariff → order-confirmation screen → «Оплатить» opens
Platega's hosted page. The webhook (billing.finalize_confirmed_payment, gift
branch) settles the payment, then billing.complete_gift_purchase issues a
one-time code and sends the buyer a forwardable link. The recipient activates
the gifted tariff (for its full period) via ``?start=gift_<code>``.
"""
import logging

import httpx
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from app import emoji, tariffs
from app.keyboards import back_to_menu
from app.services import platega
from app.utils import clean_username, safe_edit
from database import create_pending_payment

logger = logging.getLogger(__name__)
router = Router(name="gift")

INTRO = (
    "🎁 <b>Подари ELMA близкому человеку</b>\n\n"
    "Стабильный интернет без обрывов —\n"
    "лучший подарок для тех, кто важен 🫂❤️\n\n"
    "Выбери тариф → оплати → отправь ссылку.\n"
    "Получатель нажмёт — и всё заработает ⚡️"
)


def _intro_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Выбрать срок", callback_data="gift:tariffs",
              style="success", icon_custom_emoji_id=emoji.CALENDAR)
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


@router.message(Command("gift"))
async def cmd_gift(message: Message) -> None:
    await message.answer(INTRO, reply_markup=_intro_kb())


@router.callback_query(F.data == "gift:open")
async def cb_gift(call: CallbackQuery) -> None:
    await safe_edit(call.message, INTRO, reply_markup=_intro_kb())
    await call.answer()


@router.callback_query(F.data == "gift:tariffs")
async def cb_gift_tariffs(call: CallbackQuery) -> None:
    kb = InlineKeyboardBuilder()
    for t in tariffs.TARIFFS:
        label = f"🗝️ {t.title} — {t.price_rub} ₽"
        if t.save_label:
            label += f"  {t.save_label}"
        kb.button(text=label, callback_data=f"gift:tariff:{t.code}", style="success")
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data="gift:open")
    kb.adjust(1)
    await safe_edit(
        call.message,
        "🎁 <b>Подарок ELMA</b>\n\nВыбери период 👇",
        reply_markup=kb.as_markup(),
    )
    await call.answer()


def _gift_order_kb(*, pay_url: str | None, final: int | None = None) -> InlineKeyboardMarkup:
    """Order-confirmation buttons: «Оплатить» opens Platega's hosted page (all
    enabled methods), «Поддержка» → support chat, «Назад» → tariff list."""
    kb = InlineKeyboardBuilder()
    if pay_url:
        kb.button(text=f"Оплатить {final} ₽", url=pay_url, style="success")
    kb.button(text="Поддержка", url=config.SUPPORT_URL, style="primary")
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data="gift:tariffs")
    kb.adjust(1)
    return kb.as_markup()


@router.callback_query(F.data.startswith("gift:tariff:"))
async def cb_gift_tariff(call: CallbackQuery) -> None:
    """Order-confirmation for a gift. «Оплатить» opens Platega's hosted page
    directly, so we create the transaction here (tariff_code ``gf_<code>`` so the
    webhook routes it to the gift branch) and hand back a ready pay link."""
    code = call.data.split(":")[2]
    tariff = tariffs.get_tariff(code)
    if tariff is None:
        await call.answer()
        return

    order = (
        "🎁 <b>Проверьте заказ подарка</b>\n\n"
        f"• Период: {tariff.title}\n"
        f"• Итого: {tariff.price_rub} ₽\n\n"
        "После оплаты вы получите ссылку-подарок — перешлите её тому, кому "
        "дарите. Он активирует подписку в один тап."
    )

    if not config.PAYMENTS_ENABLED:
        await safe_edit(
            call.message,
            order + "\n\n⏳ Приём платежей скоро подключим. Загляни чуть позже 🙌",
            reply_markup=_gift_order_kb(pay_url=None),
        )
        await call.answer()
        return

    await call.answer("Готовлю оплату…")
    uname = clean_username(call.from_user.username)
    try:
        # No method -> the payer picks it on the Platega page.
        txn = await platega.create_transaction(
            amount_rub=float(tariff.price_rub),
            description=f"Подарок ELMA — {tariff.title}",
            payload=f"gift:{call.from_user.id}",
            user_id=call.from_user.id,
            user_name=f"@{uname}" if uname else None,
        )
    except (httpx.HTTPError, KeyError, ValueError):
        logger.exception("Platega gift create_transaction failed for %s", call.from_user.id)
        await safe_edit(
            call.message,
            "⚠️ Не удалось создать платёж. Попробуй ещё раз через минуту 🙏",
            reply_markup=back_to_menu(),
        )
        return

    txn_id = txn.get("transactionId")
    pay_url = platega.pay_url(txn)
    if not txn_id or not pay_url:
        logger.error("Platega gift response missing fields: %s", txn)
        await safe_edit(
            call.message,
            "⚠️ Не удалось создать платёж. Попробуй ещё раз через минуту 🙏",
            reply_markup=back_to_menu(),
        )
        return

    # Journal pending BEFORE the user can pay so the webhook can resolve it. The
    # gf_ prefix routes finalize to the gift branch (issue code + send link),
    # never to the buyer's own subscription.
    await create_pending_payment(
        call.from_user.id, txn_id, tariff.price_rub * 100,  # kopecks
        provider="platega", tariff_code=f"gf_{code}",
        confirm_message_id=call.message.message_id,
    )
    await safe_edit(
        call.message, order,
        reply_markup=_gift_order_kb(pay_url=pay_url, final=tariff.price_rub),
    )
