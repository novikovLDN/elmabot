"""Tariff catalogue (approved ELMA pricing).

One source of truth for the plans shown on the buy screen and used to extend a
subscription. Prices are in whole rubles; ``days`` is what we add to the panel
expiry on purchase.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Tariff:
    code: str
    title: str
    months: int
    days: int
    price_rub: int
    save_label: str  # "" for the base monthly plan


TARIFFS: list[Tariff] = [
    Tariff("1m", "1 месяц", 1, 30, 199, ""),
    Tariff("3m", "3 месяца", 3, 90, 499, "−16%"),
    Tariff("6m", "6 месяцев", 6, 180, 899, "−25%"),
    Tariff("12m", "1 год", 12, 365, 1599, "−33%"),
]

_BY_CODE = {t.code: t for t in TARIFFS}


def get_tariff(code: str) -> Tariff | None:
    return _BY_CODE.get(code)
