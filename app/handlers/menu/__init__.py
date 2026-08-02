"""Main menu (/menu), personal cabinet, About + Policy, Help + FAQ.

Static, navigation-heavy screens. Copy follows the approved ELMA spec verbatim;
tone is warm, on "ты", short.
"""
import html
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from app import emoji
from app.format import fmt_date
from app.keyboards import cabinet_keyboard, main_menu_keyboard
from app.services import bypass_service, happ_crypto
from app.utils import safe_edit, send_screen, show_screen
from config import (
    DEVICE_LIMIT,
    PRIVACY_POLICY_URL,
    REFERRAL_BONUS_DAYS,
    SUPPORT_URL,
    SUPPORT_USERNAME,
    TERMS_URL,
)
from database import get_subscription, referral_stats

_GB = 1024 ** 3


def _fmt_traffic(b: int) -> str:
    """Bytes as ГБ, or МБ when under 1 ГБ (so the 500 МБ trial bonus reads right)."""
    gb = b / _GB
    if gb < 1:
        return f"{b / (1024 ** 2):.0f} МБ"
    return f"{gb:.1f} ГБ"


def _traffic_bar(used: int, limit: int, width: int = 10) -> str:
    if limit <= 0:
        return ""
    filled = min(width, round(used / limit * width))
    return "▓" * filled + "░" * (width - filled)

logger = logging.getLogger(__name__)
router = Router(name="menu")


MAIN = (
    "💎 <b>ELMA — быстрый и безопасный интернет</b>\n\n"
    "🚀 Скорость до 75 Гбит/с\n"
    "⚡️ Подключение за минуту\n"
    "📱 До 5 устройств — вся семья\n"
    "🔒 Zero-logs — твои данные только твои\n\n"
    "30 000 человек уже внутри."
)

ABOUT = (
    "ℹ️ <b>О сервисе</b>\n\n"
    "☁️ ELMA — твой личный интернет\n"
    "без границ и без нервов.\n\n"
    "━━━━━━━━━━━━━━━\n\n"
    "🌍 Серверы по всему миру\n"
    "⚡️ Скорость до 75 Гбит/с\n"
    "📱 До 5 устройств на одну подписку\n"
    "♾️ Безлимитный трафик\n"
    "🔒 Zero-logs — мы ничего не храним\n"
    "🛡️ AES-256-GCM + WireGuard\n"
    "💬 Поддержка каждый день\n\n"
    "━━━━━━━━━━━━━━━\n\n"
    "iOS · Android · MacOS · Windows\n"
    "AndroidTV · Apple TV\n\n"
    "━━━━━━━━━━━━━━━\n\n"
    "С нами уже тысячи пользователей\n"
    "которые просто пользуются интернетом —\n"
    "без лагов, обрывов и нервов 🤍"
)

POLICY = (
    "📋 <b>Политика сервиса ELMA</b>\n\n"
    "Пользуясь сервисом, ты соглашаешься\n"
    "с этими условиями.\n\n"
    "━━━━━━━━━━━━━━━\n\n"
    "📱 <b>Устройства</b>\n"
    "Максимум 5 устройств одновременно.\n"
    "Превышение лимита — ограничение доступа без\n"
    "предупреждения и без возврата средств.\n\n"
    "⚖️ <b>Законность</b>\n"
    "ELMA предназначен для легального\n"
    "использования. Любая незаконная\n"
    "активность — немедленное ограничение доступа.\n\n"
    "🤖 <b>Накрутки и боты</b>\n"
    "Использование ботов и скриптов в\n"
    "реферальной программе запрещено.\n"
    "Бонусы будут аннулированы.\n\n"
    "💰 <b>Возврат средств</b>\n"
    "Возврат не предусмотрен после активации\n"
    "подписки или выдачи ключа.\n\n"
    "🚫 <b>Ограничение доступа</b>\n"
    "Администрация вправе ограничить или\n"
    "полностью закрыть доступ без объяснения\n"
    "причин и возврата средств при нарушении\n"
    "любого из пунктов выше.\n\n"
    "━━━━━━━━━━━━━━━\n\n"
    f"Вопросы: @{SUPPORT_USERNAME} 🤍"
)

HELP = (
    "🛎️ <b>Помощь</b>\n\n"
    "Выбери — найдём решение быстро 👇"
)

FAQ = (
    "📖 <b>Частые вопросы</b>\n\n"
    "Выбери свой вопрос 👇"
)

FAQ_ANSWERS = {
    "novpn": (
        "🚫 <b>Не работает подключение</b>\n\n"
        "Пройдись по шагам — обычно помогает один.\n\n"
        "1️⃣ <b>Проверь интернет без ELMA</b>\n"
        "Отключи ELMA, открой любой сайт.\n"
        "Не работает? Проблема у провайдера, не у нас.\n\n"
        "2️⃣ <b>Перезапусти приложение</b>\n"
        "Смахни Happ из меню → открой заново →\n"
        "включи подключение.\n\n"
        "3️⃣ <b>Импортируй ключ заново</b>\n"
        "В боте: «📲 Подключиться» → твоё устройство →\n"
        "«Импортировать ключ».\n\n"
        "Не помогло? Оператор ответит за 5–10 минут 💬"
    ),
    "howto": (
        "📲 <b>Как подключиться</b>\n\n"
        "Меньше минуты — серьёзно.\n\n"
        "1️⃣ Нажми «📲 Подключиться» в боте\n"
        "2️⃣ Выбери устройство\n"
        "3️⃣ Скачай приложение\n"
        "4️⃣ Нажми «🔗 Активировать ELMA»\n"
        "5️⃣ Включи ELMA 🚀\n\n"
        "Каждый шаг — с картинкой.\n"
        "Заблудиться сложно 🤍"
    ),
    "slow": (
        "🐌 <b>Низкая скорость</b>\n\n"
        "Пройдись по шагам.\n\n"
        "1️⃣ <b>Проверь скорость без ELMA</b>\n"
        "yandex.ru/internet с выключенным ELMA.\n"
        "Медленно без ELMA — проблема не в нас.\n\n"
        "2️⃣ <b>Смени сервер</b>\n"
        "Другая страна — иногда быстрее.\n"
        "Попробуй Германию или Финляндию.\n\n"
        "3️⃣ <b>На мобильном интернете?</b>\n"
        "Вечером вышки загружены — это нормально.\n"
        "Ночью быстрее.\n\n"
        "4️⃣ <b>Перезагрузи роутер</b>\n"
        "30 секунд без розетки — иногда решает всё.\n\n"
        "Стабильно медленно везде? Напиши нам 💬"
    ),
    "pay": (
        "💳 <b>Не проходит оплата</b>\n\n"
        "Пройдись по шагам.\n\n"
        "1️⃣ <b>Смени способ оплаты</b>\n"
        "СБП → карта, или наоборот.\n\n"
        "2️⃣ <b>Платёж завис?</b>\n"
        "Подожди 10–15 минут. Деньги либо\n"
        "спишутся и подписка активируется —\n"
        "либо вернутся автоматически.\n\n"
        "3️⃣ <b>Списали, а подписки нет?</b>\n"
        "Напиши оператору — разберёмся сразу.\n\n"
        "Ответим за 5–10 минут 💬"
    ),
}


async def _has_active_sub(user_id: int) -> bool:
    sub = await get_subscription(user_id)
    return sub is not None and sub["status"] == "active"


async def show_main(message_or_call, user_id: int) -> None:
    markup = main_menu_keyboard(has_active_sub=await _has_active_sub(user_id))
    if isinstance(message_or_call, CallbackQuery):
        await safe_edit(message_or_call.message, MAIN, reply_markup=markup)
        await message_or_call.answer()
    else:
        await message_or_call.answer(MAIN, reply_markup=markup)


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    await show_main(message, message.from_user.id)


@router.callback_query(F.data == "menu:main")
async def cb_main(call: CallbackQuery) -> None:
    await show_main(call, call.from_user.id)


# --- Personal cabinet ------------------------------------------------------

async def _cabinet_view(uid: int):
    sub = await get_subscription(uid)
    active = sub is not None and sub["status"] == "active"
    if active:
        stats = await referral_stats(uid)
        text = (
            "👤 <b>Личный кабинет</b>\n\n"
            f"🆔 ID: <code>{uid}</code>\n"
            f"📅 Подписка активна до: <b>{fmt_date(sub['expires_at'])}</b>\n"
            f"📱 Устройств: до {DEVICE_LIMIT}\n"
            f"🫂 Приглашено друзей: {stats['invited']}\n"
            f"🏆 Бонусных дней: {stats['purchased'] * REFERRAL_BONUS_DAYS}"
        )
    else:
        text = (
            "👤 <b>Личный кабинет</b>\n\n"
            f"🆔 ID: <code>{uid}</code>\n"
            "🔎 Статус подписки: не активна\n"
            "📅 Дата окончания: —"
        )

    # Bypass (traffic) block — independent of premium.
    usage = await bypass_service.get_usage(uid) if config.BYPASS_ENABLED else None
    has_bypass = bool(usage and usage["limit"])
    if has_bypass:
        used, limit, left = usage["used"], usage["limit"], usage["remaining"]
        pct = round(used / limit * 100) if limit else 0
        text += (
            "\n\n🌐 <b>Обход блокировок</b>\n"
            f"{_traffic_bar(used, limit)} {pct}%\n"
            f"Использовано: {_fmt_traffic(used)} из {_fmt_traffic(limit)} · "
            f"осталось <b>{_fmt_traffic(left)}</b>"
        )
        # Bypass key strictly as a Happ crypt4 deep link in a collapsed quote.
        crypt4 = happ_crypto.format_for_user(usage["subscription_url"])
        if crypt4:
            text += (
                "\n🔑 Ключ обхода (импортируй в Happ):\n"
                f"<blockquote expandable><code>{html.escape(crypt4)}</code></blockquote>"
            )

    return text, cabinet_keyboard(has_active_sub=active, has_bypass=has_bypass)


@router.message(Command("account"))
async def cmd_account(message: Message) -> None:
    text, markup = await _cabinet_view(message.from_user.id)
    await send_screen(message.bot, message.chat.id, "cabinet", text, reply_markup=markup)


@router.callback_query(F.data == "menu:cabinet")
async def cb_cabinet(call: CallbackQuery) -> None:
    text, markup = await _cabinet_view(call.from_user.id)
    await show_screen(call.message, "cabinet", text, reply_markup=markup)
    await call.answer()


# --- About / Policy --------------------------------------------------------

def _about_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="📋 Политика сервиса", callback_data="about:policy")
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


@router.message(Command("about"))
async def cmd_about(message: Message) -> None:
    await message.answer(ABOUT, reply_markup=_about_kb())


@router.callback_query(F.data == "about:open")
async def cb_about(call: CallbackQuery) -> None:
    await safe_edit(call.message, ABOUT, reply_markup=_about_kb())
    await call.answer()


@router.callback_query(F.data == "about:policy")
async def cb_policy(call: CallbackQuery) -> None:
    kb = InlineKeyboardBuilder()
    kb.button(text="📑 Документы", callback_data="about:docs")
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data="about:open")
    kb.adjust(1)
    await safe_edit(call.message, POLICY, reply_markup=kb.as_markup())
    await call.answer()


@router.callback_query(F.data == "about:docs")
async def cb_docs(call: CallbackQuery) -> None:
    text = (
        f'🔒 Политика конфиденциальности: <a href="{PRIVACY_POLICY_URL}">читать</a>\n'
        f'📜 Пользовательское соглашение: <a href="{TERMS_URL}">читать</a>\n\n'
        "ELMA.\n"
        "Конфиденциальность заложена\n"
        "в архитектуре сервиса."
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 Главное меню", callback_data="menu:main")
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data="about:policy")
    kb.adjust(1)
    await safe_edit(
        call.message, text, reply_markup=kb.as_markup(), disable_web_page_preview=True
    )
    await call.answer()


# --- Help / FAQ / Contacts -------------------------------------------------

def _help_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="📖 Частые вопросы", callback_data="help:faq")
    kb.button(text="📲 Инструкции", callback_data="dev:menu")
    kb.button(text="💬 Написать оператору", url=SUPPORT_URL)
    kb.button(text="ℹ️ О сервисе", callback_data="about:open")
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP, reply_markup=_help_kb())


@router.callback_query(F.data == "help:open")
async def cb_help(call: CallbackQuery) -> None:
    await safe_edit(call.message, HELP, reply_markup=_help_kb())
    await call.answer()


@router.callback_query(F.data == "help:faq")
async def cb_faq(call: CallbackQuery) -> None:
    kb = InlineKeyboardBuilder()
    kb.button(text="🚫 Не работает подключение", callback_data="faq:novpn")
    kb.button(text="📲 Как подключиться", callback_data="faq:howto")
    kb.button(text="🐌 Низкая скорость", callback_data="faq:slow")
    kb.button(text="💳 Не проходит оплата", callback_data="faq:pay")
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data="help:open")
    kb.adjust(1)
    await safe_edit(call.message, FAQ, reply_markup=kb.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("faq:"))
async def cb_faq_answer(call: CallbackQuery) -> None:
    key = call.data.split(":", 1)[1]
    text = FAQ_ANSWERS.get(key)
    if text is None:
        await call.answer()
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="💬 Написать оператору", url=SUPPORT_URL)
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data="help:faq")
    kb.adjust(1)
    await safe_edit(call.message, text, reply_markup=kb.as_markup())
    await call.answer()
