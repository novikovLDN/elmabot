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


def strip_tg_emoji(text: str) -> str:
    """Drop the custom-emoji markup, keeping the plain fallback emoji — used when
    the bot can't send premium emoji (``CUSTOM_EMOJI_INVALID``)."""
    return _TG_EMOJI_RE.sub(lambda m: m.group(1), text)


async def safe_send(
    bot: Bot,
    user_id: int,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    raise_bad_request: bool = False,
    **kw,
) -> Message | None:
    """Send a message, swallowing the usual "user blocked / chat gone" errors.

    ``raise_bad_request=True`` re-raises a non-"chat not found"
    ``TelegramBadRequest`` (e.g. a rejected parse-entity / premium-emoji markup)
    so the caller can retry with a plainer rendering."""
    try:
        return await bot.send_message(
            user_id, text, parse_mode="HTML", reply_markup=reply_markup, **kw
        )
    except TelegramForbiddenError:
        await mark_unreachable(user_id)
    except TelegramBadRequest as exc:
        if "chat not found" in str(exc).lower():
            await mark_unreachable(user_id)
        elif raise_bad_request:
            raise
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
    # A photo/media message can't be turned into a text message by editing, so
    # navigating *away* from a photo screen means delete-and-resend. This keeps
    # every existing safe_edit-based handler correct without changes.
    if message.photo or message.video or message.animation or message.document:
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
        return await safe_send(
            message.bot, message.chat.id, text, reply_markup=reply_markup
        )
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


async def send_screen(
    bot: Bot,
    chat_id: int,
    key: str,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message | None:
    """Send a screen as a photo+caption when an image is configured for ``key``
    (see :mod:`app.screens`), otherwise as a plain text message.

    Premium-emoji markdown ``![x](tg://emoji?id=N)`` is converted to a
    ``<tg-emoji>`` tag; if Telegram rejects it (an id the bot can't use) we retry
    with the plain fallback emoji. Falls back to a text message if the photo send
    fails entirely (e.g. a stale file_id)."""
    from app.screens import screen_image

    file_id = screen_image(key)
    # (premium-emoji rendering, plain-emoji fallback)
    variants = (convert_tg_emoji(text), strip_tg_emoji(text))
    if file_id:
        for i, caption in enumerate(variants):
            try:
                return await bot.send_photo(
                    chat_id,
                    file_id,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
            except TelegramForbiddenError:
                await mark_unreachable(chat_id)
                return None
            except TelegramBadRequest:
                # A rejected premium emoji -> retry stripped; if the stripped
                # caption also fails the file_id is bad -> drop to text below.
                if i == 0:
                    continue
                logger.warning("send_screen photo failed for %r; sending text", key)
    for i, body in enumerate(variants):
        try:
            return await bot.send_message(
                chat_id, body, parse_mode="HTML", reply_markup=reply_markup,
            )
        except TelegramForbiddenError:
            await mark_unreachable(chat_id)
            return None
        except TelegramBadRequest as exc:
            if "chat not found" in str(exc).lower():
                await mark_unreachable(chat_id)
                return None
            if i == 0:
                continue  # retry with the plain-emoji fallback
            logger.exception("send_screen text failed for %r", key)
    return None


async def show_screen(
    call_message: Message,
    key: str,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message | bool | None:
    """Render a screen in response to a callback. Text screens are edited in
    place; photo screens replace the message (text<->photo can't be edited in
    place), so the old message is deleted and a fresh photo is sent."""
    from app.screens import screen_image

    if not screen_image(key):
        return await safe_edit(call_message, text, reply_markup=reply_markup)
    try:
        await call_message.delete()
    except TelegramBadRequest:
        pass
    return await send_screen(
        call_message.bot, call_message.chat.id, key, text, reply_markup=reply_markup
    )
