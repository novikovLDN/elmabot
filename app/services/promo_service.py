"""Apply a redeemed promo code: a personal discount (offer) or bonus days."""
import logging
from datetime import timedelta

from aiogram import Bot

from database import get_subscription, redeem_promo, set_offer, utcnow

from . import subscription_service

logger = logging.getLogger(__name__)

_FAIL = {
    "not_found": "❌ Промокод не найден.",
    "inactive": "❌ Промокод больше не действует.",
    "expired": "❌ Срок действия промокода истёк.",
    "exhausted": "❌ Промокод исчерпан.",
    "already_used": "❌ Ты уже использовал этот промокод.",
}


async def apply_promo(bot: Bot, user_id: int, code: str) -> tuple[bool, str, bool]:
    """Redeem ``code`` for the user. Returns (ok, message, show_buy).

    ``show_buy`` is True for discount codes so the caller can open the tariff
    screen right after (the discount is already active on the user's row)."""
    # Promo codes are short; hard-cap arbitrary user input before it hits the DB.
    code = (code or "").strip()[:64]
    if not code:
        return False, "Пришли промокод одним словом.", False

    res = await redeem_promo(code, user_id)
    if not res["ok"]:
        return False, _FAIL.get(res["reason"], "❌ Не удалось активировать промокод."), False

    promo = res["promo"]
    if promo["kind"] == "days":
        days = int(promo["grant_days"] or 0)
        if days <= 0:
            return False, "❌ Промокод настроен неверно.", False
        current = await get_subscription(user_id)
        new_expires = subscription_service.next_expiry(current, days)
        try:
            await subscription_service.create_or_renew(user_id, new_expires, source="promo")
        except Exception:  # noqa: BLE001 - provisioning failure
            logger.exception("promo grant failed for %s (%s)", user_id, code)
            return False, "⚠️ Не удалось выдать доступ, попробуй позже.", False
        logger.info("Promo %s granted %d days to %s", promo["code"], days, user_id)
        return True, f"🎁 <b>Промокод активирован!</b>\n\nДоступ продлён на {days} дн. 🚀", False

    # discount
    pct = int(promo["discount_pct"] or 0)
    valid_days = int(promo["discount_days"] or 1)
    if not 0 < pct < 100:
        return False, "❌ Промокод настроен неверно.", False
    await set_offer(user_id, "promo", pct, utcnow() + timedelta(days=valid_days))
    logger.info("Promo %s gave -%d%% to %s", promo["code"], pct, user_id)
    return True, (
        f"🎟 <b>Скидка −{pct}% активирована!</b>\n\n"
        "Выбери тариф — цена уже с учётом скидки 👇"
    ), True
