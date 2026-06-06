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
import html
import io
import logging

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.keyboards import (
    buy_keyboard,
    claim_keyboard,
    device_keyboard,
    devices_keyboard,
    qr_close_keyboard,
    share_keyboard,
    welcome_keyboard,
)
from app.handlers.menu import show_main
from app.services import billing, subscription_service
from app.utils import safe_edit
from config import (
    APP_ANDROID_URL,
    APP_ANDROIDTV_URL,
    APP_IOS_URL,
    APP_MACOS_URL,
    APP_WINDOWS_URL,
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
    "<b>ELMA — VPN, который не играет на нервах.</b>\n\n"
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
    "☁️ <b>Подключение к ELMA почти завершено</b>\n\n"
    "Ты входишь в пространство,\n"
    "где сервисы открываются без ожидания,\n"
    "а интернет больше не раздражает ⚡\n\n"
    f"🎁 Тебе доступно {TRIAL_DAYS} дня бесплатного доступа"
)

SCREEN_2 = (
    "🫧 <b>ELMA активирован</b>\n\n"
    "Теперь тебе открыт гостевой режим 🫂\n\n"
    f"В ближайшие {TRIAL_DAYS} дня почувствуй,\n"
    "как работает интернет без помех ⚡\n\n"
    "Подключи до 5 устройств 👇"
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

QR_CAPTION = "Ваш QR-код ELMA VPN 🤍"


# --- Device instruction screens (3-8) -------------------------------------
#
# The subscription key is injected into ``{key}`` by ``cb_device`` and shown as
# a tap-to-copy code block; the screens have no "activate" button — the user
# copies the key and pastes it into the app ("＋" → "Вставить из буфера").

_KEY_HINT = "👆 Нажми на ключ выше — он скопируется"

DEVICES: dict[str, dict] = {
    "ios": {
        "download_url": APP_IOS_URL,
        "download_label": "📥 Скачать приложение",
        "text": (
            "📄 <b>Подключение на iOS</b>\n\n"
            "{key}\n\n"
            "1. Нажми «📥 Скачать приложение» и установи Happ или Incy\n"
            "2. Открой приложение → справа вверху нажми «＋»\n"
            "3. Выбери «Вставить из буфера» — ключ добавится сам\n"
            "4. Выбери сервер и нажми «Подключиться» 🚀"
        ),
    },
    "android": {
        "download_url": APP_ANDROID_URL,
        "download_label": "📥 Скачать приложение",
        "text": (
            "📄 <b>Подключение на Android</b>\n\n"
            "{key}\n\n"
            "1. Нажми «📥 Скачать приложение» и установи Happ или Incy\n"
            "2. Открой приложение → справа вверху нажми «＋»\n"
            "3. Выбери «Вставить из буфера» — ключ добавится сам\n"
            "4. Выбери сервер и нажми «Подключиться» 🚀"
        ),
    },
    "macos": {
        "download_url": APP_MACOS_URL,
        "download_label": "📥 Скачать приложение",
        "text": (
            "📄 <b>Подключение на MacOS</b>\n\n"
            "{key}\n\n"
            "1. Нажми «📥 Скачать приложение» и установи Happ или Incy\n"
            "2. Открой приложение → справа вверху нажми «＋»\n"
            "3. Выбери «Вставить из буфера» — ключ добавится сам\n"
            "4. Выбери сервер и нажми «Подключиться» 🚀"
        ),
    },
    "windows": {
        "download_url": APP_WINDOWS_URL,
        "download_label": "📥 Скачать программу",
        "text": (
            "📄 <b>Подключение на Windows</b>\n\n"
            "{key}\n\n"
            "1. Нажми «📥 Скачать программу», установи\n"
            "   и запусти Happ от имени администратора\n"
            "2. В приложении справа вверху нажми «＋»\n"
            "3. Выбери «Вставить из буфера» — ключ добавится сам\n"
            "4. Выбери сервер и нажми «Подключиться» 🚀"
        ),
    },
    "androidtv": {
        "download_url": None,
        "download_label": "",
        "text": (
            "📄 <b>Подключение на Android TV</b>\n\n"
            "{key}\n\n"
            "1. Установи Happ через Google Play на TV\n"
            "2. Открой Happ → Управление → Импорт с телефона\n"
            "   (англ: Control → Import config from phone)\n"
            "3. На телефоне открой «📤 Поделиться» → «⤵️ QR-код»\n"
            "4. Наведи камеру телефона на экран TV\n"
            "5. Готово! Нажми «Подключиться» 🚀"
        ),
    },
    "appletv": {
        "download_url": None,
        "download_label": "",
        "text": (
            "📄 <b>Подключение на Apple TV</b>\n\n"
            "{key}\n\n"
            "1. Открой Happ или Incy на iOS / Android\n"
            "2. Сканируй QR-код с экрана TV\n"
            "3. Выбери конфигурацию и подтверди\n"
            "4. Готово! Нажми «Подключиться» 🚀"
        ),
    },
}


# --- Helpers --------------------------------------------------------------

async def _active_sub_url(telegram_id: int) -> str | None:
    """Return the connection URL of an active subscription, else None."""
    sub = await get_subscription(telegram_id)
    if sub is not None and sub["status"] == "active" and sub["subscription_url"]:
        return sub["subscription_url"]
    return None


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
        # Trial already used: fall through to device selection if a paid
        # subscription is still active, otherwise nudge to buy.
        current = await get_subscription(user_id)
        if current is None or current["status"] != "active":
            await safe_edit(call.message, TRIAL_USED, reply_markup=buy_keyboard())
            return
    else:
        logger.info("Trial activated for %s", user_id)
        # Tell the inviter their friend joined (bonus comes on first purchase).
        await billing.notify_referrer_on_trial(call.bot, user_id)

    await safe_edit(call.message, SCREEN_2, reply_markup=devices_keyboard())


@router.callback_query(F.data == "dev:menu")
async def cb_devices(call: CallbackQuery) -> None:
    await safe_edit(call.message, SCREEN_2, reply_markup=devices_keyboard())
    await call.answer()


# --- Screens 3-8: device instructions -------------------------------------

@router.callback_query(F.data.startswith("dev:"))
async def cb_device(call: CallbackQuery) -> None:
    key = call.data.split(":", 1)[1]
    device = DEVICES.get(key)
    if device is None:
        await call.answer()
        return
    sub_url = await _active_sub_url(call.from_user.id)
    if not sub_url:
        # Reachable from the main menu without an active subscription.
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
        return

    key_block = (
        "🔑 Твой ключ:\n"
        f"<code>{html.escape(sub_url)}</code>\n"
        f"{_KEY_HINT}"
    )
    await safe_edit(
        call.message,
        device["text"].format(key=key_block),
        reply_markup=device_keyboard(
            download_url=device["download_url"],
            download_label=device["download_label"],
        ),
    )
    await call.answer()


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
        "🔗 Ссылка ELMA VPN — нажми, чтобы скопировать:\n\n"
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
