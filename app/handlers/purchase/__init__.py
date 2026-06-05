"""Tariff selection and purchase (ELMA Plus).

Payments are not wired yet: choosing a tariff opens the payment screen (СБП /
Карта), but the method buttons land on a placeholder. When a provider is
connected, the only changes are inside ``cb_method`` (create invoice) and
``on_paid`` (already routes through ``billing.complete_purchase``).
"""
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, PreCheckoutQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import tariffs
from app.format import fmt_date
from app.keyboards import back_to_menu, payment_methods_keyboard, tariffs_keyboard
from app.services import billing, discounts, payments
from app.utils import safe_edit, safe_send
from database import get_user, is_payment_paid, mark_payment_refunded

logger = logging.getLogger(__name__)
router = Router(name="purchase")

PLUS_HEADER = (
    "👑 <b>ELMA Plus</b>\n\n"
    "Один тариф — всё включено.\n\n"
    "⚡️ Скорость без лагов и буферов\n"
    "👨‍👩‍👧‍👦 До 5 устройств одновременно\n"
    "🔒 Zero-logs — твои данные только твои"
)


async def _tariffs_view(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    user = await get_user(user_id)
    offer = discounts.active_offer(user)

    lines = [PLUS_HEADER]
    if offer:
        lines.append(
            f"\n🎁 Тебе доступна {offer.reason}: <b>−{offer.pct}%</b> "
            f"(до {fmt_date(offer.expires_at)})"
        )
    lines.append("\nВыбери период 👇")

    rows: list[tuple[str, str]] = []
    for t in tariffs.TARIFFS:
        final = discounts.apply(t.price_rub, offer)
        label = f"🗝️ {t.title} — {final} ₽"
        if offer and final != t.price_rub:
            label += " ⚡"
        elif t.save_label:
            label += f"  {t.save_label}"
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
    """Show the payment screen (СБП / Карта) for the chosen tariff."""
    code = call.data.split(":")[2]
    tariff = tariffs.get_tariff(code)
    if tariff is None:
        await call.answer()
        return
    user = await get_user(call.from_user.id)
    offer = discounts.active_offer(user)
    final = discounts.apply(tariff.price_rub, offer)

    if offer and final != tariff.price_rub:
        price = f"<s>{tariff.price_rub} ₽</s> {final} ₽ (−{offer.pct}%)"
    else:
        price = f"{final} ₽"

    text = (
        "⭐️ <b>Оформление подписки ELMA VPN</b>\n\n"
        f"💰 Стоимость: {price}\n"
        f"📅 Период: {tariff.title}\n"
        "🌐 Устройств: до 5\n\n"
        "Предупредим за 3 дня до окончания —\n"
        "ничего не пропустишь.\n\n"
        "Как оплатить? 👇"
    )
    await safe_edit(
        call.message,
        text,
        reply_markup=payment_methods_keyboard(code, back_data="menu:buy"),
    )
    await call.answer()


@router.callback_query(F.data.startswith("pay:"))
async def cb_method(call: CallbackQuery) -> None:
    """Placeholder — the payment provider (СБП / Карта) is not connected yet."""
    code = call.data.split(":")[2]
    tariff = tariffs.get_tariff(code)
    if tariff is None:
        await call.answer()
        return
    user = await get_user(call.from_user.id)
    final = discounts.apply(tariff.price_rub, discounts.active_offer(user))
    await safe_edit(
        call.message,
        f"⭐️ <b>Оплата ELMA Plus «{tariff.title}» — {final} ₽</b>\n\n"
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

    key = sub["subscription_url"] or "—"
    text = (
        "✅ <b>Готово — добро пожаловать в ELMA</b> 🤍\n\n"
        "Твой VPN-ключ:\n"
        f"<code>{key}</code>\n\n"
        f"📅 Подписка активна до: {fmt_date(sub['expires_at'])}\n"
        "📱 Устройств: до 5\n\n"
        "Подключись прямо сейчас 👇"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="📲 Подключиться", callback_data="dev:menu")
    kb.button(text="👥 Пригласить друга", callback_data="menu:referral")
    kb.button(text="👤 Личный кабинет", callback_data="menu:cabinet")
    kb.adjust(1)
    await message.answer(text, parse_mode="HTML", reply_markup=kb.as_markup())
