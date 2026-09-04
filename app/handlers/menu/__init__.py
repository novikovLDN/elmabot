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
from app.services import bypass_service
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
    "💎 <b>ELMA</b>\n\n"
    "Интернет без блокировок, нервов и ограничений.\n\n"
    "⚡️ Молниеносное соединение\n"
    "⭐️ Трафик под защитой 24/7\n"
    "🏆 Премия «Надежный VPN 2026»\n"
    "🛰️ Обход глушилок"
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

_HELP_EMO = "![💬](tg://emoji?id=5443038326535759644)"   # 💬
_ROCKET = "![🚀](tg://emoji?id=5445284980978621387)"     # 🚀
_BULB = "![💡](tg://emoji?id=5422439311196834318)"       # 💡

HELP = (
    "❓ <b>Помощь</b>\n\n"
    "Выберите подходящий вариант ниже:\n\n"
    "<blockquote>![📖](tg://emoji?id=5411369574157286161) Ответы на частые вопросы\n"
    "Короткие решения типичных проблем</blockquote>\n\n"
    "<blockquote>![📱](tg://emoji?id=6019245310696495518) Инструкции по сервису\n"
    "Как настроить VPN на вашем устройстве</blockquote>\n\n"
    "<blockquote>📞 Контакты\n"
    "Почта поддержки и отдела продаж</blockquote>\n\n"
    f"<blockquote>{_HELP_EMO} Помощь\n"
    "Написать живому оператору в Telegram</blockquote>"
)

FAQ = (
    "![📖](tg://emoji?id=5411369574157286161) <b>Ответы на частые вопросы</b>\n\n"
    "Выберите свой вопрос — покажем короткое решение."
)

# (key, button label, button icon emoji-id) — order shown on the FAQ list.
_FAQ_LIST = [
    ("novpn", "Не работает VPN", emoji.FAQ_NOVPN),
    ("howto", "Как подключиться / настроить", emoji.INSTR),
    ("slow", "Низкая скорость", emoji.FAQ_SLOW),
    ("pay", "Не проходит оплата", emoji.RECEIPT),
    ("adddevice", "Как добавить ещё устройство", emoji.FAQ_DEVICE),
    ("update", "Как обновить", emoji.FAQ_KEY),
    ("bypass", "Как работают сервера обхода", emoji.GB),
    ("gb", "Как работают гигабайты обхода", emoji.FAQ_CHART),
    ("xray", "Happ — Ошибка Xray-ядра", emoji.FAQ_WARN),
]

FAQ_ANSWERS = {
    "novpn": (
        "🚫 <b>Не работает VPN</b>\n\n"
        "Пройдитесь по шагам — обычно помогает один из них.\n\n"
        "<blockquote>1️⃣ Проверьте интернет без VPN\n"
        "Отключите VPN, откройте любой сайт. Если не работает — проблема у "
        "провайдера, не у нас.</blockquote>\n\n"
        "<blockquote>2️⃣ В регионе глушат связь?\n"
        "В приложении выберите сервер с пометкой LTE — он специально для обхода "
        "блокировок мобильных операторов (МТС, МегаФон, Билайн).</blockquote>\n\n"
        "<blockquote>3️⃣ Перезапустите приложение\n"
        "Полностью закройте Happ (смахните из меню) → откройте заново → включите "
        "подключение.</blockquote>\n\n"
        "<blockquote>4️⃣ Импортируйте ключ заново\n"
        "В боте: «📲 Подключиться» → ваше устройство → «Импортировать ключ». "
        "Возможно, ссылка обновилась.</blockquote>\n\n"
        f"Не помогло? Напишите оператору — ответим за 5–10 минут. {_HELP_EMO}"
    ),
    "howto": (
        "📲 <b>Как подключиться</b>\n\n"
        "Это занимает меньше минуты.\n\n"
        "<blockquote>1️⃣ В боте нажмите «📲 Подключиться»\n\n"
        "2️⃣ Выберите устройство — iPhone · Android · Mac · Windows\n\n"
        "3️⃣ Установите приложение по нашей ссылке\n\n"
        "4️⃣ Нажмите «Импортировать ключ» — подписка добавится автоматически\n\n"
        f"5️⃣ Включите VPN в приложении {_ROCKET}</blockquote>\n\n"
        f"{_BULB} Все шаги показаны с картинками — заблудиться сложно. Если "
        f"что-то не получается — напишите оператору {_HELP_EMO}"
    ),
    "slow": (
        "![🐌](tg://emoji?id=5431689627075362922) <b>Низкая скорость</b>\n\n"
        "Пройдитесь по шагам.\n\n"
        "<blockquote>1️⃣ Проверьте скорость без VPN\n"
        "Измерьте на yandex.ru/internet с выключенным VPN. Если базовый интернет "
        "медленный — ускорить через VPN физически невозможно.</blockquote>\n\n"
        "<blockquote>2️⃣ Смените сервер\n"
        "В приложении переключитесь на другой — иногда соседние страны быстрее "
        "(например, Германия вместо Нидерландов).</blockquote>\n\n"
        "<blockquote>3️⃣ Используете LTE / 5G?\n"
        "Скорость мобильного интернета зависит от загрузки вышки и времени суток. "
        "Вечером — медленнее, ночью — быстрее.</blockquote>\n\n"
        "<blockquote>4️⃣ Перезагрузите Wi-Fi-роутер\n"
        "Иногда зависает именно он, а не VPN. Отключите от розетки на 30 секунд → "
        "включите.</blockquote>\n\n"
        f"Стабильно медленно на всех серверах? Напишите оператору. {_HELP_EMO}"
    ),
    "pay": (
        "![🧾](tg://emoji?id=5204242830687494041) <b>Не проходит оплата</b>\n\n"
        "Пройдитесь по шагам.\n\n"
        "<blockquote>1️⃣ Смените способ оплаты\n"
        "СБП → карта → Telegram Stars → баланс бота. Если один не работает — "
        "попробуйте другой.</blockquote>\n\n"
        "<blockquote>2️⃣ Платёж завис?\n"
        "Подождите 10–15 минут. Деньги либо спишутся и подписка активируется, "
        "либо вернутся на карту автоматически — мы ничего не «зажимаем».</blockquote>\n\n"
        "<blockquote>3️⃣ Списали, а подписки нет?\n"
        "Просто напишите оператору — обязательно поможем.</blockquote>\n\n"
        f"{_HELP_EMO} Поддержка ответит за 5–10 минут."
    ),
    "adddevice": (
        "📱 <b>Как добавить ещё устройство</b>\n\n"
        "Одна подписка — несколько устройств одновременно:\n\n"
        "<blockquote>• Premium — до 5 устройств</blockquote>\n\n"
        "Как добавить новое устройство\n\n"
        "<blockquote>1️⃣ В боте на основном устройстве нажмите кнопку «Меню» "
        "(синяя иконка слева от поля ввода) → «📲 Добавить устройство»</blockquote>\n\n"
        "2️⃣ Выберите тип устройства, которое хотите добавить\n\n"
        "3️⃣ Бот пришлёт QR-код и короткую инструкцию\n\n"
        "<blockquote>4️⃣ На новом устройстве установите приложение Happ и откройте его\n\n"
        "5️⃣ Нажмите «+» в правом верхнем углу → «Отсканировать QR-код»\n\n"
        "6️⃣ Наведите камеру на QR с основного устройства</blockquote>\n\n"
        f"Готово {_ROCKET}\n\n"
        f"{_BULB} Доплачивать не нужно — это та же подписка, просто на другом устройстве."
    ),
    "update": (
        "![🔑](tg://emoji?id=5278573677900752088) <b>Как обновить</b>\n\n"
        "Если в приложении Happ вы видите сообщение «Обновите ключ в боте» или "
        "«Данная версия не поддерживается» — нужно переустановить ключ.\n\n"
        "<blockquote>1️⃣ Нажмите кнопку «Меню» 🔵 (синяя иконка слева от поля ввода)\n\n"
        "2️⃣ Выберите «📲 Подключиться»\n\n"
        "3️⃣ Выберите своё устройство\n\n"
        "4️⃣ Установите приложение Happ\n"
        "Если приложение уже установлено — нажмите «Дальше» и пропустите этот шаг.\n\n"
        "5️⃣ Импортируйте ключ — пройдите стандартную процедуру установки</blockquote>\n\n"
        "Какой ключ выбрать?\n\n"
        "<blockquote>![🌐](tg://emoji?id=5447410659077661506) Добавить VPN — основные "
        "безлимитные сервера\n\n"
        "🛡 Добавить обход — сервера с обходом белых списков</blockquote>\n\n"
        f"Не получилось? Напишите оператору — поможем. {_HELP_EMO}"
    ),
    "bypass": (
        "![🌐](tg://emoji?id=5447410659077661506) <b>Как работают сервера обхода</b>\n\n"
        "Сервера обхода белых списков бывают двух типов:\n\n"
        "🇷🇺 С российским флагом\n"
        "🇪🇺 С европейским флагом\n\n"
        "Какой выбрать?\n\n"
        "Рекомендуем сервера с европейским флагом — они стабильнее и лучше "
        "работают с Telegram, Instagram и другими сервисами, заблокированными в РФ.\n\n"
        "Подключились, но сервер не работает?\n\n"
        "<blockquote>1️⃣ Выберите другой сервер и попробуйте снова\n\n"
        "2️⃣ Включите и выключите авиарежим ✈️\n\n"
        "3️⃣ Закройте приложение и откройте заново\n\n"
        "4️⃣ Проверьте подключение к мобильной сети и корректность соединения</blockquote>\n\n"
        f"Не помогло? Напишите оператору. {_HELP_EMO}"
    ),
    "gb": (
        "![📊](tg://emoji?id=5203993413346680064) <b>Как работают гигабайты обхода</b>\n\n"
        "Гигабайты для серверов обхода — это отдельный пакет трафика. Покупаете "
        "один раз и тратите в своём темпе.\n\n"
        "<blockquote>♾ Без срока годности\n"
        "Не сгорают. Не привязаны к месяцу, дню или подписке. Сколько "
        "использовали — столько и списалось, остаток остаётся вам.</blockquote>\n\n"
        "<blockquote>🔓 Независимо от подписки\n"
        "Это не часть основной подписки на VPN. Подписка закончилась — гигабайты "
        "обхода остаются на счёте и ждут вас.</blockquote>\n\n"
        "Пример\n\n"
        "<blockquote>💰 Купили 30 ГБ\n"
        "📉 За неделю израсходовали 5 ГБ\n"
        "✅ Остаток — 25 ГБ\n\n"
        "Эти 25 ГБ никуда не денутся: используйте завтра, через месяц или через "
        "полгода.</blockquote>\n\n"
        "Где посмотреть остаток\n\n"
        "<blockquote>📱 В приложении Happ — рядом с подключением к серверу обхода\n\n"
        "👤 В боте — раздел «👤 Профиль»</blockquote>\n\n"
        f"Закончились? Докупите в любой момент — новые ГБ просто прибавятся к остатку. {_HELP_EMO}"
    ),
    "xray": (
        "![⚠️](tg://emoji?id=5447644880824181073) <b>Happ — Ошибка Xray-ядра</b>\n\n"
        "Встречается часто, лечится за минуту.\n\n"
        "Почему возникает\n\n"
        "<blockquote>Многие VPN-сервисы автоматически подсовывают на устройство "
        "файлы маршрутизации — без вашего ведома. Мы так не делаем: все настройки "
        "живут на наших серверах, а не на телефоне.\n\n"
        "Но иногда файлы, оставшиеся от других VPN, конфликтуют с нашим ядром — и "
        "Happ показывает ошибку Xray.</blockquote>\n\n"
        "Как исправить\n\n"
        "<blockquote>1️⃣ Откройте Happ\n\n"
        "2️⃣ Нажмите на шестерёнку ⚙️ в левом верхнем углу\n\n"
        "3️⃣ Выберите «Маршрутизация»\n\n"
        "4️⃣ Удалите каждый файл маршрутизации из списка\n\n"
        "5️⃣ Перезапустите приложение</blockquote>\n\n"
        f"Подключение заработает штатно {_ROCKET}\n\n"
        f"Не помогло? Напишите оператору — разберёмся вместе за 5–10 минут. {_HELP_EMO}"
    ),
}


async def _has_active_sub(user_id: int) -> bool:
    sub = await get_subscription(user_id)
    return sub is not None and sub["status"] == "active"


async def show_main(message_or_call, user_id: int) -> None:
    markup = main_menu_keyboard(has_active_sub=await _has_active_sub(user_id))
    if isinstance(message_or_call, CallbackQuery):
        # "main" carries a photo, so show_screen deletes the old screen (text or
        # photo) and sends a fresh photo — text<->photo can't be edited in place.
        await show_screen(message_or_call.message, "main", MAIN, reply_markup=markup)
        await message_or_call.answer()
    else:
        # A plain Message: /menu, or call.message forwarded from onb:done (already
        # deleted there). Send a fresh screen (photo+caption when configured).
        await send_screen(
            message_or_call.bot, message_or_call.chat.id, "main", MAIN,
            reply_markup=markup,
        )


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
        # The key itself lives in the «Подключиться» flow — not shown here.

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


# --- Моя подписка ---------------------------------------------------------

async def _mysub_view(uid: int):
    sub = await get_subscription(uid)
    active = sub is not None and sub["status"] == "active"
    lines = ["📊 <b>Информация о подписке</b>\n"]
    if active:
        lines.append("⭐️ Тариф: <b>Premium</b>")
        lines.append(f"📅 Активна до: <b>{fmt_date(sub['expires_at'])}</b>")
    else:
        lines.append("⭐️ Тариф: —")
        lines.append("📅 Подписка не активна")

    usage = await bypass_service.get_usage(uid) if config.BYPASS_ENABLED else None
    if usage and usage["limit"]:
        lines.append(
            f"💎 Осталось обход трафика: <b>{_fmt_traffic(usage['remaining'])}</b> "
            f"из {_fmt_traffic(usage['limit'])}"
        )

    kb = InlineKeyboardBuilder()
    kb.button(text="Подключить VPN", callback_data="dev:menu",
              style="danger", icon_custom_emoji_id=emoji.GB)
    kb.button(text="Продлить подписку", callback_data="sub:manage",
              style="success", icon_custom_emoji_id=emoji.RENEW)
    if config.BYPASS_ENABLED:
        kb.button(text="Пополнить ГБ Обхода", callback_data="tr:open:m",
                  style="success", icon_custom_emoji_id=emoji.GB_TOPUP)
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data="menu:main")
    kb.adjust(1)
    return "\n".join(lines), kb.as_markup()


@router.callback_query(F.data == "menu:mysub")
async def cb_mysub(call: CallbackQuery) -> None:
    text, markup = await _mysub_view(call.from_user.id)
    await safe_edit(call.message, text, reply_markup=markup)
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
    """SOS Помощь: FAQ, service instructions, live operator, back to main."""
    kb = InlineKeyboardBuilder()
    kb.button(text="Ответы на частые вопросы", callback_data="help:faq",
              style="primary", icon_custom_emoji_id=emoji.FAQ_BOOK)
    kb.button(text="Инструкция по сервису", callback_data="dev:menu",
              style="primary", icon_custom_emoji_id=emoji.INSTR)
    kb.button(text="Помощь", url=SUPPORT_URL, style="danger", icon_custom_emoji_id=emoji.HELP_CHAT)
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data="menu:main", style="primary")
    kb.adjust(1)
    return kb.as_markup()


def _faq_answer_kb():
    """Under every FAQ answer: write to the operator, back to the question list."""
    kb = InlineKeyboardBuilder()
    kb.button(text="Помощь", url=SUPPORT_URL, icon_custom_emoji_id=emoji.HELP_CHAT)
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data="help:faq", style="primary")
    kb.adjust(1)
    return kb.as_markup()


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await send_screen(message.bot, message.chat.id, "help", HELP, reply_markup=_help_kb())


@router.callback_query(F.data == "help:open")
async def cb_help(call: CallbackQuery) -> None:
    await safe_edit(call.message, HELP, reply_markup=_help_kb())
    await call.answer()


@router.callback_query(F.data == "help:faq")
async def cb_faq(call: CallbackQuery) -> None:
    kb = InlineKeyboardBuilder()
    for key, label, ic in _FAQ_LIST:
        kb.button(text=label, callback_data=f"faq:{key}", style="primary", icon_custom_emoji_id=ic)
    kb.button(text="Назад", icon_custom_emoji_id=emoji.BACK, callback_data="help:open", style="primary")
    kb.adjust(1)
    await safe_edit(call.message, FAQ, reply_markup=kb.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("faq:"))
async def cb_faq_answer(call: CallbackQuery) -> None:
    key = call.data.split(":")[1]
    text = FAQ_ANSWERS.get(key)
    if text is None:
        await call.answer()
        return
    # Back always returns to the FAQ question list (previous screen).
    await safe_edit(call.message, text, reply_markup=_faq_answer_kb())
    await call.answer()
