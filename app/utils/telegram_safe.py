"""Anti-crash wrappers around Telegram send/edit.

Telegram raises ``TelegramForbiddenError`` when the user has blocked the bot
and ``TelegramBadRequest`` when a message can't be edited. Wrap every send so a
single bad recipient never tears down a loop or a broadcast.
"""
import logging
import re

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup, Message

from database import mark_unreachable

logger = logging.getLogger(__name__)

# Telegram-Ads style custom emoji: ![🎁](tg://emoji?id=12345)
_TG_EMOJI_RE = re.compile(r"!\[(.*?)\]\(tg://emoji\?id=(\d+)\)")


def convert_tg_emoji(text: str) -> str:
    """Turn ``![🎁](tg://emoji?id=123)`` into a ``<tg-emoji>`` HTML tag.

    Handy for broadcasts. Note: the custom emoji id must be reachable by the
    bot or Telegram answers ``DOCUMENT_INVALID`` (§10.4/§10.5).
    """
    return _TG_EMOJI_RE.sub(
        lambda m: f'<tg-emoji emoji-id="{m.group(2)}">{m.group(1)}</tg-emoji>', text
    )


async def safe_send(
    bot: Bot,
    user_id: int,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    **kw,
) -> Message | None:
    try:
        return await bot.send_message(
            user_id, text, parse_mode="HTML", reply_markup=reply_markup, **kw
        )
    except TelegramForbiddenError:
        await mark_unreachable(user_id)
    except TelegramBadRequest as exc:
        if "chat not found" in str(exc).lower():
            await mark_unreachable(user_id)
        else:
            logger.exception("safe_send failed for %s", user_id)
    return None


async def safe_edit(
    message: Message,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    **kw,
) -> Message | bool | None:
    try:
        return await message.edit_text(
            text, parse_mode="HTML", reply_markup=reply_markup, **kw
        )
    except TelegramBadRequest as exc:
        msg = str(exc).lower()
        if "message is not modified" in msg:
            return message
        logger.debug("safe_edit no-op for %s: %s", message.chat.id, exc)
    except TelegramForbiddenError:
        await mark_unreachable(message.chat.id)
    return None
