"""Premium (custom) emoji ids used as inline-button icons.

Set via ``InlineKeyboardButton.icon_custom_emoji_id`` (Bot API). Clients that
can't render a given emoji fall back to its standard glyph automatically.
"""
# Main menu
CONNECT = "5330115548900501467"   # 🔑 Подключиться
CABINET = "5190498849440931467"   # 👨‍💻 Личный кабинет
GB = "5447410659077661506"        # 🌐 Купить ГБ
SUB = "5199785165735367039"       # ⚡️ Купить / Продлить подписку
REFERRAL = "6048721430730773527"  # 👥 Реферальная программа
GIFT = "5193085063998224234"      # 🎁 Подарить
HELP = "5253742260054409879"      # ✉️ Помощь
ABOUT = "5334544901428229844"     # ℹ️ О сервисе

# Payment methods
SBP = "5217837965547427903"       # 🔸 СБП
CARD = "5377377923076476823"      # 🏛 Банковская карта

# Premium tariff list
TARIFF_KEY = "5330115548900501467"      # 🔑 default tariff
TARIFF_DIAMOND = "5372885812486626219"  # 💎 highlighted (3 месяца)
TARIFF_CROWN = "5449601904147440135"    # 👑 1 год

# "Пригласить друга" / "Поделиться" (same link emoji)
INVITE = "5271604874419647061"          # 🔗
SHARE = "5271604874419647061"           # 🔗

# Gift
CALENDAR = "5413879192267805083"        # 🗓 Выбрать срок

# Year-promo broadcast button (1 год со скидкой)
TROPHY = "5413566144986503832"          # 🏆 flashed on tap + year-plan icon

# Device picker
DEV_IOS = "5440584199402693616"         # 🤍
DEV_MAC = "5454100049166357274"         # 🍏
DEV_WINDOWS = "5454081378943518859"     # 💻
DEV_ANDROID = "6048857619848761040"     # 👽
DEV_ANDROIDTV = "5373330964372004748"   # 📺
DEV_APPLETV = "4949906098757829467"     # 🎥

# Used on every "Назад" button across the bot.
BACK = "6021510515103111203"      # 👈

# --- New-user onboarding (redesigned flow) ---
TRY_FREE = "6023826881160157558"      # 🎁 Попробовать бесплатно
BUY_VPN = "6030561664758191905"       # 🛒 Купить VPN
NEXT = "5807453545548487345"          # ➡️ Дальше
DONE = "6019175208240289774"          # ✅ Готово
HELP_CHAT = "5443038326535759644"     # 💬 Нужна помощь
BOLT = "5456140674028019486"          # ⚡️ (flashed after Готово)

# Device picker (redesigned)
DEV_IPHONE = "5821379843861778259"    # ⚪️ iPhone / iPad
DEV_ANDROID2 = "6048857619848761040"  # 👽 Android
DEV_MAC2 = "5334955749409834455"      # 📱 Mac
DEV_WINDOWS2 = "5296237443870105568"  # 🌌 Windows

# Cabinet / subscription (redesigned) — used in Phase 2
LOGO = "5427168083074628963"          # 💎 ELMA
STAR_SHIELD = "5226928895189598791"   # ⭐️ Трафик под защитой
RENEW = "6030517456659814017"         # 🔄 Продлить
GB_TOPUP = "6019336759140165949"      # 📡 Докупить ГБ / трафик
MY_SUB = "6021344879689341042"        # ⛓️ Моя подписка
INVITE_FRIENDS = "6021678620123077295"  # 👤 Пригласить друзей
MY_PROFILE = "6024039683904772353"    # 👤 Мой профиль
MANAGE_CARD = "5850492961850134154"   # 💳 Управление подпиской
RECEIPT = "5204242830687494041"       # 🧾 К оплате / Не проходит оплата
TARIFF_YEAR = "5217822164362739968"   # 👑 12 месяцев

# Help / FAQ (redesigned)
FAQ_BOOK = "5411369574157286161"      # 📖 Ответы на частые вопросы
INSTR = "6019245310696495518"         # 📱 Инструкция по сервису
FAQ_NOVPN = "5462882007451185227"     # 🚫 Не работает VPN
FAQ_SLOW = "5431689627075362922"      # 🐌 Низкая скорость
FAQ_DEVICE = "6019098624678435283"    # 💻 Добавить устройство
FAQ_KEY = "5278573677900752088"       # 🔑 Как обновить
FAQ_CHART = "5203993413346680064"     # 📊 Гигабайты обхода
FAQ_WARN = "5447644880824181073"      # ⚠️ Ошибка Xray-ядра
