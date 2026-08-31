"""ELMA onboarding flow.

The whole user-facing journey lives here as a chain of edited messages:

    /start (no trial yet, no sub)  ──▶  Screen 1 — "почти завершено" + Забрать доступ
            └─ onb:claim  ──▶  Screen 2 — ELMA активирован + выбор устройства
                 ├─ dev:<device>  ──▶  Screens 3-8 — инструкция по подключению
                 └─ share:open    ──▶  Screen 9 — Поделиться (ссылка)
                      └─ share:qr  ──▶  Screen 10 — QR-код (фото)

    /start (trial already used, or an active subscription)  ──▶  главное меню

Everything is stateless callback-data; the only state is the user's
subscription row (whose ``subscription_url`` powers "Активировать" / share / QR).
"""
import asyncio
import html
import io
import logging
from urllib.parse import quote

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import emoji
from app.keyboards import (
    buy_keyboard,
    claim_keyboard,
    devices_keyboard,
    qr_close_keyboard,
    share_keyboard,
    welcome_keyboard,
)
from app.handlers.menu import show_main
from app.services import aggregator, billing, happ_crypto, incy_crypto, subscription_service
from app.utils import clean_username, convert_tg_emoji, safe_edit, send_screen, show_screen
from config import (
    ADMIN_IDS,
    APP_ANDROID_URL,
    APP_INCY_ANDROID_URL,
    APP_INCY_IOS_URL,
    APP_IOS_INTL_URL,
    APP_IOS_RU_URL,
    APP_MACOS_URL,
    APP_WINDOWS_URL,
    BYPASS_ENABLED,
    CONNECT_PAGE_URL,
    SUBSCRIPTION_ADMIN_ONLY,
    SUBSCRIPTION_BASE_URL,
    SUBSCRIPTION_SINGLE_KEY_FLOW,
    SUPPORT_URL,
    TRIAL_DAYS,
)
from database import (
    attribute_user,
    bump_stat_link_click,
    ensure_sub_token,
    get_bypass,
    get_subscription,
    set_referral,
    trial_available,
    upsert_user,
)

logger = logging.getLogger(__name__)
router = Router(name="onboarding")


# --- Screen copy ----------------------------------------------------------

WELCOME = (
    "<b>ELMA — интернет, который не играет на нервах.</b>\n\n"
    "⚡️ Высокая скорость\n"
    "♾️ Безлимитный трафик\n"
    "💎 От 199 ₽\n"
    "📱 5 устройств\n"
    "👥 Реферальная система\n"
    "🔒 Zero-logs\n"
    "🛡️ iOS · Android · MacOS · Windows · AndroidTV · Apple TV\n\n"
    f"🎁 Первые {TRIAL_DAYS} дня бесплатно\n\n"
    "Твой доступ готов. Нажми Start 👇"
)

SCREEN_1 = (
    "🌐 <b>Добро пожаловать в ELMA</b>\n\n"
    "VPN, который не подводит.\n"
    "Без блокировок. Без обрывов. Без нервов.\n\n"
    f"🎁 Первые {TRIAL_DAYS} дня — бесплатно"
)

SCREEN_2_TRIAL = (
    "✅ <b>ELMA активирована</b>\n\n"
    f"У вас {TRIAL_DAYS} дня бесплатно. Без ограничений, без карты.\n\n"
    "Выберите устройство — и мы проведём вас через установку "
    "шаг за шагом 🚀"
)

SCREEN_2_PAID = (
    "✅ <b>ELMA активирована</b>\n\n"
    "Premium-доступ открыт 🤍\n\n"
    "Выберите устройство — и мы проведём вас через установку "
    "шаг за шагом 🚀"
)

TRIAL_USED = (
    "🎁 Бесплатный доступ уже был использован.\n\n"
    "Чтобы вернуться в ELMA, оформи подписку 👇"
)

NO_ACCESS = (
    "Сначала забери бесплатный доступ к ELMA, "
    "чтобы получить ссылку для подключения 👇"
)

GIFT_REDEEMED = (
    "🎁 <b>Подарок активирован!</b>\n\n"
    "Добро пожаловать в ELMA 🤍\n\n"
    "Подключи устройство 👇"
)

SHARE = (
    "📱 <b>Отправь ссылку на другое устройство</b>\n\n"
    "🔗\n"
    "<code>{link}</code>"
)

QR_CAPTION = "Ваш QR-код ELMA 🤍"


# --- Connection flow ------------------------------------------------------
#
# Phones/desktops use a two-step flow:
#   dl:<device>  → download screen ("Скачайте Happ" + store links + «Дальше»)
#   cn:<device>  → connect screen  (photo + «Добавить VPN ключ» / вручную / help)
# TV devices can't open a deep link, so dl:<device> shows a QR-import guide.

# Premium ⚡️ custom emoji flashed after «Готово», just before the main menu.
PREMIUM_BOLT = "![⚡️](tg://emoji?id=5456140674028019486)"

DOWNLOAD_TEXT = (
    "📲 <b>Скачайте Happ</b> — это бесплатно и займёт минуту\n\n"
    "Уже есть? Жми «Дальше» 👇"
)

CONNECT_TEXT = (
    "🌐 <b>Подключитесь в одно нажатие</b>\n\n"
    "Нажмите кнопку ниже с названием вашего приложения — "
    "ключ добавится автоматически."
)

# Platforms where Incy is available (App Store / Play Market). Incy has no
# Windows client and TVs can't open a deep link, so both stay Happ-only.
_INCY_PLATFORMS = frozenset({"ios", "android", "macos"})

# Phone/desktop devices: Happ download buttons (label, url) and an optional
# download-screen photo (a key in app.screens). MacOS mirrors the Windows flow.
# Incy-capable platforms also list an Incy download link (macOS reuses the iOS
# App Store entry — Apple Silicon Macs install the iOS app).
PHONE_DEVICES: dict[str, dict] = {
    "ios": {
        "downloads": [
            ("📲 Скачать Incy", APP_INCY_IOS_URL),
            ("📲 Скачать Happ (Россия)", APP_IOS_RU_URL),
            ("📲 Скачать Happ (другой регион)", APP_IOS_INTL_URL),
        ],
        "dl_photo": None,
    },
    "android": {
        "downloads": [
            ("📲 Скачать Incy", APP_INCY_ANDROID_URL),
            ("📲 Скачать Happ", APP_ANDROID_URL),
        ],
        "dl_photo": "dl_android",
    },
    "macos": {
        "downloads": [
            ("📲 Скачать Incy", APP_INCY_IOS_URL),
            ("📲 Скачать Happ", APP_MACOS_URL),
        ],
        "dl_photo": None,
    },
    "windows": {
        "downloads": [("📲 Скачать Happ", APP_WINDOWS_URL)],
        "dl_photo": None,
    },
}

# TV devices keep the QR-import guide (a TV has no Happ deep link). {key} is the
# expandable copyable access key.
TV_DEVICES: dict[str, str] = {
    "androidtv": (
        "📺 <b>Подключение · Android TV</b>\n\n"
        "1️⃣ Установи <b>Happ</b> из Google Play на телевизоре\n"
        "2️⃣ Открой Happ → <b>Управление</b> → <b>Импорт с телефона</b>\n"
        "   (в англ. версии — <i>Control → Import config from phone</i>)\n"
        "3️⃣ В этом боте на телефоне открой "
        "<b>«📤 Поделиться»</b> → <b>«⤵️ QR-код»</b>\n"
        "4️⃣ Наведи камеру телевизора на QR-код с телефона\n"
        "5️⃣ Выбери сервер и нажми <b>«Подключиться»</b> 🚀\n\n"
        "{key}"
    ),
    "appletv": (
        "📺 <b>Подключение · Apple TV</b>\n\n"
        "1️⃣ Установи <b>Happ</b> на iPhone/iPad "
        "и добавь профиль (как в инструкции для iOS)\n"
        "2️⃣ На Apple TV установи то же приложение из App Store\n"
        "3️⃣ Войди тем же аккаунтом или импортируй профиль по QR-коду\n"
        "4️⃣ Выбери сервер и нажми <b>«Подключиться»</b> 🚀\n\n"
        "{key}"
    ),
}


def _connect_link(deeplink: str | None) -> str | None:
    """https landing-page URL that auto-opens the app (key in the #fragment, so
    it never reaches the web server), or None if no connect page is configured."""
    if not CONNECT_PAGE_URL or not deeplink:
        return None
    return f"{CONNECT_PAGE_URL}#{quote(deeplink, safe='')}"


def _add_connect_button(kb, label: str, deeplink: str, fallback_cb: str, *, style: str | None = None) -> None:
    """One-tap add button: connect-page redirect (URL) if available, else a
    callback that reveals the key as a copyable quote."""
    page = _connect_link(deeplink)
    if page and style:
        kb.button(text=label, url=page, style=style)
    elif page:
        kb.button(text=label, url=page)
    elif style:
        kb.button(text=label, callback_data=fallback_cb, style=style)
    else:
        kb.button(text=label, callback_data=fallback_cb)


def _labeled_key(label: str, key: str) -> str:
    """A titled key in a collapsed, tap-to-copy quote."""
    return f"{label}\n<blockquote expandable><code>{html.escape(key)}</code></blockquote>"


def _key_block(happ_link: str) -> str:
    return (
        "🔑 <b>Твой ключ доступа</b>\n"
        f"<blockquote expandable><code>{html.escape(happ_link)}</code></blockquote>"
    )


# --- Helpers --------------------------------------------------------------

async def _active_sub_raw(telegram_id: int) -> str | None:
    """Raw subscription URL of an active subscription, else None."""
    sub = await get_subscription(telegram_id)
    if sub is not None and sub["status"] == "active" and sub["subscription_url"]:
        return sub["subscription_url"]
    return None


async def _active_sub_url(telegram_id: int) -> str | None:
    """Return the user-facing connection link of an active subscription, else
    None. The raw subscription URL is wrapped into a Happ crypt link
    (``happ://crypt4/…``) so the real address stays hidden from the user."""
    return happ_crypto.format_for_user(await _active_sub_raw(telegram_id))


async def _device_select_text(telegram_id: int) -> str:
    """Screen-2 copy by access type: Premium for any paid/admin/gift/referral
    access, guest copy for the free trial (or no active subscription yet)."""
    sub = await get_subscription(telegram_id)
    if sub is not None and sub["status"] == "active" and sub["source"] != "trial":
        return SCREEN_2_PAID
    return SCREEN_2_TRIAL


def _make_qr_png(data: str) -> bytes | None:
    """Render ``data`` to a PNG QR code; None if the lib is unavailable."""
    try:
        import qrcode
    except ImportError:  # pragma: no cover - declared in requirements
        logger.warning("qrcode library not installed; cannot render QR")
        return None
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# --- Welcome / Screen 1 ---------------------------------------------------

def _parse_ref(args: str | None) -> int | None:
    """Extract a referrer id from a ``ref_<id>`` deep-link payload."""
    if not args or not args.startswith("ref_"):
        return None
    try:
        return int(args[4:])
    except ValueError:
        return None


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject) -> None:
    user = message.from_user
    is_new = await upsert_user(
        user.id, clean_username(user.username), user.language_code or "ru"
    )
    args = command.args or ""

    # Gift redemption works for any user (new or returning).
    if args.startswith("gift_"):
        try:
            tariff = await billing.redeem_gift(message.bot, user.id, args[5:])
        except Exception:  # noqa: BLE001
            logger.exception("Gift redemption failed for %s", user.id)
            tariff = None
        if tariff is not None:
            await message.answer(GIFT_REDEEMED, reply_markup=devices_keyboard())
            return

    # «Продлить» from the subscription client's header card: /start renew.
    if args == "renew":
        from app.handlers.purchase import _tariffs_view

        text, markup = await _tariffs_view(user.id)
        await message.answer(text, reply_markup=markup)
        return

    # Promo-code deep link: /start promo_<code>.
    if args.startswith("promo_"):
        from app.services import promo_service

        _, msg, show_buy = await promo_service.apply_promo(message.bot, user.id, args[6:])
        kb = InlineKeyboardBuilder()
        if show_buy:
            kb.button(text="Выбрать тариф", callback_data="menu:buy", style="success")
        kb.button(text="🏠 Главное меню", callback_data="menu:main")
        kb.adjust(1)
        await message.answer(msg, reply_markup=kb.as_markup())
        return

    # Marketing stats-link attribution: /start s-<slug>. Counts the click and,
    # for a new user, stamps the acquisition source (immutable). Falls through
    # to the normal onboarding below.
    if args.startswith("s-"):
        link_id = await bump_stat_link_click(args[2:])
        if is_new and link_id:
            await attribute_user(user.id, link_id)

    if is_new:
        logger.info("New user onboarded: %s (@%s)", user.id, user.username)
        referrer_id = _parse_ref(args)
        if referrer_id and referrer_id != user.id:
            if await set_referral(user.id, referrer_id):
                logger.info("User %s referred by %s", user.id, referrer_id)

    # First visit (trial never used and no active subscription) -> onboarding;
    # returning users (trial used, or any active sub) -> main menu.
    sub = await get_subscription(user.id)
    has_active = sub is not None and sub["status"] == "active"
    if await trial_available(user.id) and not has_active:
        await message.answer(SCREEN_1, reply_markup=claim_keyboard())
    else:
        await show_main(message, user.id)


@router.callback_query(F.data == "menu:home")
async def cb_home(call: CallbackQuery) -> None:
    await safe_edit(call.message, WELCOME, reply_markup=welcome_keyboard())
    await call.answer()


@router.callback_query(F.data == "onb:start")
async def cb_screen1(call: CallbackQuery) -> None:
    await safe_edit(call.message, SCREEN_1, reply_markup=claim_keyboard())
    await call.answer()


# --- Screen 2: claim trial + device selection -----------------------------

@router.callback_query(F.data == "onb:claim")
async def cb_claim(call: CallbackQuery) -> None:
    await call.answer()
    user_id = call.from_user.id
    try:
        sub = await subscription_service.activate_trial(user_id, TRIAL_DAYS)
    except Exception:  # noqa: BLE001 - VPN/DB failure -> safe retry
        logger.exception("Trial activation failed for %s", user_id)
        await safe_edit(
            call.message,
            "⚠️ Не удалось активировать доступ — попробуй ещё раз через минуту.",
            reply_markup=claim_keyboard(),
        )
        return

    if sub is None:
        # Trial already used: show device selection if a paid subscription is
        # still active, otherwise nudge to buy.
        current = await get_subscription(user_id)
        if current is None or current["status"] != "active":
            await safe_edit(call.message, TRIAL_USED, reply_markup=buy_keyboard())
            return
        text = SCREEN_2_PAID if current["source"] != "trial" else SCREEN_2_TRIAL
        await show_screen(call.message, "devices", text, reply_markup=devices_keyboard())
        return

    # Trial newly activated -> straight to device selection.
    logger.info("Trial activated for %s", user_id)
    # Tell the inviter their friend joined (bonus comes on first purchase).
    await billing.notify_referrer_on_trial(call.bot, user_id)
    await show_screen(
        call.message, "devices", SCREEN_2_TRIAL, reply_markup=devices_keyboard()
    )


@router.message(Command("connect"))
async def cmd_connect(message: Message) -> None:
    text = await _device_select_text(message.from_user.id)
    await send_screen(
        message.bot, message.chat.id, "devices", text, reply_markup=devices_keyboard()
    )


@router.callback_query(F.data == "dev:menu")
async def cb_devices(call: CallbackQuery) -> None:
    text = await _device_select_text(call.from_user.id)
    await show_screen(call.message, "devices", text, reply_markup=devices_keyboard())
    await call.answer()


# --- Connection: download → connect → done --------------------------------

async def _happ_key(user_id: int) -> str | None:
    """Happ deep link for the user's active subscription, or None."""
    raw = await _active_sub_raw(user_id)
    return happ_crypto.format_for_user(raw) if raw else None


async def _bypass_key(user_id: int) -> str | None:
    """Happ crypt4 deep link for the user's bypass entity, or None."""
    if not BYPASS_ENABLED:
        return None
    row = await get_bypass(user_id)
    if not row or not row["subscription_url"]:
        return None
    return happ_crypto.format_for_user(row["subscription_url"])


async def _incy_vpn_key(user_id: int) -> str | None:
    """Incy crypt1 deep link for the user's subscription, or None (sidecar)."""
    raw = await _active_sub_raw(user_id)
    return await incy_crypto.to_incy_link(raw) if raw else None


async def _incy_bypass_key(user_id: int) -> str | None:
    """Incy crypt1 deep link for the user's bypass entity, or None."""
    if not BYPASS_ENABLED:
        return None
    row = await get_bypass(user_id)
    if not row or not row["subscription_url"]:
        return None
    return await incy_crypto.to_incy_link(row["subscription_url"])


# --- Aggregator (single-key) connection -----------------------------------
#
# With the aggregator, premium and bypass are merged into ONE link served from
# our domain — the user gets a single key (no VPN/Обход split). Two clients,
# Happ and Incy, each with an encrypted deep link of the *same* aggregated URL.
# Gated by SUBSCRIPTION_ADMIN_ONLY on the beta; when the gate doesn't pass, the
# legacy dual-key flow below is used unchanged.

CONNECT_AGG_TEXT = (
    "⚡️ <b>Подключитесь в одно нажатие</b>\n\n"
    "Нажмите <b>«Добавить ключ»</b> в вашем приложении — "
    "подписка импортируется автоматически.\n\n"
    "Если по каким-то причинам не открылось — "
    "нажмите <b>«Настроить вручную»</b> ниже."
)


def _aggregator_enabled(telegram_id: int) -> bool:
    """Whether the connection flow OFFERS the single aggregated key.

    Off by default (SUBSCRIPTION_SINGLE_KEY_FLOW=False) — users get the legacy
    two links (VPN + Обход). This gates only what the connect screens SHOW; the
    /sub aggregator endpoint stays live regardless, so anyone who already
    imported an aggregator link keeps working. Flip the flag to re-enable the
    single-key screens."""
    if not SUBSCRIPTION_SINGLE_KEY_FLOW or not SUBSCRIPTION_BASE_URL:
        return False
    return not SUBSCRIPTION_ADMIN_ONLY or telegram_id in ADMIN_IDS


async def _agg_url(telegram_id: int) -> str | None:
    """The user's single aggregated subscription URL, or None when the
    aggregator is off for them or they have nothing to serve (no active premium
    and no bypass — the /sub link would 404)."""
    if not _aggregator_enabled(telegram_id):
        return None
    has_premium = bool(await _active_sub_raw(telegram_id))
    has_bypass = bool(await _bypass_raw(telegram_id))
    if not has_premium and not has_bypass:
        return None
    token = await ensure_sub_token(telegram_id)
    return aggregator.sub_link(token)


def _access_gate_kb():
    """Buy options shown when a premium key is requested without an active sub —
    a subscription, and (if bypass is on) buying GB traffic instead."""
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Купить подписку", callback_data="menu:buy", style="success")
    if BYPASS_ENABLED:
        kb.button(text="🌐 Обход блокировок (ГБ)", callback_data="tr:open", style="success")
    kb.button(text="🏠 Главное меню", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


async def _no_access(call: CallbackQuery) -> None:
    """Shown when a premium connection screen is reached without an active sub."""
    text = "🔒 Доступ не активен.\n\nОформи подписку, чтобы получить ключ 👇"
    if BYPASS_ENABLED:
        text = (
            "🔒 Премиум-подписка не активна.\n\n"
            "Оформи подписку — или подключи обход блокировок по трафику (ГБ) 👇"
        )
    await safe_edit(call.message, text, reply_markup=_access_gate_kb())
    await call.answer()


async def _show_tv_guide(call: CallbackQuery, key: str) -> None:
    raw = await _active_sub_raw(call.from_user.id)
    if not raw:
        await _no_access(call)
        return
    happ = happ_crypto.format_for_user(raw)
    kb = InlineKeyboardBuilder()
    kb.button(text="📤 Поделиться", callback_data="share:open", style="primary")
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data="dev:menu")
    kb.adjust(1)
    await safe_edit(
        call.message, TV_DEVICES[key].format(key=_key_block(happ)),
        reply_markup=kb.as_markup(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("dl:"))
async def cb_download(call: CallbackQuery) -> None:
    """Step 1: download screen. TV devices fall through to the QR-import guide."""
    key = call.data.split(":", 1)[1]
    if key in TV_DEVICES:
        await _show_tv_guide(call, key)
        return
    device = PHONE_DEVICES.get(key)
    if device is None:
        await call.answer()
        return
    kb = InlineKeyboardBuilder()
    for label, url in device["downloads"]:
        if url:
            kb.button(text=label, url=url)
    kb.button(text="➡️ Дальше", callback_data=f"cn:{key}")
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data="dev:menu")
    kb.adjust(1)
    if device["dl_photo"]:
        await show_screen(call.message, device["dl_photo"], DOWNLOAD_TEXT, reply_markup=kb.as_markup())
    else:
        await safe_edit(call.message, DOWNLOAD_TEXT, reply_markup=kb.as_markup())
    await call.answer()


async def _connect_agg(call: CallbackQuery, key: str, agg_url: str) -> None:
    """Aggregator connect screen: two one-tap buttons (Happ / Incy) that add the
    single merged key — no VPN/Обход split."""
    kb = InlineKeyboardBuilder()
    # Each add-key button on its own full-width row — side-by-side rows truncate
    # the label to «Добавить…».
    _add_connect_button(
        kb, "📥 Добавить ключ в Happ", happ_crypto.format_for_user(agg_url),
        "aggadd:happ", style="primary",
    )
    if key in _INCY_PLATFORMS:
        incy_dl = await incy_crypto.to_incy_link(agg_url)
        if incy_dl:
            _add_connect_button(
                kb, "💚 Добавить ключ в Incy", incy_dl, "aggadd:incy", style="success"
            )
    kb.button(text="✅ Готово", callback_data="onb:done", style="success")
    kb.button(text="⚙️ Настроить вручную", callback_data=f"manual:{key}")
    kb.button(text="💬 Нужна помощь", url=SUPPORT_URL)
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data=f"dl:{key}")
    kb.adjust(1)
    await show_screen(call.message, "connect", CONNECT_AGG_TEXT, reply_markup=kb.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("cn:"))
async def cb_connect(call: CallbackQuery) -> None:
    """Step 2: connect screen — one-tap key import (or copyable-key fallback)."""
    key = call.data.split(":", 1)[1]
    device = PHONE_DEVICES.get(key)
    if device is None:
        await call.answer()
        return

    uid = call.from_user.id
    # Aggregator single-key flow (gated) takes precedence over legacy dual-key.
    agg = await _agg_url(uid)
    if agg:
        await _connect_agg(call, key, agg)
        return

    happ = await _happ_key(uid)
    if not happ:
        await _no_access(call)
        return

    kb = InlineKeyboardBuilder()
    rows: list[int] = []

    # VPN row: Happ (left) + Incy (right, iOS/Android/macOS).
    _add_connect_button(kb, "🔑 Happ VPN", happ, f"addkey:{key}")
    vpn_n = 1
    if key in _INCY_PLATFORMS:
        incy_vpn = await _incy_vpn_key(uid)
        if incy_vpn:
            _add_connect_button(kb, "💚 Incy VPN", incy_vpn, f"addvincy:{key}")
            vpn_n = 2
    rows.append(vpn_n)

    # Обход row (only if the user has bypass): Happ (left) + Incy (right).
    bp = await _bypass_key(uid)
    if bp:
        _add_connect_button(kb, "🌐 Happ Обход", bp, f"addbp:{key}")
        bp_n = 1
        if key in _INCY_PLATFORMS:
            incy_bp = await _incy_bypass_key(uid)
            if incy_bp:
                _add_connect_button(kb, "💚 Incy Обход", incy_bp, f"addbpincy:{key}")
                bp_n = 2
        rows.append(bp_n)

    kb.button(text="✅ Готово", callback_data="onb:done")
    kb.button(text="📋 Установить вручную", callback_data=f"manual:{key}")
    kb.button(text="💬 Нужна помощь", url=SUPPORT_URL)
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data=f"dl:{key}")
    rows += [1, 1, 1, 1]
    kb.adjust(*rows)
    await show_screen(call.message, "connect", CONNECT_TEXT, reply_markup=kb.as_markup())
    await call.answer()


async def _manual_agg(call: CallbackQuery, key: str, agg_url: str) -> None:
    """Aggregator manual screen: two encrypted keys (Happ + Incy) of the single
    merged link, each in a tap-to-copy quote."""
    parts = [
        "📋 <b>Ручная установка — 3 простых шага</b>\n",
        "1. Нажмите на ключ ниже — он скопируется",
        "2. Откройте Happ или Incy",
        "3. Нажмите <b>➕</b> в правом верхнем углу или "
        "<b>«Вставить»</b> (Incy) и вставьте из буфера 📋",
        "<i>Повторите для второго ключа.</i>\n",
        _labeled_key(
            "🔑 <b>Ключ Happ</b> (скопируйте и вставьте в приложение):",
            happ_crypto.format_for_user(agg_url),
        ),
    ]
    if key in _INCY_PLATFORMS:
        incy_key = await incy_crypto.to_incy_link(agg_url)
        if incy_key:
            parts.append(_labeled_key(
                "💚 <b>Ключ Incy</b> (скопируйте и вставьте в приложение):", incy_key,
            ))
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Готово", callback_data="onb:done", style="success")
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data=f"cn:{key}")
    kb.adjust(1)
    await safe_edit(call.message, "\n".join(parts), reply_markup=kb.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("manual:"))
async def cb_manual(call: CallbackQuery) -> None:
    key = call.data.split(":", 1)[1]
    uid = call.from_user.id

    # Aggregator single-key flow (gated) takes precedence over legacy dual-key.
    agg = await _agg_url(uid)
    if agg:
        await _manual_agg(call, key, agg)
        return

    happ = await _happ_key(uid)
    if not happ:
        await _no_access(call)
        return

    parts = [
        "📋 <b>Ручная установка — 3 простых шага</b>\n",
        "1. Нажмите на ключ ниже — он скопируется",
        "2. Откройте Happ/Incy",
        "3. Нажмите ➕ в правом верхнем углу (или «Вставить» в Incy) "
        "и вставьте из буфера 📋",
        "<i>Повторите для второго ключа.</i>\n",
        _labeled_key("🔑 <b>VPN ключ Happ</b> (обычные безлимитные сервера):", happ),
    ]
    bp = await _bypass_key(uid)
    if bp:
        parts.append(_labeled_key("🌐 <b>Обход ключ Happ</b> (белые списки РФ):", bp))
    # Incy keys — only on platforms with an Incy client (iOS / Android / macOS).
    if key in _INCY_PLATFORMS:
        iv = await _incy_vpn_key(uid)
        if iv:
            parts.append(_labeled_key("💚 <b>VPN ключ Incy</b> (обычные безлимитные сервера):", iv))
        if bp:
            ib = await _incy_bypass_key(uid)
            if ib:
                parts.append(_labeled_key("💚 <b>Обход ключ Incy</b> (белые списки РФ):", ib))

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Готово", callback_data="onb:done")
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data=f"cn:{key}")
    kb.adjust(1)
    await safe_edit(call.message, "\n".join(parts), reply_markup=kb.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("aggadd:"))
async def cb_aggadd(call: CallbackQuery) -> None:
    """No-connect-page fallback: reveal the aggregated key (Happ or Incy) as a
    tap-to-copy quote."""
    client = call.data.split(":", 1)[1]  # happ | incy
    agg = await _agg_url(call.from_user.id)
    if not agg:
        await call.answer("Ключ недоступен", show_alert=True)
        return
    if client == "incy":
        key = await incy_crypto.to_incy_link(agg)
        app, tip = "Incy", "💚"
    else:
        key = happ_crypto.format_for_user(agg)
        app, tip = "Happ", "🔑"
    if not key:
        await call.answer("Ключ недоступен", show_alert=True)
        return
    await call.message.answer(
        f"{tip} Нажми на ключ — он скопируется, затем вставь его в {app}:\n\n"
        f"<blockquote expandable><code>{html.escape(key)}</code></blockquote>"
    )
    await call.answer("Ключ отправлен ниже 👇")


@router.callback_query(F.data.startswith("addkey:"))
async def cb_addkey(call: CallbackQuery) -> None:
    """Connect-page fallback: reveal the Happ key as a tap-to-copy quote."""
    happ = await _happ_key(call.from_user.id)
    if not happ:
        await call.answer("Сначала забери доступ", show_alert=True)
        return
    await call.message.answer(
        "🔑 Нажми на ключ — он скопируется, затем вставь его в Happ:\n\n"
        f"<blockquote expandable><code>{html.escape(happ)}</code></blockquote>"
    )
    await call.answer("Ключ отправлен ниже 👇")


@router.callback_query(F.data.startswith("addbp:"))
async def cb_addbp(call: CallbackQuery) -> None:
    """Connect-page fallback: reveal the bypass crypt4 key as a tap-to-copy quote."""
    bp = await _bypass_key(call.from_user.id)
    if not bp:
        await call.answer("Ключ обхода недоступен", show_alert=True)
        return
    await call.message.answer(
        "🌐 Нажми на ключ — он скопируется, затем вставь его в Happ:\n\n"
        f"<blockquote expandable><code>{html.escape(bp)}</code></blockquote>"
    )
    await call.answer("Ключ обхода отправлен ниже 👇")


@router.callback_query(F.data.startswith("addvincy:"))
async def cb_addvincy(call: CallbackQuery) -> None:
    """Connect-page fallback: reveal the Incy crypt1 VPN key."""
    incy = await _incy_vpn_key(call.from_user.id)
    if not incy:
        await call.answer("Ключ Incy недоступен", show_alert=True)
        return
    await call.message.answer(
        "💚 Нажми на ключ — он скопируется, затем вставь его в Incy:\n\n"
        f"<blockquote expandable><code>{html.escape(incy)}</code></blockquote>"
    )
    await call.answer("Ключ отправлен ниже 👇")


@router.callback_query(F.data.startswith("addbpincy:"))
async def cb_addbpincy(call: CallbackQuery) -> None:
    """Connect-page fallback: reveal the Incy crypt1 bypass key."""
    incy = await _incy_bypass_key(call.from_user.id)
    if not incy:
        await call.answer("Ключ обхода Incy недоступен", show_alert=True)
        return
    await call.message.answer(
        "💚 Нажми на ключ — он скопируется, затем вставь его в Incy:\n\n"
        f"<blockquote expandable><code>{html.escape(incy)}</code></blockquote>"
    )
    await call.answer("Ключ обхода отправлен ниже 👇")


@router.callback_query(F.data == "onb:done")
async def cb_done(call: CallbackQuery) -> None:
    """Flash a premium ⚡️ for 2s, then open the main menu."""
    await call.answer()
    try:
        await call.message.delete()
    except Exception:  # noqa: BLE001 - message may be too old
        pass
    bolt = None
    try:
        bolt = await call.message.bot.send_message(
            call.message.chat.id, convert_tg_emoji(PREMIUM_BOLT), parse_mode="HTML"
        )
    except Exception:  # noqa: BLE001 - custom emoji may be unavailable to the bot
        logger.debug("premium bolt send failed", exc_info=True)
    await asyncio.sleep(2)
    if bolt is not None:
        try:
            await bolt.delete()
        except Exception:  # noqa: BLE001
            pass
    await show_main(call.message, call.from_user.id)


# --- Screen 9: share ------------------------------------------------------

@router.callback_query(F.data == "share:open")
async def cb_share(call: CallbackQuery) -> None:
    url = await _active_sub_url(call.from_user.id)
    if not url:
        await safe_edit(call.message, NO_ACCESS, reply_markup=claim_keyboard())
        await call.answer()
        return
    await safe_edit(
        call.message,
        SHARE.format(link=html.escape(url)),
        reply_markup=share_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data == "share:copy")
async def cb_share_copy(call: CallbackQuery) -> None:
    url = await _active_sub_url(call.from_user.id)
    if not url:
        await call.answer("Сначала забери доступ", show_alert=True)
        return
    await call.message.answer(
        "🔗 Ссылка ELMA — нажми, чтобы скопировать:\n\n"
        f"<code>{html.escape(url)}</code>"
    )
    await call.answer("Ссылка отправлена ниже 👇")


# --- Screen 10: QR code ---------------------------------------------------

@router.callback_query(F.data == "share:qr")
async def cb_share_qr(call: CallbackQuery) -> None:
    url = await _active_sub_url(call.from_user.id)
    if not url:
        await call.answer("Сначала забери доступ", show_alert=True)
        return
    png = _make_qr_png(url)
    if png is None:
        await call.answer("Не удалось сгенерировать QR-код", show_alert=True)
        return
    await call.message.answer_photo(
        BufferedInputFile(png, filename="elma-vpn.png"),
        caption=QR_CAPTION,
        reply_markup=qr_close_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data == "qr:close")
async def cb_qr_close(call: CallbackQuery) -> None:
    try:
        await call.message.delete()
    except Exception:  # noqa: BLE001 - message may be too old to delete
        await safe_edit(call.message, QR_CAPTION, reply_markup=None)
    await call.answer()


# --- Add device (QR import for a second device) ---------------------------
#
# A paid user already connected on one device and wants another. Same
# subscription URL is imported on the new device via QR (or a copy-paste key).
# Flow: choose type (обычные / обход) → choose app (Happ / Incy) → QR + key.
#   hw:add            → type screen
#   hw:kind:<std|bp>  → app screen
#   hw:app:<client>:<kind> → QR + key photo
# "✅ Готово" reuses ``onb:done`` (flash + main menu).

HW_TYPE = (
    "📲 <b>Добавить устройство</b>\n\n"
    "Одна подписка — до 5 устройств. Импортируй ключ на новом устройстве.\n\n"
    "Выбери тип подключения:"
)

HW_APP = (
    "📲 <b>Добавить устройство</b>\n\n"
    "Выбери приложение, в котором будешь подключаться:"
)

HW_NO_SUB = (
    "🔒 Чтобы подключиться, нужен доступ.\n\n"
    "Оформи подписку — или подключи обход блокировок по трафику (ГБ) 👇"
)

HW_BYPASS_UNAVAILABLE = (
    "❌ <b>Обход белых списков недоступен</b>\n\n"
    "Убедись, что у тебя активна подписка и есть трафик обхода."
)


async def _bypass_raw(user_id: int) -> str | None:
    """Raw bypass subscription URL, or None if bypass is off/absent."""
    if not BYPASS_ENABLED:
        return None
    row = await get_bypass(user_id)
    if not row or not row["subscription_url"]:
        return None
    return row["subscription_url"]


def _hw_type_kb(has_sub: bool, has_bypass: bool):
    kb = InlineKeyboardBuilder()
    if has_sub:  # premium (unlimited) servers need an active subscription
        kb.button(text="🌐 Обычные сервера (безлимит)", callback_data="hw:kind:std", style="primary")
    if has_bypass:  # bypass works on bought GB traffic alone, no subscription
        kb.button(text="🤍 Обход белых списков", callback_data="hw:kind:bp", style="primary")
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def _hw_app_kb(kind: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="💚 Incy", callback_data=f"hw:app:incy:{kind}", style="success")
    kb.button(text="Happ", callback_data=f"hw:app:happ:{kind}", style="primary")
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data="hw:add")
    kb.adjust(1)
    return kb.as_markup()


def _hw_back_kb(callback_data: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data=callback_data)
    kb.adjust(1)
    return kb.as_markup()


async def _render_text(call: CallbackQuery, text: str, markup) -> None:
    """Show ``text`` in place. Edits the current message, or — when it's a photo
    (no editable text, e.g. coming back from the QR screen) — deletes and resends."""
    res = await safe_edit(call.message, text, reply_markup=markup)
    if res is None:
        try:
            await call.message.delete()
        except Exception:  # noqa: BLE001
            pass
        await call.message.answer(text, reply_markup=markup)


def _hw_caption(client: str, kind: str, crypt: str) -> str:
    if client == "incy":
        app, manual = "Incy", "затем в Incy нажми «Вставить»"
        label = (
            "💚 <b>Обход ключ Incy</b> (белые списки РФ):"
            if kind == "bp"
            else "💚 <b>VPN ключ Incy</b> (обычные безлимитные сервера):"
        )
    else:
        app, manual = "Happ", "затем в Happ нажми иконку буфера"
        label = (
            "🔑 <b>Обход ключ Happ</b> (белые списки РФ):"
            if kind == "bp"
            else "🔑 <b>VPN ключ Happ</b> (обычные безлимитные сервера):"
        )
    return (
        "📲 <b>Добавить устройство</b>\n\n"
        f"📷 <b>По QR-коду:</b> отсканируй код выше в {app} (иконка камеры).\n"
        f"✍️ <b>Вручную:</b> нажми на ключ ниже — он скопируется, {manual}.\n\n"
        f"{label}\n"
        f"<blockquote expandable><code>{html.escape(crypt)}</code></blockquote>"
    )


async def _hw_type_screen(call: CallbackQuery) -> None:
    has_sub = bool(await _active_sub_raw(call.from_user.id))
    has_bypass = bool(await _bypass_raw(call.from_user.id))
    if not has_sub and not has_bypass:  # nothing to connect with yet
        await _render_text(call, HW_NO_SUB, _access_gate_kb())
        return
    await _render_text(call, HW_TYPE, _hw_type_kb(has_sub, has_bypass))


@router.message(Command("hwadd"))
async def cmd_hwadd(message: Message) -> None:
    has_sub = bool(await _active_sub_raw(message.from_user.id))
    has_bypass = bool(await _bypass_raw(message.from_user.id))
    if not has_sub and not has_bypass:
        await message.answer(HW_NO_SUB, reply_markup=_access_gate_kb())
        return
    await message.answer(HW_TYPE, reply_markup=_hw_type_kb(has_sub, has_bypass))


@router.callback_query(F.data == "hw:add")
async def cb_hw_add(call: CallbackQuery) -> None:
    await _hw_type_screen(call)
    await call.answer()


@router.callback_query(F.data.startswith("hw:kind:"))
async def cb_hw_kind(call: CallbackQuery) -> None:
    kind = call.data.split(":")[2]
    if kind not in ("std", "bp"):
        await call.answer()
        return
    await _render_text(call, HW_APP, _hw_app_kb(kind))
    await call.answer()


@router.callback_query(F.data.startswith("hw:app:"))
async def cb_hw_app(call: CallbackQuery) -> None:
    parts = call.data.split(":")  # hw:app:<client>:<kind>
    if len(parts) != 4 or parts[2] not in ("happ", "incy") or parts[3] not in ("std", "bp"):
        await call.answer()
        return
    client, kind = parts[2], parts[3]
    uid = call.from_user.id

    if kind == "bp":
        raw = await _bypass_raw(uid)
        if not raw:
            await _render_text(call, HW_BYPASS_UNAVAILABLE, _hw_back_kb(f"hw:kind:{kind}"))
            await call.answer()
            return
    else:
        raw = await _active_sub_raw(uid)
        if not raw:
            await _render_text(call, HW_NO_SUB, _access_gate_kb())
            await call.answer()
            return

    crypt = (
        await incy_crypto.to_incy_link(raw)
        if client == "incy"
        else happ_crypto.format_for_user(raw)
    )
    if not crypt:
        await _render_text(
            call, "⚠️ Не удалось подготовить ключ. Попробуй ещё раз.",
            _hw_back_kb(f"hw:kind:{kind}"),
        )
        await call.answer()
        return

    caption = _hw_caption(client, kind, crypt)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Готово", callback_data="onb:done")
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data=f"hw:kind:{kind}")
    kb.adjust(1)
    markup = kb.as_markup()

    png = _make_qr_png(crypt)
    try:
        await call.message.delete()
    except Exception:  # noqa: BLE001 - previous (text) screen may be too old
        pass
    if png is None:
        # QR lib unavailable — the key in the caption is still copy-pasteable.
        await call.message.answer(caption, reply_markup=markup)
    else:
        await call.message.answer_photo(
            BufferedInputFile(png, filename="elma-device.png"),
            caption=caption,
            reply_markup=markup,
        )
    await call.answer()
