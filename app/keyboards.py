"""Inline keyboards. Most screens are stateless callback-data, no FSM."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu:main")]
        ]
    )


# --- Main menu / personal cabinet ---

def main_menu_keyboard(*, has_active_sub: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📲 Подключиться", callback_data="dev:menu")
    if has_active_sub:
        kb.button(text="🔄 Продлить подписку", callback_data="menu:buy")
    else:
        kb.button(text="💳 Купить подписку", callback_data="menu:buy")
    kb.button(text="👤 Личный кабинет", callback_data="menu:cabinet")
    kb.button(text="🫂 Реферальная программа", callback_data="menu:referral")
    kb.button(text="🎁 Подарить", callback_data="gift:open")
    kb.button(text="🛎️ Помощь", callback_data="help:open")
    kb.button(text="ℹ️ О сервисе", callback_data="about:open")
    kb.adjust(1, 2, 1, 2, 1)
    return kb.as_markup()


def cabinet_keyboard(*, has_active_sub: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if has_active_sub:
        kb.button(text="🔄 Продлить подписку", callback_data="menu:buy")
        kb.button(text="📲 Подключиться", callback_data="dev:menu")
        kb.button(text="🫂 Реферальная программа", callback_data="menu:referral")
        kb.button(text="🛎️ Поддержка", url=_support_url())
    else:
        kb.button(text="💳 Купить подписку", callback_data="menu:buy")
        kb.button(text="🛎️ Написать в поддержку", url=_support_url())
    kb.button(text="🔙 Назад", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def _support_url() -> str:
    from config import SUPPORT_URL

    return SUPPORT_URL


def payment_methods_keyboard(
    code: str, back_data: str, *, prefix: str = "pay"
) -> InlineKeyboardMarkup:
    """СБП / Карта — both placeholders until a provider is wired.

    ``prefix`` is ``pay`` for a self-purchase or ``giftpay`` for a gift, so the
    handlers stay separate; ``code`` is the chosen tariff.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="🏦 СБП", callback_data=f"{prefix}:sbp:{code}")
    kb.button(text="💳 Банковская карта", callback_data=f"{prefix}:card:{code}")
    kb.button(text="🔙 Назад", callback_data=back_data)
    kb.adjust(1)
    return kb.as_markup()


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
    kb.button(text="📤 Поделиться", callback_data="share:open")
    kb.button(text="🔙 Назад", callback_data="menu:main")
    kb.adjust(2, 2, 2, 1, 1)
    return kb.as_markup()


def device_keyboard(
    *,
    download_url: str | None,
    download_label: str,
    connect_url: str | None = None,
    connect_incy_url: str | None = None,
) -> InlineKeyboardMarkup:
    """A single device instruction screen (screens 3-8).

    The subscription key is shown in the message text (tap-to-copy). When a
    branded connect page is configured, primary "Открыть в Happ" / "Открыть в
    Incy" buttons open it (auto-import the key); otherwise users paste the key by
    hand. Plus the app download link and navigation: Back / Main menu.
    """
    kb = InlineKeyboardBuilder()
    if connect_url:
        kb.button(text="🚀 Открыть в Happ", url=connect_url)
    if connect_incy_url:
        kb.button(text="🚀 Открыть в Incy", url=connect_incy_url)
    if download_url:
        kb.button(text=download_label, url=download_url)
    kb.button(text="🔙 Назад", callback_data="dev:menu")
    kb.button(text="🏠 Главное меню", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def share_keyboard() -> InlineKeyboardMarkup:
    """Screen 9 — share the access link."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📥 Копировать ссылку", callback_data="share:copy")
    kb.button(text="⤵️ QR-код", callback_data="share:qr")
    kb.button(text="🔙 Назад", callback_data="dev:menu")
    kb.adjust(1)
    return kb.as_markup()


def qr_close_keyboard() -> InlineKeyboardMarkup:
    """Screen 10 — close the QR photo."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Закрыть", callback_data="qr:close")
    kb.adjust(1)
    return kb.as_markup()


def buy_keyboard(*, renew: bool = False) -> InlineKeyboardMarkup:
    """Compact entry point to the tariff list (used by reminders / offers)."""
    kb = InlineKeyboardBuilder()
    kb.button(
        text="🔄 Продлить подписку" if renew else "💳 Купить подписку",
        callback_data="menu:buy",
    )
    kb.button(text="🔙 Главное меню", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def offer_keyboard(button_text: str) -> InlineKeyboardMarkup:
    """Single call-to-action (renew / restore / buy with discount) → buy flow."""
    kb = InlineKeyboardBuilder()
    kb.button(text=button_text, callback_data="menu:buy")
    kb.button(text="🔙 Главное меню", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def tariffs_keyboard(rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """Tariff list. ``rows`` is ``[(callback_data, label), ...]`` so the handler
    can bake the (optionally discounted) price into each label."""
    kb = InlineKeyboardBuilder()
    for data, label in rows:
        kb.button(text=label, callback_data=data)
    kb.button(text="🔙 Назад", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def referral_keyboard(share_url: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🫂 Пригласить друга", url=share_url)
    kb.button(text="🔙 Назад", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


# --- Admin ---

def admin_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Дашборд", callback_data="admin:stats")
    kb.button(text="💳 Платежи", callback_data="admin:pay:0")
    kb.button(text="🫂 Рефералы", callback_data="admin:ref:0")
    kb.button(text="👤 Найти пользователя", callback_data="admin:find")
    kb.button(text="📢 Рассылка", callback_data="admin:broadcast")
    kb.adjust(1)
    return kb.as_markup()


def admin_dashboard_actions() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Обновить", callback_data="admin:stats")
    kb.button(text="💳 Платежи", callback_data="admin:pay:0")
    kb.button(text="🫂 Рефералы", callback_data="admin:ref:0")
    kb.button(text="👤 Найти пользователя", callback_data="admin:find")
    kb.button(text="⬅️ Админка", callback_data="admin:home")
    kb.adjust(1)
    return kb.as_markup()


def admin_pager(prefix: str, page: int, *, has_prev: bool, has_next: bool, extra=None) -> InlineKeyboardMarkup:
    """Left/right pager used by the Payments and Referrals tabs. ``prefix`` is the
    callback stem (e.g. ``admin:pay``); ``extra`` is a list of (text, cb) rows
    added above the navigation."""
    kb = InlineKeyboardBuilder()
    for text, cb in (extra or []):
        kb.button(text=text, callback_data=cb)
    if has_prev:
        kb.button(text="⬅️ Назад", callback_data=f"{prefix}:{page - 1}")
    if has_next:
        kb.button(text="Вперёд ➡️", callback_data=f"{prefix}:{page + 1}")
    kb.button(text="🏠 Админка", callback_data="admin:home")
    # one row for nav arrows, the rest stacked
    nav = (1 if has_prev else 0) + (1 if has_next else 0)
    layout = [1] * len(extra or [])
    if nav:
        layout.append(nav)
    layout.append(1)
    kb.adjust(*layout)
    return kb.as_markup()


def admin_user_actions(telegram_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Выдать доступ", callback_data=f"admin:grant:{telegram_id}")
    kb.button(text="🚫 Лишить доступа", callback_data=f"admin:revoke:{telegram_id}")
    kb.button(text="🧾 История платежей", callback_data=f"admin:history:{telegram_id}")
    kb.button(text="⬅️ Админка", callback_data="admin:home")
    kb.adjust(1)
    return kb.as_markup()


def admin_grant_cancel(telegram_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Отмена", callback_data=f"admin:card:{telegram_id}")
    return kb.as_markup()


def admin_broadcast_segments() -> InlineKeyboardMarkup:
    """One button per segment, labelled from the DB segment registry."""
    from database import SEGMENTS

    kb = InlineKeyboardBuilder()
    for code, (label, _sql) in SEGMENTS.items():
        kb.button(text=label, callback_data=f"bcast:{code}")
    kb.button(text="⬅️ Отмена", callback_data="admin:home")
    kb.adjust(1)
    return kb.as_markup()


def admin_broadcast_builder(
    *, disc_pct: int | None = None, disc_days: int | None = None, channel: bool = False
) -> InlineKeyboardMarkup:
    """Compose-step keyboard: optionally attach buttons, then send."""
    kb = InlineKeyboardBuilder()
    if disc_pct:
        kb.button(
            text=f"✏️ Скидка: −{disc_pct}% / {disc_days} дн.",
            callback_data="bcastbtn:disc",
        )
    else:
        kb.button(text="💸 + Кнопка «Купить со скидкой»", callback_data="bcastbtn:disc")
    kb.button(
        text=("✅ Канал прикреплён" if channel else "📣 + Кнопка «Перейти в канал»"),
        callback_data="bcastbtn:chan",
    )
    kb.button(text="🚀 Отправить рассылку", callback_data="bcast:send")
    kb.button(text="⬅️ Отмена", callback_data="admin:home")
    kb.adjust(1)
    return kb.as_markup()


def broadcast_user_markup(
    disc_pct: int | None, disc_days: int | None, channel: bool
) -> InlineKeyboardMarkup | None:
    """The inline buttons attached to the message recipients receive."""
    from config import CHANNEL_URL

    kb = InlineKeyboardBuilder()
    has_any = False
    if disc_pct and disc_days:
        kb.button(
            text=f"🔥 Купить со скидкой −{disc_pct}%",
            callback_data=f"promo:{disc_pct}:{disc_days}",
        )
        has_any = True
    if channel:
        if CHANNEL_URL:
            kb.button(text="📣 Перейти в канал", url=CHANNEL_URL)
        else:
            kb.button(text="📣 Перейти в канал", callback_data="chan:soon")
        has_any = True
    if not has_any:
        return None
    kb.adjust(1)
    return kb.as_markup()
