"""One-time 3-day trial activation."""
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.format import subscription_text
from app.keyboards import back_to_menu
from app.services import access
from app.utils import safe_edit
from config import TRIAL_DAYS
from database import activate_trial, get_subscription

logger = logging.getLogger(__name__)
router = Router(name="trial")


@router.callback_query(F.data == "menu:trial")
async def cb_trial(call: CallbackQuery) -> None:
    await call.answer()
    user_id = call.from_user.id
    try:
        sub = await activate_trial(
            user_id, TRIAL_DAYS, access.trial_provision(user_id)
        )
    except Exception:  # noqa: BLE001 - VPN/DB failure -> safe retry
        logger.exception("Trial activation failed for %s", user_id)
        await safe_edit(
            call.message,
            "⚠️ Не удалось активировать триал — попробуйте ещё раз через минуту.",
            reply_markup=back_to_menu(),
        )
        return

    if sub is None:
        # trial_used_at was already set
        current = await get_subscription(user_id)
        await safe_edit(
            call.message,
            "Триал уже был использован.\n\n" + subscription_text(current),
            reply_markup=back_to_menu(),
        )
        return

    logger.info("Trial activated for %s", user_id)
    await safe_edit(
        call.message,
        "🎉 <b>Триал на 3 дня активирован!</b>\n\n" + subscription_text(sub),
        reply_markup=back_to_menu(),
    )
