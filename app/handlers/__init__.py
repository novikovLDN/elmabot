"""Router registry — order matters (admin first so its filter short-circuits)."""
from aiogram import Router

from .admin import router as admin_router
from .common import router as common_router
from .onboarding import router as onboarding_router
from .purchase import router as purchase_router
from .referral import router as referral_router
from .trial import router as trial_router


def get_routers() -> list[Router]:
    return [
        admin_router,
        onboarding_router,
        referral_router,
        common_router,
        trial_router,
        purchase_router,
    ]
