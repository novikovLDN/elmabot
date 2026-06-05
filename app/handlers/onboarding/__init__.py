"""ELMA onboarding flow.

The whole user-facing journey lives here as a chain of edited messages:

    /start  ──▶  Welcome (features + Start)
       └─ onb:start   ──▶  Screen 1 — "почти завершено" + Забрать доступ
            └─ onb:claim  ──▶  Screen 2 — ELMA активирован + выбор устройства
                 ├─ dev:<device>  ──▶  Screens 3-8 — инструкция по подключению
                 └─ share:open    ──▶  Screen 9 — Поделиться (ссылка)
                      └─ share:qr  ──▶  Screen 10 — QR-код (фото)

Everything is stateless callback-data; the only state is the user's
subscription row (whose ``subscription_url`` powers "Активировать" / share / QR).
"""
import html
import io
import logging

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.keyboards import (
    buy_keyboard,
    claim_keyboard,
    device_keyboard,
    devices_keyboard,
    qr_close_keyboard,
    share_keyboard,
    welcome_keyboard,
)
from app.services import subscription_service
from app.utils import safe_edit
from config import (
    APP_ANDROID_URL,
    APP_ANDROIDTV_URL,
    APP_IOS_URL,
    APP_MACOS_URL,
    APP_WINDOWS_URL,
    TRIAL_DAYS,
)
from database import get_subscription, set_referral, upsert_user

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
    "🛡️ Для всех устройств — iOS, Android, MacOS и Windows, AndroidTV, Apple TV\n"
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
    "Теперь тебе открыт гостевой режим 🫂\n"
    f"В ближайшие {TRIAL_DAYS} дня ты сможешь почувствовать,\n"
    "как должен работать интернет без постоянных помех ⚡\n\n"
    "ИЛИ ты можешь подключить до 5 устройств\n\n"
    "👇 Выбери устройство для подключения"
)

TRIAL_USED = (
    "🎁 Бесплатный доступ уже был использован.\n\n"
    "Чтобы вернуться в ELMA, оформи подписку 👇"
)

NO_ACCESS = (
    "Сначала забери бесплатный доступ к ELMA, "
    "чтобы получить ссылку для подключения 👇"
)

SHARE = (
    "📱 <b>Поделиться</b>\n\n"
    "Отправь ссылку на другое устройство:\n\n"
    "<code>{link}</code>"
)

QR_CAPTION = "Ваш QR Code на ELMA VPN 🤍"


# --- Device instruction screens (3-8) -------------------------------------

DEVICES: dict[str, dict] = {
    "ios": {
        "download_url": APP_IOS_URL,
        "download_label": "📥 Скачать приложение",
        "mode": "activate",
        "text": (
            "📄 <b>Подключение на iOS</b>\n\n"
            "1. Нажмите «📥 Скачать приложение» и установите его\n"
            "2. После установки нажмите «🔗 Активировать ELMA VPN»\n"
            "3. Готово! Нажмите «Подключиться» 🚀"
        ),
    },
    "android": {
        "download_url": APP_ANDROID_URL,
        "download_label": "📥 Скачать приложение",
        "mode": "activate",
        "text": (
            "📄 <b>Подключение на Android</b>\n\n"
            "1. Нажмите «📥 Скачать приложение» и установите его\n"
            "2. После установки нажмите «🔗 Активировать ELMA VPN»\n"
            "3. Готово! Выберите сервер и нажмите «Подключиться» 🚀"
        ),
    },
    "macos": {
        "download_url": APP_MACOS_URL,
        "download_label": "📥 Скачать приложение",
        "mode": "activate",
        "text": (
            "📄 <b>Подключение на MacOS Intel</b>\n\n"
            "1. Нажмите «📥 Скачать приложение» и установите его на устройство\n"
            "2. После установки нажмите «🔗 Активировать ELMA VPN», "
            "чтобы добавить подписку в приложение\n"
            "3. Готово! Теперь выберите сервер и нажмите «Подключиться» 🚀"
        ),
    },
    "windows": {
        "download_url": APP_WINDOWS_URL,
        "download_label": "📥 Скачать программу",
        "mode": "copy",
        "text": (
            "📄 <b>Подключение на Windows</b>\n\n"
            "1. Нажмите «📥 Скачать программу», установите "
            "и запустите Happ от имени администратора\n"
            "2. Откройте Telegram на ПК, нажмите «🔗 Скопировать профиль» "
            "и вставьте его в Happ\n"
            "3. Настройте программу по инструкции\n"
            "4. Готово! Нажмите «Подключиться» 🚀"
        ),
    },
    "androidtv": {
        "download_url": None,
        "download_label": "",
        "mode": "activate",
        "text": (
            "📄 <b>Подключение на Android TV</b>\n\n"
            "1. Установите приложение «Happ» на ваш Android TV через Google Play\n"
            "2. Откройте Happ на TV, выберите «Управление → Импорт с телефона» "
            "(Если язык английский: «Control» → «Import config from phone»)\n"
            "3. Возьмите телефон, откройте сканер QR-кода — нажмите на маленькую "
            "иконку QR-кода на любом из конфигов ELMA VPN в телефоне, "
            "так откроется сканер. Наведите его на экран телевизора\n"
            "4. Готово! Теперь выберите сервер и нажмите «Подключиться» 🚀"
        ),
    },
    "appletv": {
        "download_url": None,
        "download_label": "",
        "mode": "activate",
        "text": (
            "📄 <b>Подключение на Apple TV</b>\n\n"
            "1. Откройте Happ на iOS / Android\n"
            "2. Сканируйте QR-код с экрана TV\n"
            "3. Выберите, что отправлять (конфигурации / подписки) и подтвердите\n"
            "4. Готово! Теперь выберите сервер и нажмите «Подключиться» 🚀"
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
    if is_new:
        logger.info("New user onboarded: %s (@%s)", user.id, user.username)
        referrer_id = _parse_ref(command.args)
        if referrer_id and referrer_id != user.id:
            if await set_referral(user.id, referrer_id):
                logger.info("User %s referred by %s", user.id, referrer_id)
    await message.answer(WELCOME, reply_markup=welcome_keyboard())


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

    await safe_edit(call.message, SCREEN_2, reply_markup=devices_keyboard())


@router.callback_query(F.data == "dev:menu")
async def cb_devices(call: CallbackQuery) -> None:
    await safe_edit(call.message, SCREEN_2, reply_markup=devices_keyboard())
    await call.answer()


# --- Screens 3-8: device instructions -------------------------------------

@router.callback_query(F.data == "dev:copy")
async def cb_copy_profile(call: CallbackQuery) -> None:
    url = await _active_sub_url(call.from_user.id)
    if not url:
        await call.answer("Сначала забери доступ", show_alert=True)
        return
    await call.message.answer(
        "🔗 Ваш профиль ELMA VPN — скопируйте и вставьте в Happ:\n\n"
        f"<code>{html.escape(url)}</code>"
    )
    await call.answer("Профиль отправлен ниже 👇")


@router.callback_query(F.data.startswith("dev:"))
async def cb_device(call: CallbackQuery) -> None:
    key = call.data.split(":", 1)[1]
    device = DEVICES.get(key)
    if device is None:
        await call.answer()
        return
    sub_url = await _active_sub_url(call.from_user.id)
    await safe_edit(
        call.message,
        device["text"],
        reply_markup=device_keyboard(
            download_url=device["download_url"],
            download_label=device["download_label"],
            mode=device["mode"],
            sub_url=sub_url,
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
