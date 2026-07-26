"""Resolve editable text / on-off for the bot's built-in automatic messages,
for use OUTSIDE the notification loops (e.g. billing) where there's no override
cache. Reads the override on demand and is fail-safe: any error falls back to
the built-in default (enabled).
"""
import logging

import database
from app.utils import convert_tg_emoji

logger = logging.getLogger(__name__)


async def resolve(key: str, default: str) -> tuple[bool, str]:
    """(enabled, effective_text) for a built-in automation key."""
    try:
        ov = (await database.list_overrides()).get(key, {})
    except Exception:  # noqa: BLE001 - never break a send on a config read
        return True, default
    return bool(ov.get("enabled", True)), (ov.get("text") or default)


def render(text: str, **placeholders) -> str:
    """Substitute {name} placeholders (literal replace — safe against stray
    braces in admin text) and convert premium-emoji markdown to HTML."""
    for k, v in placeholders.items():
        text = text.replace("{" + k + "}", str(v))
    return convert_tg_emoji(text)
