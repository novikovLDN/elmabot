"""Tariff selection and purchase (ELMA Plus).

Choosing a tariff opens an order-confirmation screen; «Оплатить» creates a
Platega transaction and links straight to the hosted payment page (which lists
every method enabled for the merchant), so there's no in-bot method picker.
The webhook resolves the pending payment via ``billing.complete_purchase``.
"""
import asyncio
import logging
from datetime import timedelta

import httpx
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, PreCheckoutQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from app import emoji, tariffs
from app.format import fmt_date
from app.keyboards import back_to_menu, tariffs_keyboard
from app.services import billing, discounts, payments, platega
from app.utils import clean_username, convert_tg_emoji, safe_edit, safe_send
from database import (
    create_pending_payment,
    get_user,
    is_payment_paid,
    mark_payment_refunded,
    set_offer,
    utcnow,
)

logger = logging.getLogger(__name__)
router = Router(name="purchase")

PLUS_HEADER = (
    "💎 <b>Тариф: Premium</b>\n\n"
    "Выберите срок подписки 👇🏻"
)

# Shown when the active offer is the year promo: all periods listed, the 1-year
# plan discounted and highlighted (success style), others at the regular price.
# The percentage comes from config so header, button label and price never drift.
YEAR_PROMO_HEADER = (
    f"🎁 <b>Скидка {config.YEAR_PROMO_PCT}% на 1 год</b>\n\n"
    "Годовой план — сразу с учётом скидки.\n"
    "Другие периоды доступны по обычной цене.\n\n"
    "Выбери тариф ↓"
)


async def _tariffs_view(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    user = await get_user(user_id)
    offer = discounts.active_offer(user)
    year_promo = offer is not None and offer.code == "year"

    if year_promo:
        lines = [YEAR_PROMO_HEADER]
    else:
        lines = [PLUS_HEADER]
        if offer:
            lines.append(
                f"\n🎁 Тебе доступна {offer.reason}: <b>−{offer.pct}%</b> "
                f"(до {fmt_date(offer.expires_at)})"
            )
        lines.append("\nВыбери период 👇")

    rows: list[tuple[str, str, str | None, str | None]] = []
    for t in tariffs.TARIFFS:
        discounted = discounts.applies_to(offer, t.code)
        final = discounts.apply(t.price_rub, offer) if discounted else t.price_rub
        label = f"{t.title} — {final} ₽"
        # Colours per the design: 3м green, the rest blue.
        style = "success" if t.code == "3m" else "primary"
        if discounted and final != t.price_rub:
            label += f" · −{offer.pct}% ⚡"
            style = "success"  # a discounted plan is always green
        elif t.save_label:
            label += f"  {t.save_label}"
        icon = {
            "3m": emoji.TARIFF_DIAMOND,
            "12m": emoji.TARIFF_CROWN,
        }.get(t.code, emoji.TARIFF_KEY)
        rows.append((f"buy:tariff:{t.code}", label, icon, style))

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


SUB_MANAGE = (
    "💳 <b>Управление подпиской</b>\n\n"
    "Ваш текущий тариф:\n"
    "⚡️ <b>Тариф: Premium</b>\n\n"
    "<blockquote>🚀 Канал до 25 Гбит/с — YouTube 4K без тормозов\n"
    "🌐 1 ГБ обхода белых списков — в подарок к подписке\n"
    "🧑‍🧑‍🧒‍🧒 Одна подписка на всю семью — до 5 устройств\n"
    "➕ Подключение в одно нажатие</blockquote>\n\n"
    "Выберите действие:"
)


@router.callback_query(F.data == "sub:manage")
async def cb_sub_manage(call: CallbackQuery) -> None:
    """Subscription-management screen — reached from the cabinet / reminders."""
    kb = InlineKeyboardBuilder()
    kb.button(text="Продлить Premium", callback_data="menu:buy",
              style="success", icon_custom_emoji_id=emoji.RENEW)
    if config.BYPASS_ENABLED:
        kb.button(text="Купить ГБ обхода", callback_data="tr:open:m",
                  style="success", icon_custom_emoji_id=emoji.GB_TOPUP)
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data="menu:main")
    kb.adjust(1)
    await safe_edit(call.message, SUB_MANAGE, reply_markup=kb.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("promo:"))
async def cb_promo(call: CallbackQuery) -> None:
    """User tapped a 'Купить со скидкой' button from a broadcast: set the offer
    (applies to *all* tariffs) and open the buy screen with the discount."""
    try:
        _, pct_s, days_s = call.data.split(":")
        pct, days = int(pct_s), int(days_s)
    except ValueError:
        await call.answer()
        return
    if not (0 < pct < 100) or days <= 0:
        await call.answer()
        return
    await set_offer(
        call.from_user.id, "promo", pct, utcnow() + timedelta(days=days)
    )
    _u = await get_user(call.from_user.id)
    logger.info(
        "promo uid=%s pct=%s days=%s -> active_offer=%s",
        call.from_user.id, pct, days, discounts.active_offer(_u),
    )
    text, markup = await _tariffs_view(call.from_user.id)
    # The source may be a photo broadcast (no editable text) -> send a fresh msg.
    await call.message.answer(text, reply_markup=markup)
    await call.answer(f"Скидка −{pct}% активирована!")


@router.callback_query(F.data == "yearpromo")
async def cb_yearpromo(call: CallbackQuery) -> None:
    """Broadcast-button entry point for the year promo: grant a 24h discount
    scoped to the 1-year plan, flash a premium 🏆 for ~2s, then open the tariff
    screen with 1 год highlighted (green) and discounted."""
    await set_offer(
        call.from_user.id, "year", config.YEAR_PROMO_PCT, utcnow() + timedelta(days=1)
    )
    await call.answer(f"Скидка −{config.YEAR_PROMO_PCT}% на 1 год активирована!")

    # Premium-emoji flash — purely cosmetic, so never let it block the offer.
    chat_id = call.message.chat.id
    try:
        flash = await call.bot.send_message(
            chat_id,
            convert_tg_emoji(f"![🏆](tg://emoji?id={emoji.TROPHY})"),
            parse_mode="HTML",
        )
        await asyncio.sleep(2)
        await call.bot.delete_message(chat_id, flash.message_id)
    except Exception:  # noqa: BLE001
        logger.warning("year-promo emoji flash failed for %s", call.from_user.id)

    text, markup = await _tariffs_view(call.from_user.id)
    # Source may be a photo broadcast (no editable text) -> send a fresh message.
    await call.message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("disc:"))
async def cb_disc(call: CallbackQuery) -> None:
    """Broadcast discount button: grant a time-limited discount (optionally
    scoped to one tariff) and open the tariff screen. Callback:
    ``disc:{pct}:{hours}:{scope}`` with scope in all|1m|3m|6m|12m."""
    parts = call.data.split(":")
    if len(parts) != 4:
        await call.answer()
        return
    try:
        pct, hours = int(parts[1]), int(parts[2])
    except ValueError:
        await call.answer()
        return
    scope = parts[3]
    code = discounts.SCOPE_TO_CODE.get(scope)
    if code is None or not (0 < pct < 100) or not (0 < hours <= 8760):
        await call.answer()
        return
    await set_offer(call.from_user.id, code, pct, utcnow() + timedelta(hours=hours))
    text, markup = await _tariffs_view(call.from_user.id)
    await call.message.answer(text, reply_markup=markup)
    await call.answer(f"Скидка −{pct}% активирована!")


@router.callback_query(F.data == "buyaccess")
async def cb_buyaccess(call: CallbackQuery) -> None:
    """Broadcast "Купить доступ" button: open the tariff list. Sends a fresh
    message (not edit) so it works under a photo broadcast too."""
    text, markup = await _tariffs_view(call.from_user.id)
    await call.message.answer(text, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data == "chan:soon")
async def cb_channel_soon(call: CallbackQuery) -> None:
    await call.answer("Канал скоро откроется ✨", show_alert=True)


def _order_kb(*, pay_url: str | None, final: int | None = None) -> InlineKeyboardMarkup:
    """Order-confirmation buttons: «Оплатить» opens Platega's hosted page (all
    enabled methods), «Поддержка» → support chat, «Назад» → tariff list."""
    kb = InlineKeyboardBuilder()
    if pay_url:
        kb.button(text=f"Оплатить {final} ₽", url=pay_url, style="success")
    kb.button(text="Поддержка", url=config.SUPPORT_URL, style="primary")
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data="menu:buy")
    kb.adjust(1)
    return kb.as_markup()


@router.callback_query(F.data.startswith("buy:tariff:"))
async def cb_tariff(call: CallbackQuery) -> None:
    """Order-confirmation screen. «Оплатить» opens Platega's hosted payment page
    (every method enabled for the merchant) directly, so we create the
    transaction here and hand back a ready pay link — one tap, no in-bot method
    picker."""
    code = call.data.split(":")[2]
    tariff = tariffs.get_tariff(code)
    if tariff is None:
        await call.answer()
        return
    user = await get_user(call.from_user.id)
    offer = discounts.active_offer(user)
    discounted = discounts.applies_to(offer, code)
    final = discounts.apply(tariff.price_rub, offer) if discounted else tariff.price_rub

    order = (
        f"🧾 <b>К оплате: {final} ₽</b>\n\n"
        f"Тариф: {tariff.title}\n\n"
        "Как только банк подтвердит операцию, подписка активируется "
        "автоматически (обычно до 3 минут)."
    )

    if not config.PAYMENTS_ENABLED:
        await safe_edit(
            call.message,
            order + "\n\n⏳ Приём платежей скоро подключим. Загляни чуть позже 🙌",
            reply_markup=_order_kb(pay_url=None),
        )
        await call.answer()
        return

    await call.answer("Готовлю оплату…")
    uname = clean_username(call.from_user.username)
    try:
        # No method -> the payer picks it on the Platega page.
        txn = await platega.create_transaction(
            amount_rub=float(final),
            description=f"Подписка ELMA — {tariff.title}",
            payload=f"tg:{call.from_user.id}",
            user_id=call.from_user.id,
            user_name=f"@{uname}" if uname else None,
        )
    except (httpx.HTTPError, KeyError, ValueError):
        logger.exception("Platega create_transaction failed for %s", call.from_user.id)
        await safe_edit(
            call.message,
            "⚠️ Не удалось создать платёж. Попробуй ещё раз через минуту 🙏",
            reply_markup=back_to_menu(),
        )
        return

    txn_id = txn.get("transactionId")
    pay_url = platega.pay_url(txn)
    if not txn_id or not pay_url:
        logger.error("Platega response missing fields: %s", txn)
        await safe_edit(
            call.message,
            "⚠️ Не удалось создать платёж. Попробуй ещё раз через минуту 🙏",
            reply_markup=back_to_menu(),
        )
        return

    # Journal pending BEFORE the user can pay, so the webhook can resolve it.
    # Store this message's id so the webhook can delete the «Проверьте заказ»
    # screen once the payment is confirmed (it's an in-place edit of the tariff
    # list, so the id is stable).
    await create_pending_payment(
        call.from_user.id, txn_id, final * 100,  # kopecks
        provider="platega", tariff_code=code,
        confirm_message_id=call.message.message_id,
    )
    await safe_edit(call.message, order, reply_markup=_order_kb(pay_url=pay_url, final=final))


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

    # Store the charged amount as rubles×100 (kopecks), like every other provider,
    # so dashboard revenue stays correct (sp.total_amount is the star count).
    user = await get_user(user_id)
    amount_kopecks = discounts.apply(tariff.price_rub, discounts.active_offer(user)) * 100

    # Provision first; mark paid only on success — refund on failure so the rule
    # "paid -> served OR refunded" always holds.
    try:
        sub = await billing.complete_purchase(
            message.bot,
            user_id,
            tariff,
            invoice_id=invoice_id,
            amount_paid=amount_kopecks,
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
    await billing.notify_purchase_activated(message.bot, user_id)
