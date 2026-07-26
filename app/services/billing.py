"""Purchase completion — the single place a successful payment lands.

The actual payment provider is not wired yet (buttons only); when it is, the
provider's success handler just calls :func:`complete_purchase`. It extends the
subscription, journals the payment, clears any used discount, and — on the
buyer's *first* paid purchase — credits the referrer with bonus days.
"""
import logging
import secrets

import asyncpg
from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from app import emoji
from app.tariffs import TARIFFS, Tariff, get_tariff
from app.utils import safe_send
from database import (
    adjust_balance,
    clear_offer,
    create_gift,
    credit_referral,
    get_subscription,
    get_user,
    has_paid_payment,
    mark_payment_paid,
    record_traffic_purchase,
    redeem_gift_record,
    referral_stats,
    try_spend_balance,
)

from . import bypass_service, cashback, subscription_service

logger = logging.getLogger(__name__)


async def complete_purchase(
    bot: Bot,
    user_id: int,
    tariff: Tariff,
    *,
    invoice_id: str,
    amount_paid: int,
) -> asyncpg.Record:
    """Provision the bought tariff and settle the side effects.

    Provisioning runs first; the payment is marked paid only after it succeeds
    (the caller refunds on exception, keeping "paid -> served OR refunded").
    """
    current = await get_subscription(user_id)
    first_purchase = not await has_paid_payment(user_id)

    new_expires = subscription_service.next_expiry(current, tariff.days)
    sub = await subscription_service.create_or_renew(
        user_id, new_expires, source="payment"
    )
    await mark_payment_paid(user_id, invoice_id, amount_paid)
    await clear_offer(user_id)

    if first_purchase:
        await _reward_referrer(bot, user_id)
    await _credit_cashback(bot, user_id, amount_paid)
    return sub


async def complete_balance_purchase(
    bot: Bot, user_id: int, tariff: Tariff, amount_kopecks: int
) -> asyncpg.Record | None:
    """Pay for a subscription from the user's balance. Returns the subscription
    on success, or None if the balance doesn't cover the price.

    No payment row is written (balance was funded earlier — not new revenue) and
    no cashback is paid (would loop balance → cashback → balance)."""
    ok = await try_spend_balance(user_id, amount_kopecks, meta=f"tariff {tariff.code}")
    if not ok:
        return None
    current = await get_subscription(user_id)
    new_expires = subscription_service.next_expiry(current, tariff.days)
    sub = await subscription_service.create_or_renew(user_id, new_expires, source="payment")
    await clear_offer(user_id)
    return sub


async def _credit_cashback(bot: Bot, buyer_id: int, amount_kopecks: int) -> None:
    """Credit the buyer's referrer a % of this payment to their balance.

    Percent is the referrer's fixed override, else their «Круг Амбассадоров»
    tier. Best-effort — a cashback failure never affects the purchase."""
    try:
        if amount_kopecks <= 0:
            return
        buyer = await get_user(buyer_id)
        referrer_id = buyer["referred_by"] if buyer else None
        if not referrer_id:
            return
        referrer = await get_user(referrer_id)
        if referrer is None:
            return
        stats = await referral_stats(referrer_id)
        pct = cashback.effective_percent(
            int(stats.get("purchased", 0)), referrer["cashback_fixed_percent"]
        )
        reward = round(amount_kopecks * pct / 100)
        if pct <= 0 or reward <= 0:
            return
        await adjust_balance(referrer_id, reward, "cashback", meta=f"from {buyer_id}")
        await safe_send(
            bot, referrer_id,
            f"💸 <b>Кешбэк +{reward // 100} ₽</b>\n\n"
            f"Твой реферал оплатил подписку — начислили {pct}% на баланс 🤍",
        )
    except Exception:  # noqa: BLE001 - cashback must never break a purchase
        logger.exception("cashback crediting failed for buyer %s", buyer_id)


_GB = 1024 ** 3


async def complete_traffic_purchase(
    bot: Bot,
    user_id: int,
    gb: int,
    *,
    invoice_id: str,
    amount_paid: int,
    provider: str = "unknown",
) -> None:
    """Provision a bypass GB pack — adds traffic only, never touches premium.

    Provisioning runs first (panel call), then the payment is settled and the
    purchase journalled. A retry would at worst add the GB twice (user benefit),
    never leave a paid user without traffic.
    """
    new_limit = await bypass_service.provision_traffic(user_id, gb * _GB)
    await mark_payment_paid(user_id, invoice_id, amount_paid)
    await record_traffic_purchase(user_id, gb, amount_paid, provider, invoice_id)
    await _credit_cashback(bot, user_id, amount_paid)

    kb = InlineKeyboardBuilder()
    kb.button(text="👤 Личный кабинет", callback_data="menu:cabinet")
    kb.button(text="📲 Подключиться", callback_data="dev:menu")
    kb.adjust(1)
    await safe_send(
        bot,
        user_id,
        "✅ <b>Трафик обхода зачислен</b>\n\n"
        f"➕ {gb} ГБ добавлено.\n"
        f"📦 Всего лимит: <b>{new_limit // _GB} ГБ</b>.\n\n"
        "Ключ обхода и остаток трафика — в личном кабинете 👇",
        reply_markup=kb.as_markup(),
    )


async def finalize_confirmed_payment(bot: Bot, payment) -> None:
    """Provision a CONFIRMED payment (traffic pack or subscription) and notify.

    Shared by the Platega webhook and the reconcile poller. The caller guarantees
    the payment isn't already settled (is_payment_paid guard) before calling.
    """
    code = payment["tariff_code"] or ""
    invoice_id = payment["invoice_id"]
    tg = payment["telegram_id"]
    amount = payment["amount_kopecks"]

    if code.startswith("tr_"):
        gb = int(code[3:])  # ValueError -> caller logs & marks failed
        await complete_traffic_purchase(
            bot, tg, gb, invoice_id=invoice_id, amount_paid=amount,
            provider=payment["provider"],
        )
    else:
        tariff = get_tariff(code) or TARIFFS[0]
        await complete_purchase(bot, tg, tariff, invoice_id=invoice_id, amount_paid=amount)
        await notify_purchase_activated(bot, tg)

    # Best-effort admin web-push for daily revenue milestones (guarded/no-op if
    # push is disabled or unavailable). Never affects payment settlement.
    from app.services import push_service

    await push_service.check_revenue_milestones()


_PURCHASE_OK_TEXT = (
    "🌐 <b>Подписка ELMA подтверждена</b>\n\n"
    "Твой доступ активирован ☁️\n"
    "Теперь цифровое пространство ELMA поддерживает стабильное подключение "
    "для всего, что важно тебе — без зависаний и неожиданных обрывов ⚡\n\n"
    "🫧 До 5 устройств одновременно\n"
    "🛜 Максимальная скорость и стабильность\n"
    "💎 Доступ ко всем функциям сервиса\n\n"
    "Наслаждайся интернетом, который наконец перестал раздражать"
)


async def notify_purchase_activated(bot: Bot, user_id: int) -> None:
    """Confirmation message after a subscription purchase (Stars or Platega)."""
    kb = InlineKeyboardBuilder()
    kb.button(text="Подключиться", callback_data="dev:menu",
              style="primary", icon_custom_emoji_id=emoji.CONNECT)
    kb.button(text="Пригласить друга", callback_data="menu:referral",
              icon_custom_emoji_id=emoji.INVITE)
    kb.button(text="Личный кабинет", callback_data="menu:cabinet",
              icon_custom_emoji_id=emoji.CABINET)
    kb.adjust(1)
    await safe_send(bot, user_id, _PURCHASE_OK_TEXT, reply_markup=kb.as_markup())


async def _reward_referrer(bot: Bot, buyer_id: int) -> None:
    """Grant the inviter bonus days when their friend buys for the first time."""
    referrer_id = await credit_referral(buyer_id)
    if not referrer_id:
        return
    try:
        ref_sub = await get_subscription(referrer_id)
        new_expires = subscription_service.next_expiry(
            ref_sub, config.REFERRAL_BONUS_DAYS
        )
        sub = await subscription_service.create_or_renew(
            referrer_id, new_expires, source="referral"
        )
        await safe_send(
            bot,
            referrer_id,
            "💎 <b>Ваш друг остался в ELMA</b>\n\n"
            "Подписка успешно оформлена ✨\n"
            f"Вам начислено +{config.REFERRAL_BONUS_DAYS} бонусных дней",
        )
    except Exception:  # noqa: BLE001 - never fail the buyer's purchase on this
        logger.exception("Failed to reward referrer %s", referrer_id)


async def notify_referrer_on_trial(bot: Bot, user_id: int) -> None:
    """Tell the inviter their friend joined (on the friend's trial activation)."""
    user = await get_user(user_id)
    referrer_id = user["referred_by"] if user else None
    if not referrer_id:
        return
    await safe_send(
        bot,
        referrer_id,
        "🎉 <b>Ваш друг активировал ELMA</b>\n\n"
        "Пробный доступ уже запущен ✨\n\n"
        f"Если он оформит подписку — вы получите +{config.REFERRAL_BONUS_DAYS} "
        "бонусных дней автоматически",
    )


# --- Gifts (ready; gift creation is gated behind payment) -----------------

async def create_gift_code(buyer_id: int, tariff: Tariff) -> str:
    """Issue a one-time gift code (called once a gift payment succeeds)."""
    code = secrets.token_urlsafe(9)
    await create_gift(code, tariff.code, buyer_id)
    return code


async def complete_gift_purchase(bot: Bot, buyer_id: int, tariff: Tariff) -> str:
    """After a gift payment: create the code and send the buyer a ready-to-
    forward message with the activation link. Returns the gift link."""
    code = await create_gift_code(buyer_id, tariff)
    me = await bot.me()
    link = f"https://t.me/{me.username}?start=gift_{code}"
    await safe_send(
        bot,
        buyer_id,
        "Привет! Дарю тебе подписку\n"
        f"🌐 ELMA на {tariff.title}\n\n"
        "Чтобы интернет работал спокойно — без лагов, обрывов "
        "и бесконечной загрузки ⚡\n\n"
        "Нажми на ссылку для активации:\n"
        f"🔗 {link}",
        disable_web_page_preview=True,
    )
    return link


async def redeem_gift(bot: Bot, user_id: int, code: str) -> Tariff | None:
    """Activate a gift for the recipient. Returns the tariff on success, or None
    if the code is unknown / already used. Notifies the gifter."""
    rec = await redeem_gift_record(code, user_id)
    if rec is None:
        return None
    tariff = get_tariff(rec["tariff_code"])
    if tariff is None:
        return None
    current = await get_subscription(user_id)
    new_expires = subscription_service.next_expiry(current, tariff.days)
    await subscription_service.create_or_renew(user_id, new_expires, source="gift")
    await safe_send(
        bot,
        rec["created_by"],
        "🎁 <b>Твой подарок активирован!</b>\n\n"
        "Получатель уже в сети —\nбез лагов и обрывов 🤍",
    )
    return tariff
