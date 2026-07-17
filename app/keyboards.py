"""Inline keyboards. Most screens are stateless callback-data, no FSM."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import emoji


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu:main")]
        ]
    )


# --- Main menu / personal cabinet ---

def main_menu_keyboard(*, has_active_sub: bool) -> InlineKeyboardMarkup:
    from config import BYPASS_ENABLED

    sub_text = "Продлить подписку" if has_active_sub else "Купить подписку"

    kb = InlineKeyboardBuilder()
    # Bot API button styles: "primary" (blue), "success" (green), "danger" (red).
    # icon_custom_emoji_id puts a premium emoji to the left of the label.
    kb.button(text="Подключиться", callback_data="dev:menu",
              style="primary", icon_custom_emoji_id=emoji.CONNECT)
    kb.button(text="📲 Добавить устройство", callback_data="hw:add")
    kb.button(text="Личный кабинет", callback_data="menu:cabinet",
              icon_custom_emoji_id=emoji.CABINET)
    # Right under the cabinet: «Купить ГБ» | «Купить/Продлить подписку».
    if BYPASS_ENABLED:
        kb.button(text="Купить ГБ", callback_data="tr:open", icon_custom_emoji_id=emoji.GB)
        kb.button(text=sub_text, callback_data="menu:buy",
                  style="primary", icon_custom_emoji_id=emoji.SUB)
        buy_row = (2,)
    else:
        kb.button(text=sub_text, callback_data="menu:buy",
                  style="primary", icon_custom_emoji_id=emoji.SUB)
        buy_row = (1,)
    kb.button(text="Реферальная программа", callback_data="menu:referral",
              icon_custom_emoji_id=emoji.REFERRAL)
    kb.button(text="Подарить", callback_data="gift:open", icon_custom_emoji_id=emoji.GIFT)
    kb.button(text="Помощь", callback_data="help:open", icon_custom_emoji_id=emoji.HELP)
    kb.button(text="О сервисе", callback_data="about:open", icon_custom_emoji_id=emoji.ABOUT)
    kb.adjust(1, 1, 1, *buy_row, 2, 2)
    return kb.as_markup()


def cabinet_keyboard(*, has_active_sub: bool, has_bypass: bool = False) -> InlineKeyboardMarkup:
    from config import BYPASS_ENABLED

    kb = InlineKeyboardBuilder()
    if has_active_sub:
        kb.button(text="Продлить подписку", callback_data="menu:buy",
                  style="primary", icon_custom_emoji_id=emoji.SUB)
        kb.button(text="Подключиться", callback_data="dev:menu",
                  style="primary", icon_custom_emoji_id=emoji.CONNECT)
    else:
        kb.button(text="Купить подписку", callback_data="menu:buy",
                  style="primary", icon_custom_emoji_id=emoji.SUB)
    if BYPASS_ENABLED:
        kb.button(
            text="Докупить ГБ обхода" if has_bypass else "Обход блокировок",
            callback_data="tr:open", icon_custom_emoji_id=emoji.GB,
        )
    kb.button(text="Реферальная программа", callback_data="menu:referral",
              icon_custom_emoji_id=emoji.REFERRAL)
    kb.button(text="Поддержка", url=_support_url(), icon_custom_emoji_id=emoji.HELP)
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data="menu:main")
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
    kb.button(text="СБП", callback_data=f"{prefix}:sbp:{code}", icon_custom_emoji_id=emoji.SBP)
    kb.button(text="Банковская карта", callback_data=f"{prefix}:card:{code}",
              icon_custom_emoji_id=emoji.CARD)
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data=back_data)
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
    kb.button(text="🎁 Забрать бесплатный доступ", callback_data="onb:claim")
    kb.adjust(1)
    return kb.as_markup()


def devices_keyboard() -> InlineKeyboardMarkup:
    """Screen 2 — choose a device to connect. Each device opens its download
    step (``dl:<key>``); TV devices keep their QR-import instructions."""
    kb = InlineKeyboardBuilder()
    kb.button(text="iOS", callback_data="dl:ios", icon_custom_emoji_id=emoji.DEV_IOS)
    kb.button(text="Android", callback_data="dl:android", icon_custom_emoji_id=emoji.DEV_ANDROID)
    kb.button(text="MacOS", callback_data="dl:macos", icon_custom_emoji_id=emoji.DEV_MAC)
    kb.button(text="Windows", callback_data="dl:windows", icon_custom_emoji_id=emoji.DEV_WINDOWS)
    kb.button(text="Android TV", callback_data="dl:androidtv", icon_custom_emoji_id=emoji.DEV_ANDROIDTV)
    kb.button(text="Apple TV", callback_data="dl:appletv", icon_custom_emoji_id=emoji.DEV_APPLETV)
    kb.button(text="Поделиться", callback_data="share:open", icon_custom_emoji_id=emoji.SHARE)
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data="menu:main")
    kb.adjust(2, 2, 2, 1, 1)
    return kb.as_markup()


def share_keyboard() -> InlineKeyboardMarkup:
    """Screen 9 — share the access link."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📥 Копировать ссылку", callback_data="share:copy")
    kb.button(text="⤵️ QR-код", callback_data="share:qr")
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data="dev:menu")
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


def manage_sub_keyboard() -> InlineKeyboardMarkup:
    """Reminder CTA → the subscription-management screen (``sub:manage``)."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Продлить доступ", callback_data="sub:manage")
    kb.adjust(1)
    return kb.as_markup()


def offer_keyboard(
    button_text: str, *, pct: int | None = None, days: int = 1
) -> InlineKeyboardMarkup:
    """Single call-to-action → buy flow. When ``pct`` is given the button carries
    the discount (``promo:pct:days``), so clicking re-applies it on the spot —
    it never depends on a previously-stored (and possibly expired) offer."""
    kb = InlineKeyboardBuilder()
    cb = f"promo:{pct}:{days}" if pct else "menu:buy"
    kb.button(text=button_text, callback_data=cb)
    kb.button(text="🏠 Главное меню", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def tariffs_keyboard(
    rows: list[tuple[str, str, str | None, str | None]],
) -> InlineKeyboardMarkup:
    """Tariff list. ``rows`` is ``[(callback_data, label, icon_emoji_id, style),
    ...]`` so the handler bakes the (discounted) price, per-row premium icon and
    an optional button style ("success" highlights the year-promo pick)."""
    kb = InlineKeyboardBuilder()
    for data, label, icon, style in rows:
        kb.button(
            text=label, callback_data=data, icon_custom_emoji_id=icon, style=style
        )
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def referral_keyboard(share_url: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Пригласить друга", url=share_url, icon_custom_emoji_id=emoji.INVITE)
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data="menu:main")
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
    kb.button(text="🌐 Профили обхода", callback_data="admin:bypass_check")
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
    """One button per segment, labelled from the DB segment registry. The
    per-day buckets ("истекает через N" / "закончилась N назад") are packed
    two-per-row to stay compact, with each family kept on its own rows."""
    from database import SEGMENTS

    kb = InlineKeyboardBuilder()
    rows: list[int] = []
    pending = 0  # day-bucket buttons waiting to fill the current pair
    family: str | None = None

    def flush() -> None:
        nonlocal pending
        if pending:
            rows.append(pending)
            pending = 0

    for code, (label, _sql) in SEGMENTS.items():
        kb.button(text=label, callback_data=f"bcast:{code}")
        fam = "exp" if code.startswith("exp_") else "expd" if code.startswith("expd_") else None
        if fam is None:
            flush()
            family = None
            rows.append(1)
            continue
        if family is not None and fam != family:
            flush()  # don't mix two families in one row
        family = fam
        pending += 1
        if pending == 2:
            rows.append(2)
            pending = 0
    flush()
    kb.button(text="⬅️ Отмена", callback_data="admin:home")
    rows.append(1)
    kb.adjust(*rows)
    return kb.as_markup()


def admin_broadcast_builder(
    *,
    disc_pct: int | None = None,
    disc_days: int | None = None,
    channel: bool = False,
    referral: bool = False,
    bypass: bool = False,
    year: bool = False,
    buy: bool = False,
) -> InlineKeyboardMarkup:
    """Compose-step keyboard: optionally attach buttons, then send."""
    from config import YEAR_PROMO_PCT

    kb = InlineKeyboardBuilder()
    kb.button(
        text=("✅ Кнопка «Купить доступ»" if buy else "🛒 + Кнопка «Купить доступ»"),
        callback_data="bcastbtn:buy",
    )
    kb.button(
        text=(
            f"✅ Кнопка «1 год −{YEAR_PROMO_PCT}%»"
            if year
            else f"🏆 + Кнопка «1 год со скидкой {YEAR_PROMO_PCT}%»"
        ),
        callback_data="bcastbtn:year",
    )
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
    kb.button(
        text=(
            "✅ Кнопка «Пригласить друга»"
            if referral
            else "🫂 + Кнопка «Пригласить друга»"
        ),
        callback_data="bcastbtn:ref",
    )
    from config import BYPASS_ENABLED, CONNECT_PAGE_URL

    if BYPASS_ENABLED and CONNECT_PAGE_URL:
        kb.button(
            text=("✅ Кнопка «Добавить Обход»" if bypass else "🌐 + Кнопка «Добавить Обход»"),
            callback_data="bcastbtn:bypass",
        )
    kb.button(text="🚀 Отправить рассылку", callback_data="bcast:send")
    kb.button(text="⬅️ Отмена", callback_data="admin:home")
    kb.adjust(1)
    return kb.as_markup()


def broadcast_user_markup(
    disc_pct: int | None, disc_days: int | None, channel: bool, referral: bool = False,
    *, bypass_url: str | None = None, year: bool = False, buy: bool = False,
) -> InlineKeyboardMarkup | None:
    """The inline buttons attached to the message recipients receive.

    ``bypass_url`` is per-recipient (their bypass crypt4 key on the connect page),
    so the send loop builds this markup individually for each user."""
    from config import CHANNEL_URL, YEAR_PROMO_PCT

    kb = InlineKeyboardBuilder()
    has_any = False
    if buy:
        # Plain "open the tariff list" CTA (no discount). Own callback so it opens
        # a fresh tariffs message even under a photo broadcast (menu:buy edits).
        kb.button(text="🛒 Купить доступ", callback_data="buyaccess", style="primary")
        has_any = True
    if year:
        # Its own callback (not promo:pct:days) — the year offer is scoped to the
        # 1-year plan and opens a dedicated screen with a premium-emoji flash.
        kb.button(
            text=f"🏆 1 год со скидкой {YEAR_PROMO_PCT}%",
            callback_data="yearpromo",
            style="success",
            icon_custom_emoji_id=emoji.TROPHY,
        )
        has_any = True
    if bypass_url:
        kb.button(text="🌐 Добавить Обход 🤍", url=bypass_url)
        has_any = True
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
    if referral:
        kb.button(text="Пригласить друга", callback_data="menu:referral",
                  icon_custom_emoji_id=emoji.INVITE)
        has_any = True
    if not has_any:
        return None
    kb.adjust(1)
    return kb.as_markup()
