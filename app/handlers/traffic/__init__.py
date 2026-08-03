"""Bypass traffic packs — buy GB of "обход белых списков".

Mirrors the premium pay flow (Platega), but the pending payment carries
``tariff_code="tr_<gb>"`` so the webhook routes it to traffic provisioning
(adds GB to the user's separate bypass entity) instead of a subscription.
"""
import logging

import httpx
from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from app import emoji
from app.keyboards import back_to_menu
from app.services import bypass_service, platega
from app.utils import safe_edit
from database import create_pending_payment

logger = logging.getLogger(__name__)
router = Router(name="traffic")

_GB = 1024 ** 3

INTRO = (
    "🌐 <b>Обход белых списков</b>\n\n"
    "Отдельный доступ для обхода блокировок — оплата по трафику, "
    "без срока: пока есть ГБ, всё работает.\n\n"
    "Выбери пакет 👇"
)


def _origin(data: str) -> str:
    """Trailing origin token of a traffic callback: 'c' (opened from the cabinet)
    or 'm' (from the main menu; the default for any legacy / external callback)."""
    return "c" if data.split(":")[-1] == "c" else "m"


def _back_cb(origin: str) -> str:
    """Where the top-level «Назад» returns — the screen the user came from."""
    return "menu:cabinet" if origin == "c" else "menu:main"


def _packs_keyboard(
    packs: dict[int, dict], *, extended: bool, origin: str
) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for gb, p in packs.items():
        label = f"{gb} ГБ — {p['price']} ₽"
        if p["discount"]:
            label += f"  {p['discount']}"
        kb.button(text=label, callback_data=f"tr:pack:{gb}:{origin}", style="success")
    rows = [2] * (len(packs) // 2) + ([1] if len(packs) % 2 else [])
    if extended:
        kb.button(text="← Базовые пакеты", callback_data=f"tr:open:{origin}", style="primary")
    else:
        kb.button(text="📦 Больше объёма →", callback_data=f"tr:ext:{origin}", style="primary")
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data=_back_cb(origin))
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


@router.callback_query(F.data.startswith("tr:open"))
async def cb_open(call: CallbackQuery) -> None:
    if not config.BYPASS_ENABLED:
        await call.answer("Обход скоро будет доступен ✨", show_alert=True)
        return
    origin = _origin(call.data)
    text = await _intro_text(call.from_user.id)
    await safe_edit(
        call.message, text,
        reply_markup=_packs_keyboard(config.TRAFFIC_PACKS, extended=False, origin=origin).as_markup(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("tr:ext"))
async def cb_extended(call: CallbackQuery) -> None:
    origin = _origin(call.data)
    await safe_edit(
        call.message,
        "📦 <b>Большие пакеты обхода</b>\n\nЧем больше объём — тем выгоднее 👇",
        reply_markup=_packs_keyboard(config.TRAFFIC_PACKS_EXTENDED, extended=True, origin=origin).as_markup(),
    )
    await call.answer()


def _order_kb(price: int, back: str, *, pay_url: str | None) -> InlineKeyboardMarkup:
    """Order-confirmation buttons for a GB pack: «Оплатить» opens Platega's
    hosted page (all methods), «Поддержка» → support, «Назад» → the packs list."""
    kb = InlineKeyboardBuilder()
    if pay_url:
        kb.button(text=f"Оплатить {price} ₽", url=pay_url, style="success")
    kb.button(text="Поддержка", url=config.SUPPORT_URL, style="primary")
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data=back)
    kb.adjust(1)
    return kb.as_markup()


@router.callback_query(F.data.startswith("tr:pack:"))
async def cb_pack(call: CallbackQuery) -> None:
    """Order-confirmation for a GB pack. «Оплатить» opens Platega's hosted page
    (all methods) directly, so we create the methodless transaction here and
    hand back a ready pay link — the payer picks the method on Platega."""
    parts = call.data.split(":")  # tr:pack:<gb>[:origin]
    try:
        gb = int(parts[2])
    except (IndexError, ValueError):
        await call.answer()
        return
    pack = config.traffic_pack(gb)
    if pack is None:
        await call.answer()
        return
    origin = _origin(call.data)
    price = pack["price"]
    # Назад -> the list the pack was picked from, carrying the origin so its own
    # «Назад» still returns to where the whole flow started.
    back = f"tr:ext:{origin}" if gb in config.TRAFFIC_PACKS_EXTENDED else f"tr:open:{origin}"
    order = (
        f"📦 <b>{gb} ГБ обхода</b>\n\n"
        f"💰 Стоимость: <b>{price} ₽</b>\n"
        "♾️ Без срока — пока есть трафик\n\n"
        "Для оплаты 👇"
    )

    if not config.PAYMENTS_ENABLED:
        await safe_edit(
            call.message,
            order + "\n\n⏳ Приём платежей скоро подключим. Загляни чуть позже 🙌",
            reply_markup=_order_kb(price, back, pay_url=None),
        )
        await call.answer()
        return

    await call.answer("Готовлю оплату…")
    try:
        # No method -> the payer picks it on the Platega page.
        txn = await platega.create_transaction(
            amount_rub=float(price),
            description=f"ELMA — обход {gb} ГБ",
            payload=f"tg:{call.from_user.id}",
            user_id=call.from_user.id,
            user_name=f"@{call.from_user.username}" if call.from_user.username else None,
        )
    except (httpx.HTTPError, KeyError, ValueError):
        logger.exception("Platega traffic txn failed for %s", call.from_user.id)
        await safe_edit(call.message,
                        "⚠️ Не удалось создать платёж. Попробуй ещё раз через минуту 🙏",
                        reply_markup=back_to_menu())
        return

    txn_id = txn.get("transactionId")
    pay_url = platega.pay_url(txn)
    if not txn_id or not pay_url:
        logger.error("Platega traffic response missing fields: %s", txn)
        await safe_edit(call.message,
                        "⚠️ Не удалось создать платёж. Попробуй ещё раз через минуту 🙏",
                        reply_markup=back_to_menu())
        return

    # Store this message's id so the webhook can delete the pay screen once the
    # payment is confirmed (in-place edit -> stable id).
    await create_pending_payment(
        call.from_user.id, txn_id, price * 100,
        provider="platega", tariff_code=f"tr_{gb}",
        confirm_message_id=call.message.message_id,
    )
    await safe_edit(call.message, order, reply_markup=_order_kb(price, back, pay_url=pay_url))


@router.message(F.text == "/traffic")
async def cmd_traffic(message: Message) -> None:
    if not config.BYPASS_ENABLED:
        await message.answer("Обход скоро будет доступен ✨")
        return
    text = await _intro_text(message.from_user.id)
    await message.answer(
        text,
        reply_markup=_packs_keyboard(config.TRAFFIC_PACKS, extended=False, origin="m").as_markup(),
    )
