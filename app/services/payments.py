"""Payment gateway wrapper — Telegram Stars (built into the Bot API).

Stars need no external webhook: ``send_invoice`` -> ``pre_checkout_query`` ->
``successful_payment`` all flow through the same polling process.
"""
import time

from aiogram import Bot
from aiogram.types import LabeledPrice

from config import PRICE_STARS, SUBSCRIPTION_DAYS

# Payload prefix used to match successful_payment back to our pending row.
PAYLOAD_PREFIX = "sub"


def make_payload(telegram_id: int) -> str:
    """Unique invoice payload returned verbatim in pre_checkout/successful."""
    return f"{PAYLOAD_PREFIX}:{telegram_id}:{int(time.time())}"


def parse_payload(payload: str) -> int | None:
    parts = payload.split(":")
    if len(parts) >= 2 and parts[0] == PAYLOAD_PREFIX:
        try:
            return int(parts[1])
        except ValueError:
            return None
    return None


async def send_subscription_invoice(bot: Bot, chat_id: int, payload: str) -> None:
    await bot.send_invoice(
        chat_id=chat_id,
        title=f"VPN на {SUBSCRIPTION_DAYS} дней",
        description="Атлас Lite — безлимитный трафик, один тариф, один сервер.",
        payload=payload,
        currency="XTR",  # Telegram Stars
        prices=[LabeledPrice(label="VPN", amount=PRICE_STARS)],
    )


async def refund(bot: Bot, user_id: int, charge_id: str) -> None:
    """Refund a Stars payment (used when provisioning ultimately fails)."""
    await bot.refund_star_payment(user_id=user_id, telegram_payment_charge_id=charge_id)
