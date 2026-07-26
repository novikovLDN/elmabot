"""Personal time-bound discounts.

An offer lives on the user row (``offer_code`` / ``offer_pct`` /
``offer_expires_at``); the scheduler sets it when a trigger fires (trial ended,
subscription ending, reactivation window) and clears itself by expiry. The buy
screen reads the active offer and applies the percentage to the tariff price.
"""
from dataclasses import dataclass
from datetime import datetime

import asyncpg

from database import utcnow

# offer code -> short human reason shown on the buy screen
REASONS: dict[str, str] = {
    "trial_end": "скидка за окончание пробного периода",
    "sub_end": "скидка на продление",
    "reactivation": "скидка на возвращение",
    "promo": "акционная скидка",
    "trial": "персональная скидка для тебя",
    "year": "скидка на годовой тариф",
    "admin": "персональная скидка",
}

# Offers whose discount is limited to specific tariff codes. Codes not listed
# here apply to every plan (``applies_to`` returns True by default).
SCOPED: dict[str, set[str]] = {
    "year": {"12m"},
}


@dataclass(frozen=True)
class Offer:
    code: str
    pct: int
    expires_at: datetime

    @property
    def reason(self) -> str:
        return REASONS.get(self.code, "персональная скидка")


def active_offer(user: asyncpg.Record | None) -> Offer | None:
    """Return the user's live offer, or None if absent/expired."""
    if user is None:
        return None
    code = user["offer_code"]
    pct = user["offer_pct"]
    exp = user["offer_expires_at"]
    if not code or not pct or exp is None:
        return None
    if exp <= utcnow():
        return None
    return Offer(code=code, pct=int(pct), expires_at=exp)


def applies_to(offer: Offer | None, tariff_code: str) -> bool:
    """Whether ``offer`` discounts this particular tariff.

    Most offers apply to every plan; scoped offers (e.g. the year promo) only to
    the tariff codes listed in ``SCOPED``.
    """
    if offer is None or offer.pct <= 0:
        return False
    scope = SCOPED.get(offer.code)
    return tariff_code in scope if scope is not None else True


def apply(price_rub: int, offer: Offer | None) -> int:
    """Discounted price in whole rubles (rounded)."""
    if offer is None or offer.pct <= 0:
        return price_rub
    return round(price_rub * (100 - offer.pct) / 100)
