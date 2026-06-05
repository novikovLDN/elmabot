"""Tariff selection and purchase.

Payments are not wired yet: choosing a tariff shows its details and the
"Оплатить" button is a placeholder. When a provider is connected, the only
changes are inside ``cb_pay`` (create invoice) and ``on_paid`` (already routes
through ``billing.complete_purchase``).
"""
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, PreCheckoutQuery

from app import tariffs
from app.format import fmt_dt, subscription_text
from app.keyboards import back_to_menu, tariff_detail_keyboard, tariffs_keyboard
from app.services import billing, discounts, payments
from app.utils import safe_edit, safe_send
from database import get_user, is_payment_paid, mark_payment_refunded

logger = logging.getLogger(__name__)
router = Router(name="purchase")


async def _tariffs_view(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    user = await get_user(user_id)
    offer = discounts.active_offer(user)

    lines = [
        "💳 <b>Тарифы ELMA VPN</b>",
        "",
        "Безлимит, до 5 устройств, zero-logs — на всех устройствах семьи.",
    ]
    if offer:
        lines += [
            "",
            f"🎁 Тебе доступна {offer.reason}: <b>−{offer.pct}%</b> "
            f"(до {fmt_dt(offer.expires_at)})",
        ]
    lines += ["", "Выбери срок 👇"]

    rows: list[tuple[str, str]] = []
    for t in tariffs.TARIFFS:
        final = discounts.apply(t.price_rub, offer)
        label = f"{t.title} — {final} ₽"
        if offer and final != t.price_rub:
            label += " ⚡"
        elif t.save_label:
            label += f" · {t.save_label}"
        rows.append((f"buy:tariff:{t.code}", label))

    return "\n".join(lines), tariffs_keyboard(rows)


@router.message(Command("buy"))
async def cmd_buy(message: Message) -> None:
    text, markup = await _tariffs_view(message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "menu:buy")
async def cb_buy(call: CallbackQuery) -> None:
    text, markup = await _tariffs_view(call.from_user.id)
    await safe_edit(call.message, text, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data.startswith("buy:tariff:"))
async def cb_tariff(call: CallbackQuery) -> None:
    code = call.data.split(":")[2]
    tariff = tariffs.get_tariff(code)
    if tariff is None:
        await call.answer()
        return
    user = await get_user(call.from_user.id)
    offer = discounts.active_offer(user)
    final = discounts.apply(tariff.price_rub, offer)

    price_line = f"Цена: <b>{tariff.price_rub} ₽</b>"
    if tariff.save_label:
        price_line += f" ({tariff.save_label})"
    if offer and final != tariff.price_rub:
        price_line = (
            f"Цена: <s>{tariff.price_rub} ₽</s> → <b>{final} ₽</b> "
            f"(−{offer.pct}%, {offer.reason})"
        )

    text = (
        f"💳 <b>{tariff.title}</b>\n\n"
        f"Срок: {tariff.months} мес ({tariff.days} дней)\n"
        f"{price_line}\n"
        "Безлимитный трафик, до 5 устройств, zero-logs.\n\n"
        "Нажми «Оплатить», чтобы продолжить 👇"
    )
    await safe_edit(call.message, text, reply_markup=tariff_detail_keyboard(code))
    await call.answer()


@router.callback_query(F.data.startswith("buy:pay:"))
async def cb_pay(call: CallbackQuery) -> None:
    """Placeholder — the payment provider is not connected yet."""
    code = call.data.split(":")[2]
    tariff = tariffs.get_tariff(code)
    if tariff is None:
        await call.answer()
        return
    user = await get_user(call.from_user.id)
    final = discounts.apply(tariff.price_rub, discounts.active_offer(user))
    await safe_edit(
        call.message,
        f"💳 <b>Оплата тарифа «{tariff.title}» — {final} ₽</b>\n\n"
        "⏳ Приём платежей скоро подключим. Загляни чуть позже 🙌",
        reply_markup=back_to_menu(),
    )
    await call.answer()


# --- Payment provider hooks (ready, currently unused) ---------------------

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

    if await is_payment_paid(invoice_id):
        logger.info("Invoice %s already processed; skipping", invoice_id)
        return

    parsed = payments.parse_payload(invoice_id)
    tariff = tariffs.get_tariff(parsed["tariff_code"]) if parsed else None
    if tariff is None:
        tariff = tariffs.TARIFFS[0]  # defensive fallback

    # Provision first; mark paid only on success — refund on failure so the rule
    # "paid -> served OR refunded" always holds.
    try:
        sub = await billing.complete_purchase(
            message.bot,
            user_id,
            tariff,
            invoice_id=invoice_id,
            amount_paid=sp.total_amount,
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
            "⚠️ Не удалось выдать доступ, средства возвращены. "
            "Попробуй оплатить ещё раз позже.",
        )
        return

    logger.info("Payment processed for %s (%s)", user_id, tariff.code)
    await message.answer(
        "✅ <b>Оплата прошла, подписка активна!</b>\n\n" + subscription_text(sub),
        parse_mode="HTML",
        reply_markup=back_to_menu(),
    )
