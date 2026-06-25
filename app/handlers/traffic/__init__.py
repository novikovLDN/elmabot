"""Bypass traffic packs — buy GB of "обход белых списков".

Mirrors the premium pay flow (Platega), but the pending payment carries
``tariff_code="tr_<gb>"`` so the webhook routes it to traffic provisioning
(adds GB to the user's separate bypass entity) instead of a subscription.
"""
import logging

import httpx
from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from app import emoji
from app.keyboards import back_to_menu, payment_methods_keyboard
from app.services import bypass_service, platega
from app.utils import safe_edit
from database import create_pending_payment

logger = logging.getLogger(__name__)
router = Router(name="traffic")

_PLATEGA_METHODS = {"sbp": platega.METHOD_SBP, "card": platega.METHOD_CARD}
_GB = 1024 ** 3

INTRO = (
    "🌐 <b>Обход белых списков</b>\n\n"
    "Отдельный доступ для обхода блокировок — оплата по трафику, "
    "без срока: пока есть ГБ, всё работает.\n\n"
    "Выбери пакет 👇"
)


def _packs_keyboard(packs: dict[int, dict], *, extended: bool) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for gb, p in packs.items():
        label = f"{gb} ГБ — {p['price']} ₽"
        if p["discount"]:
            label += f"  {p['discount']}"
        kb.button(text=label, callback_data=f"tr:pack:{gb}")
    rows = [2] * (len(packs) // 2) + ([1] if len(packs) % 2 else [])
    if extended:
        kb.button(text="← Базовые пакеты", callback_data="tr:open")
    else:
        kb.button(text="📦 Больше объёма →", callback_data="tr:ext")
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data="menu:cabinet")
    kb.adjust(*rows, 1, 1)
    return kb


async def _intro_text(uid: int) -> str:
    usage = await bypass_service.get_usage(uid)
    if usage and usage["limit"]:
        used_gb = usage["used"] / _GB
        limit_gb = usage["limit"] / _GB
        left_gb = usage["remaining"] / _GB
        return (
            INTRO + f"\n\n📊 Сейчас: {used_gb:.1f} / {limit_gb:.0f} ГБ "
            f"(осталось {left_gb:.1f} ГБ)"
        )
    return INTRO


@router.callback_query(F.data == "tr:open")
async def cb_open(call: CallbackQuery) -> None:
    if not config.BYPASS_ENABLED:
        await call.answer("Обход скоро будет доступен ✨", show_alert=True)
        return
    text = await _intro_text(call.from_user.id)
    await safe_edit(call.message, text,
                    reply_markup=_packs_keyboard(config.TRAFFIC_PACKS, extended=False).as_markup())
    await call.answer()


@router.callback_query(F.data == "tr:ext")
async def cb_extended(call: CallbackQuery) -> None:
    await safe_edit(
        call.message,
        "📦 <b>Большие пакеты обхода</b>\n\nЧем больше объём — тем выгоднее 👇",
        reply_markup=_packs_keyboard(config.TRAFFIC_PACKS_EXTENDED, extended=True).as_markup(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("tr:pack:"))
async def cb_pack(call: CallbackQuery) -> None:
    try:
        gb = int(call.data.split(":")[2])
    except (IndexError, ValueError):
        await call.answer()
        return
    pack = config.traffic_pack(gb)
    if pack is None:
        await call.answer()
        return
    back = "tr:ext" if gb in config.TRAFFIC_PACKS_EXTENDED else "tr:open"
    text = (
        f"📦 <b>{gb} ГБ обхода</b>\n\n"
        f"💰 Стоимость: <b>{pack['price']} ₽</b>\n"
        "♾️ Без срока — пока есть трафик\n\n"
        "Как оплатить? 👇"
    )
    await safe_edit(
        call.message, text,
        reply_markup=payment_methods_keyboard(str(gb), back_data=back, prefix="trpay"),
    )
    await call.answer()


@router.callback_query(F.data.startswith("trpay:"))
async def cb_method(call: CallbackQuery) -> None:
    _, method, gb_s = call.data.split(":", 2)
    try:
        gb = int(gb_s)
    except ValueError:
        await call.answer()
        return
    pack = config.traffic_pack(gb)
    if pack is None or method not in _PLATEGA_METHODS:
        await call.answer()
        return
    price = pack["price"]

    if not config.PAYMENTS_ENABLED:
        await safe_edit(
            call.message,
            f"📦 <b>Обход {gb} ГБ — {price} ₽</b>\n\n"
            "⏳ Приём платежей скоро подключим. Загляни чуть позже 🙌",
            reply_markup=back_to_menu(),
        )
        await call.answer()
        return

    await call.answer("Готовлю ссылку на оплату…")
    try:
        txn = await platega.create_transaction(
            method=_PLATEGA_METHODS[method],
            amount_rub=float(price),
            description=f"ELMA — обход {gb} ГБ",
            payload=f"tg:{call.from_user.id}",
        )
    except (httpx.HTTPError, KeyError, ValueError):
        logger.exception("Platega traffic txn failed for %s", call.from_user.id)
        await safe_edit(call.message,
                        "⚠️ Не удалось создать платёж. Попробуй ещё раз через минуту 🙏",
                        reply_markup=back_to_menu())
        return

    txn_id = txn.get("transactionId")
    pay_url = txn.get("redirect")
    if not txn_id or not pay_url:
        logger.error("Platega traffic response missing fields: %s", txn)
        await safe_edit(call.message,
                        "⚠️ Не удалось создать платёж. Попробуй ещё раз через минуту 🙏",
                        reply_markup=back_to_menu())
        return

    await create_pending_payment(
        call.from_user.id, txn_id, price * 100,
        provider=method, tariff_code=f"tr_{gb}",
    )

    method_label = "СБП" if method == "sbp" else "картой"
    kb = InlineKeyboardBuilder()
    kb.button(text=f"💳 Оплатить {price} ₽", url=pay_url)
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data=f"tr:pack:{gb}")
    kb.adjust(1)
    await safe_edit(
        call.message,
        f"💳 <b>Оплата обхода — {gb} ГБ</b>\n\n"
        f"К оплате {method_label}: <b>{price} ₽</b>\n"
        "Ссылка действует 15 минут.\n\n"
        "Заверши оплату — трафик зачислится автоматически ✨",
        reply_markup=kb.as_markup(),
    )


@router.message(F.text == "/traffic")
async def cmd_traffic(message: Message) -> None:
    if not config.BYPASS_ENABLED:
        await message.answer("Обход скоро будет доступен ✨")
        return
    text = await _intro_text(message.from_user.id)
    await message.answer(
        text, reply_markup=_packs_keyboard(config.TRAFFIC_PACKS, extended=False).as_markup()
    )
