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

from app.keyboards import (
    buy_keyboard,
    claim_keyboard,
    devices_keyboard,
    qr_close_keyboard,
    share_keyboard,
    welcome_keyboard,
)
from app.handlers.menu import show_main
from app.services import billing, happ_crypto, subscription_service
from app.utils import convert_tg_emoji, safe_edit, send_screen, show_screen
from config import (
    APP_ANDROID_URL,
    APP_IOS_INTL_URL,
    APP_IOS_RU_URL,
    APP_MACOS_URL,
    APP_WINDOWS_URL,
    CONNECT_PAGE_URL,
    SUPPORT_URL,
    TRIAL_DAYS,
)
from database import (
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
    "💎 От 149 ₽\n"
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
    "Нажмите кнопку ниже — ключ добавится автоматически."
)

MANUAL_TEXT = (
    "<b>Ручная установка — 3 простых шага</b>\n\n"
    "1. Нажмите на ключ ниже — он скопируется\n"
    "2. Откройте Happ\n"
    "3. Вставьте из буфера (📋)\n\n"
    "{key}"
)

# Phone/desktop devices: Happ download buttons (label, url) and an optional
# download-screen photo (a key in app.screens). MacOS mirrors the Windows flow.
PHONE_DEVICES: dict[str, dict] = {
    "ios": {
        "downloads": [
            ("📲 Скачать Happ (Россия)", APP_IOS_RU_URL),
            ("📲 Скачать Happ (другой регион)", APP_IOS_INTL_URL),
        ],
        "dl_photo": None,
    },
    "android": {
        "downloads": [("📲 Скачать Happ", APP_ANDROID_URL)],
        "dl_photo": "dl_android",
    },
    "macos": {
        "downloads": [("📲 Скачать Happ", APP_MACOS_URL)],
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
    is_new = await upsert_user(user.id, user.username, user.language_code or "ru")
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


async def _no_access(call: CallbackQuery) -> None:
    """Shown when a connection screen is reached without an active subscription."""
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Купить подписку", callback_data="menu:buy")
    kb.button(text="🏠 Главное меню", callback_data="menu:main")
    kb.adjust(1)
    await safe_edit(
        call.message,
        "🔒 Доступ не активен.\n\nОформи подписку, чтобы получить ключ 👇",
        reply_markup=kb.as_markup(),
    )
    await call.answer()


async def _show_tv_guide(call: CallbackQuery, key: str) -> None:
    raw = await _active_sub_raw(call.from_user.id)
    if not raw:
        await _no_access(call)
        return
    happ = happ_crypto.format_for_user(raw)
    kb = InlineKeyboardBuilder()
    kb.button(text="📤 Поделиться", callback_data="share:open")
    kb.button(text="🔙 Назад", callback_data="dev:menu")
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
    kb.button(text="🔙 Назад", callback_data="dev:menu")
    kb.adjust(1)
    if device["dl_photo"]:
        await show_screen(call.message, device["dl_photo"], DOWNLOAD_TEXT, reply_markup=kb.as_markup())
    else:
        await safe_edit(call.message, DOWNLOAD_TEXT, reply_markup=kb.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("cn:"))
async def cb_connect(call: CallbackQuery) -> None:
    """Step 2: connect screen — one-tap key import (or copyable-key fallback)."""
    key = call.data.split(":", 1)[1]
    device = PHONE_DEVICES.get(key)
    if device is None:
        await call.answer()
        return
    happ = await _happ_key(call.from_user.id)
    if not happ:
        await _no_access(call)
        return

    kb = InlineKeyboardBuilder()
    page = _connect_link(happ)
    if page:
        kb.button(text="🔑 Добавить VPN ключ", url=page)
    else:
        kb.button(text="🔑 Добавить VPN ключ", callback_data=f"addkey:{key}")
    kb.button(text="✅ Готово", callback_data="onb:done")
    kb.button(text="📋 Установить вручную", callback_data=f"manual:{key}")
    kb.button(text="💬 Нужна помощь", url=SUPPORT_URL)
    kb.button(text="🔙 Назад", callback_data=f"dl:{key}")
    kb.adjust(1)
    await show_screen(call.message, "connect", CONNECT_TEXT, reply_markup=kb.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("manual:"))
async def cb_manual(call: CallbackQuery) -> None:
    key = call.data.split(":", 1)[1]
    happ = await _happ_key(call.from_user.id)
    if not happ:
        await _no_access(call)
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Готово", callback_data="onb:done")
    kb.button(text="🔙 Назад", callback_data=f"cn:{key}")
    kb.adjust(1)
    await safe_edit(
        call.message, MANUAL_TEXT.format(key=_key_block(happ)),
        reply_markup=kb.as_markup(),
    )
    await call.answer()


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
