"""Inline keyboards. Most screens are stateless callback-data, no FSM."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:home")]
        ]
    )


# --- ELMA onboarding ---

def welcome_keyboard() -> InlineKeyboardMarkup:
    """Welcome screen — single Start button."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Start", callback_data="onb:start")
    kb.adjust(1)
    return kb.as_markup()


def claim_keyboard() -> InlineKeyboardMarkup:
    """Screen 1 — claim the free trial."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🎁 Забрать доступ", callback_data="onb:claim")
    kb.adjust(1)
    return kb.as_markup()


def devices_keyboard() -> InlineKeyboardMarkup:
    """Screen 2 — choose a device to connect."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📱 iOS", callback_data="dev:ios")
    kb.button(text="🤖 Android", callback_data="dev:android")
    kb.button(text="🖥 MacOS", callback_data="dev:macos")
    kb.button(text="💻 Windows", callback_data="dev:windows")
    kb.button(text="📺 Android TV", callback_data="dev:androidtv")
    kb.button(text="🍎 Apple TV", callback_data="dev:appletv")
    kb.button(text="➕ Добавить устройство", callback_data="share:open")
    kb.adjust(2, 2, 2, 1)
    return kb.as_markup()


def device_keyboard(
    *,
    download_url: str | None,
    download_label: str,
    mode: str,
    sub_url: str | None,
) -> InlineKeyboardMarkup:
    """A single device instruction screen (screens 3-8).

    ``mode`` is "activate" (import the subscription) or "copy" (Windows: copy
    the raw profile). When ``sub_url`` is missing the activate button falls back
    to the claim flow so we never build an invalid empty-url button.
    """
    kb = InlineKeyboardBuilder()
    if download_url:
        kb.button(text=download_label, url=download_url)
    if mode == "copy":
        kb.button(text="🔗 Скопировать профиль", callback_data="dev:copy")
    elif sub_url:
        kb.button(text="🔗 Активировать ELMA VPN", url=sub_url)
    else:
        kb.button(text="🔗 Активировать ELMA VPN", callback_data="onb:claim")
    kb.button(text="🔙 Назад", callback_data="dev:menu")
    kb.adjust(1)
    return kb.as_markup()


def share_keyboard() -> InlineKeyboardMarkup:
    """Screen 9 — share the access link."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📥 Копировать", callback_data="share:copy")
    kb.button(text="⤵️ QR Code", callback_data="share:qr")
    kb.button(text="🔙 Назад", callback_data="dev:menu")
    kb.adjust(2, 1)
    return kb.as_markup()


def qr_close_keyboard() -> InlineKeyboardMarkup:
    """Screen 10 — close the QR photo."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Закрыть", callback_data="qr:close")
    kb.adjust(1)
    return kb.as_markup()


def buy_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⭐ Оплатить", callback_data="buy:invoice")
    kb.button(text="⬅️ В меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


# --- Admin ---

def admin_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Статистика", callback_data="admin:stats")
    kb.button(text="👤 Найти пользователя", callback_data="admin:find")
    kb.button(text="📢 Рассылка", callback_data="admin:broadcast")
    kb.adjust(1)
    return kb.as_markup()


def admin_user_actions(telegram_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Выдать 30 дней", callback_data=f"admin:grant:{telegram_id}")
    kb.button(text="🚫 Отозвать", callback_data=f"admin:revoke:{telegram_id}")
    kb.button(text="🧾 История", callback_data=f"admin:history:{telegram_id}")
    kb.button(text="⬅️ Админка", callback_data="admin:home")
    kb.adjust(1)
    return kb.as_markup()


def admin_broadcast_segments() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Все", callback_data="bcast:all")
    kb.button(text="Активные", callback_data="bcast:active")
    kb.button(text="Без подписки", callback_data="bcast:no_sub")
    kb.button(text="⬅️ Отмена", callback_data="admin:home")
    kb.adjust(1)
    return kb.as_markup()


def admin_broadcast_confirm() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Отправить", callback_data="bcast:send")
    kb.button(text="⬅️ Отмена", callback_data="admin:home")
    kb.adjust(1)
    return kb.as_markup()
