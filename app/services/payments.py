"""Payment provider wrapper.

NOTE: the provider is not wired yet — the buy screens only *select* a tariff and
the "Оплатить" button is a placeholder. The pieces below (payload encode/parse,
invoice send, refund) are kept ready so flipping payments on is a small change:
have the "Оплатить" handler create a pending payment + call
``send_subscription_invoice`` (or your provider), and route ``successful_payment``
through ``app.services.billing.complete_purchase``.

The payload carries both the user id and the chosen tariff code so the success
handler knows what was bought.
"""
import time

from aiogram import Bot
from aiogram.types import LabeledPrice

from app.tariffs import Tariff

# Payload prefix used to match successful_payment back to our pending row.
PAYLOAD_PREFIX = "sub"


def make_payload(telegram_id: int, tariff_code: str) -> str:
    """Unique invoice payload returned verbatim in pre_checkout/successful."""
    return f"{PAYLOAD_PREFIX}:{telegram_id}:{tariff_code}:{int(time.time())}"


def parse_payload(payload: str) -> dict | None:
    """Return ``{"telegram_id": int, "tariff_code": str}`` or None."""
    parts = payload.split(":")
    if len(parts) >= 3 and parts[0] == PAYLOAD_PREFIX:
        try:
            return {"telegram_id": int(parts[1]), "tariff_code": parts[2]}
        except ValueError:
            return None
    return None


async def send_subscription_invoice(
    bot: Bot, chat_id: int, payload: str, tariff: Tariff, amount_stars: int
) -> None:
    await bot.send_invoice(
        chat_id=chat_id,
        title=f"ELMA VPN — {tariff.title}",
        description="ELMA VPN — безлимитный трафик, до 5 устройств, zero-logs.",
        payload=payload,
        currency="XTR",  # Telegram Stars
        prices=[LabeledPrice(label=tariff.title, amount=amount_stars)],
    )


async def refund(bot: Bot, user_id: int, charge_id: str) -> None:
    """Refund a Stars payment (used when provisioning ultimately fails)."""
    await bot.refund_star_payment(user_id=user_id, telegram_payment_charge_id=charge_id)
