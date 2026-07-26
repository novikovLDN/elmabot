"""Router registry — order matters (admin first so its filter short-circuits)."""
from aiogram import Router

from .admin import router as admin_router
from .gift import router as gift_router
from .menu import router as menu_router
from .onboarding import router as onboarding_router
from .promo import router as promo_router
from .purchase import router as purchase_router
from .referral import router as referral_router
from .traffic import router as traffic_router


def get_routers() -> list[Router]:
    return [
        admin_router,
        onboarding_router,
        menu_router,
        referral_router,
        gift_router,
        promo_router,
        purchase_router,
        traffic_router,
    ]
