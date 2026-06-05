"""Purchase / renewal via Telegram Stars."""
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery

from app.format import subscription_text
from app.keyboards import back_to_menu, buy_keyboard
from app.services import access, payments
from app.utils import safe_edit, safe_send
from config import PRICE_STARS, SUBSCRIPTION_DAYS
from database import (
    create_pending_payment,
    grant_days,
    mark_payment_refunded,
)

logger = logging.getLogger(__name__)
router = Router(name="purchase")

BUY_SCREEN = (
    "💳 <b>Подписка ELMA VPN</b>\n\n"
    f"• Срок: {SUBSCRIPTION_DAYS} дней\n"
    f"• Цена: {PRICE_STARS} ⭐ (Telegram Stars)\n"
    "• Безлимитный трафик, до 5 устройств.\n\n"
    "Если доступ ещё активен — дни прибавятся к текущему сроку."
)


@router.callback_query(F.data == "menu:buy")
async def cb_buy(call: CallbackQuery) -> None:
    await safe_edit(call.message, BUY_SCREEN, reply_markup=buy_keyboard())
    await call.answer()


@router.callback_query(F.data == "buy:invoice")
async def cb_invoice(call: CallbackQuery) -> None:
    await call.answer()
    user_id = call.from_user.id
    payload = payments.make_payload(user_id)
    # Journal as 'pending' before showing the invoice (§5.3).
    await create_pending_payment(user_id, payload, PRICE_STARS)
    await payments.send_subscription_invoice(call.bot, user_id, payload)


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery) -> None:
    # Always approve — Stars are charged only after this ok.
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def on_paid(message: Message) -> None:
    sp = message.successful_payment
    user_id = message.from_user.id
    invoice_id = sp.invoice_payload
    charge_id = sp.telegram_payment_charge_id

    # Mark-paid + VPN provisioning happen in one DB transaction. If the panel
    # is down, grant_days raises, the transaction rolls back, the payment stays
    # 'pending' — and we refund the Stars so "paid -> served OR refunded".
    try:
        sub = await grant_days(
            user_id,
            SUBSCRIPTION_DAYS,
            source="payment",
            provision=access.extend_provision(user_id),
            invoice_id=invoice_id,
            amount=sp.total_amount,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Provisioning failed after payment by %s; refunding", user_id)
        try:
            await payments.refund(message.bot, user_id, charge_id)
            await mark_payment_refunded(invoice_id)
        except Exception:  # noqa: BLE001
            logger.exception("Refund failed for %s charge %s", user_id, charge_id)
        await safe_send(
            message.bot,
            user_id,
            "⚠️ Не удалось выдать доступ, звёзды возвращены. "
            "Попробуйте оплатить ещё раз позже.",
        )
        return

    logger.info("Payment processed for %s (+%d days)", user_id, SUBSCRIPTION_DAYS)
    await message.answer(
        "✅ <b>Оплата прошла, подписка продлена!</b>\n\n" + subscription_text(sub),
        parse_mode="HTML",
        reply_markup=back_to_menu(),
    )
