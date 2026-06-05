"""Referral programme: personal invite link + stats.

A friend who joins via ``?start=ref_<id>`` is recorded on /start (see
onboarding). The +days bonus is granted to the inviter when that friend makes
their first paid purchase (see ``app.services.billing``).
"""
import logging
from urllib.parse import quote

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.keyboards import referral_keyboard
from app.utils import safe_edit
from config import REFERRAL_BONUS_DAYS
from database import referral_stats

logger = logging.getLogger(__name__)
router = Router(name="referral")


async def _render(bot: Bot, user_id: int) -> tuple[str, str]:
    me = await bot.me()
    link = f"https://t.me/{me.username}?start=ref_{user_id}"
    stats = await referral_stats(user_id)
    invited = stats["invited"]
    purchased = stats["purchased"]

    text = (
        "🫂 <b>Реферальная программа</b>\n\n"
        "Приведи друга — получи бонус.\n\n"
        "За каждого друга купившего подписку —\n"
        f"<b>+{REFERRAL_BONUS_DAYS} дней</b> к твоей 🎁\n\n"
        f"🫂 Приглашено: {invited}\n"
        f"💰 Купили подписку: {purchased}\n"
        f"🏆 Бонусных дней: {purchased * REFERRAL_BONUS_DAYS}\n\n"
        "🔗 Твоя ссылка:\n"
        f"<code>{link}</code>"
    )
    share_text = "Подключайся к ELMA — VPN, который не играет на нервах ⚡"
    share_url = (
        f"https://t.me/share/url?url={quote(link)}&text={quote(share_text)}"
    )
    return text, share_url


@router.callback_query(F.data == "menu:referral")
async def cb_referral(call: CallbackQuery) -> None:
    text, share_url = await _render(call.bot, call.from_user.id)
    await safe_edit(call.message, text, reply_markup=referral_keyboard(share_url))
    await call.answer()


@router.message(Command("invite", "ref"))
async def cmd_invite(message: Message) -> None:
    text, share_url = await _render(message.bot, message.from_user.id)
    await message.answer(text, reply_markup=referral_keyboard(share_url))
