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
    "sc_1m": "скидка на тариф 1 месяц",
    "sc_3m": "скидка на тариф 3 месяца",
    "sc_6m": "скидка на тариф 6 месяцев",
    "sc_12m": "скидка на годовой тариф",
}

# Offers whose discount is limited to specific tariff codes. Codes not listed
# here apply to every plan (``applies_to`` returns True by default). The ``sc_*``
# codes back the broadcast "scoped discount" buttons.
SCOPED: dict[str, set[str]] = {
    "year": {"12m"},
    "sc_1m": {"1m"},
    "sc_3m": {"3m"},
    "sc_6m": {"6m"},
    "sc_12m": {"12m"},
}

# Broadcast discount-button scope -> the offer code that scopes it. "all" uses
# the generic "promo" code (applies to every tariff).
SCOPE_TO_CODE: dict[str, str] = {
    "all": "promo",
    "1m": "sc_1m",
    "3m": "sc_3m",
    "6m": "sc_6m",
    "12m": "sc_12m",
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
