"""Brand-name substitution.

The whole product is templated on a single name. Screens hard-code the default
brand (``ELMA``); a deployment rebrands by setting ``BRAND_NAME``, and this
request middleware rewrites the brand token in the ``text`` / ``caption`` of every
outgoing Telegram message. When ``BRAND_NAME`` is the default the middleware is
not installed at all, so the original bot is byte-for-byte unchanged.

This makes one codebase serve several bots: deploy the same repo with a
different ``BRAND_NAME`` (plus its own token / DB / domain / panel prefix).
"""
import logging

from aiogram.client.session.middlewares.base import BaseRequestMiddleware

import config

logger = logging.getLogger(__name__)

DEFAULT_BRAND = "ELMA"


class BrandMiddleware(BaseRequestMiddleware):
    """Rewrites the brand token in outgoing message text and captions."""

    def __init__(self, brand: str) -> None:
        self.brand = brand

    async def __call__(self, make_request, bot, method):
        for attr in ("text", "caption"):
            value = getattr(method, attr, None)
            if isinstance(value, str) and DEFAULT_BRAND in value:
                try:
                    setattr(method, attr, value.replace(DEFAULT_BRAND, self.brand))
                except Exception:  # noqa: BLE001 - never break a send over branding
                    logger.debug("brand rewrite skipped for %s", type(method).__name__)
        return await make_request(bot, method)


def install_brand(bot) -> None:
    """Register the brand rewriter unless the brand is the built-in default."""
    if config.BRAND_NAME != DEFAULT_BRAND:
        bot.session.middleware(BrandMiddleware(config.BRAND_NAME))
        logger.info("Brand rewriting enabled: %s -> %s", DEFAULT_BRAND, config.BRAND_NAME)
