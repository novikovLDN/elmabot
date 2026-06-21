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
    # 👤 Личный кабинет
    "cabinet": "AgACAgQAAxkBAAKdp2orzSZpDobx7J4m5sbMf--KVnyeAAIxDWsbbFlgUUyw3wuaKd_oAQADAgADeQADPAQ",
    # 🫧 ELMA активирован — экран выбора устройства
    "devices": "AgACAgQAAxkBAAKdq2orzVbXhIztj1r7BJsKyVsNNEwrAAIyDWsbbFlgUekFWRgF2ieaAQADAgADeQADPAQ",
    # 🌐 Подключитесь в одно нажатие — экран импорта ключа (общий для устройств)
    "connect": "AgACAgIAAxkBAAEEsxJqN6Xqh717eC9BIS0tNUKpeH85kQACQRprGxiswEmHMO1mDqO4VgEAAwIAA3kAAzwE",
    # 📲 Скачайте Happ — экран загрузки для Android
    "dl_android": "AgACAgIAAxkBAAEEsyRqN6qqU9EdWDXtoxeki674VJtnZAACqRtrG-wUwEmVOepDyczjwAEAAwIAA3kAAzwE",
}


def screen_image(key: str) -> str | None:
    """file_id for a screen, or None if no photo applies.

    The photos are Elma-specific (file_ids belong to Elma's uploads), so only
    the Elma brand renders screens with images; any other BRAND_NAME serves them
    text-only.
    """
    import config
    from app.brand import DEFAULT_BRAND

    if config.BRAND_NAME.upper() != DEFAULT_BRAND:
        return None
    return SCREEN_IMAGES.get(key) or None
