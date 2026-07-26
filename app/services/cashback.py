"""Referral cashback tiers («Круг Амбассадоров»).

Cashback percent by number of *paid* referrals. A per-user fixed override
(``cashback_fixed_percent``) beats the tier entirely when set.
"""

# (min paid referrals, percent, tier name) — ascending.
TIERS: list[tuple[int, int, str]] = [
    (0, 10, "Проводник"),
    (25, 20, "Хранитель"),
    (50, 30, "Инсайдер"),
    (75, 40, "Лидер"),
    (100, 45, "Амбассадор"),
]


def tier_for(paid_count: int) -> tuple[int, str]:
    pct, name = TIERS[0][1], TIERS[0][2]
    for threshold, p, n in TIERS:
        if paid_count >= threshold:
            pct, name = p, n
    return pct, name


def effective_percent(paid_count: int, fixed: int | None) -> int:
    """Fixed override wins; otherwise the tier for ``paid_count``."""
    if fixed is not None:
        return int(fixed)
    return tier_for(paid_count)[0]
