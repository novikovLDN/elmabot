"""Optional photos attached to bot screens.

Map a screen key -> Telegram photo ``file_id``. To obtain a file_id, an admin
sends the photo to the bot and it replies with the id (see the admin handler).
Fill entries in as we receive ``screen -> file_id`` pairs; an absent / empty
entry keeps the screen text-only, so nothing breaks until a photo is set.

Use :func:`app.utils.show_screen` (callbacks) and :func:`app.utils.send_screen`
(fresh messages) to render — they read this registry and pick photo-vs-text.
"""

# screen key -> photo file_id (populated as the admin provides them)
SCREEN_IMAGES: dict[str, str] = {
    # "onb_welcome": "AgACAgIAAx...",
    # "menu_main":   "AgACAgIAAx...",
}


def screen_image(key: str) -> str | None:
    """file_id for a screen, or None if no photo is configured."""
    return SCREEN_IMAGES.get(key) or None
