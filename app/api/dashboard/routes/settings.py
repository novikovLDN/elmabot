"""Settings — read-only config snapshot + the admin's passkeys.

GET /settings   brand, trial, tariffs, payments flag, registered passkeys
"""
from aiohttp import web

import config
import database
from app import tariffs

from ..util import json_ok

routes = web.RouteTableDef()


@routes.get("/settings")
async def settings(request: web.Request) -> web.Response:
    admin_id = int(request["admin"]["sub"])
    return json_ok(
        {
            "admin": {
                "telegram_id": admin_id,
                "username": request["admin"].get("username"),
            },
            "brand": config.BRAND_NAME,
            "trial_days": config.TRIAL_DAYS,
            "device_limit": config.DEVICE_LIMIT,
            "referral_bonus_days": config.REFERRAL_BONUS_DAYS,
            "payments_enabled": config.PAYMENTS_ENABLED,
            "dashboard_base_url": config.DASHBOARD_BASE_URL,
            "tariffs": [
                {
                    "code": t.code,
                    "title": t.title,
                    "price_rub": t.price_rub,
                    "days": t.days,
                    "save_label": t.save_label,
                }
                for t in tariffs.TARIFFS
            ],
            "passkeys": await database.webauthn_list(admin_id),
        }
    )
