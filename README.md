# ELMA — Telegram VPN bot

Лёгкий бот, продающий **одну** VPN-подписку: бесплатные 2 дня → оплата
звёздами Telegram → автопродление, напоминания и админка. Один продукт,
один сервер, один платёжный поток.

## Возможности

- `/start` → онбординг ELMA: welcome → «Забрать доступ» → выбор устройства.
- `/menu` → главное меню: Личный кабинет, Купить/Продлить, Подключиться,
  Рефералка, Подарить, Помощь (4 FAQ + контакты), О сервисе + Политика.
- 🆓 Одноразовый бесплатный доступ на 2 дня (атомарная транзакция).
- 📱 Пошаговые экраны подключения: iOS, Android, MacOS, Windows, Android TV,
  Apple TV; «Поделиться» (ссылка) и QR-код для второго устройства.
- 🎁 Подарить подписку: выбор тарифа → оплата (заглушка) → одноразовая
  ссылка-подарок (`?start=gift_<code>`), активация получателем.
- 🚫 Экран блокировки: `/block <id>` (админ) — отзыв доступа + уведомление.
- 💳 Тарифы 1 / 3 / 6 / 12 мес (`/buy`). **Приём платежей ещё не подключён** —
  экран выбора тарифа работает, кнопка «Оплатить» — заглушка; точка
  подключения провайдера: `purchase.cb_pay` + `billing.complete_purchase`.
- 👥 Реферальная программа (`/invite`): +7 дней за друга, который **купил**
  подписку (не триал).
- 🎁 Персональные скидки: −10% после триала (1 день), −20% в день окончания,
  −20% реактивация через 3 дня.
- 🔗 Выдача подписки через панель **Remnawave** (`subscription_service`).
- ⏳ Напоминания 24ч/3ч, авто-очистка истёкших, рассылка офферов.
- 🛠 Админка: статистика, выдать/отозвать доступ, рассылка по сегментам.

## Стек

aiogram 3.x · PostgreSQL 14+ (`asyncpg`) · Remnawave REST · Telegram Stars ·
Python 3.11+. Один процесс, фоновые `asyncio`-таски — без Celery/APScheduler.

## Структура

```
main.py                  запуск: pool + bot + scheduler (3 loop'а)
config.py                все env-vars и константы
app/tariffs.py           каталог тарифов (1/3/6/12 мес)
database/                core (pool/init/helpers), users, subscriptions
app/
  handlers/              onboarding · menu · referral · gift · trial · purchase · admin
  services/              remnawave (REST) · subscription_service (provisioning)
                         billing (покупка+рефералка+подарки) · discounts · payments · notifications
  utils/telegram_safe.py safe_send / safe_edit / convert_tg_emoji
  keyboards.py, format.py
docs/ARCHITECTURE.md
```

## Запуск локально

```bash
cp .env.example .env        # заполните BOT_TOKEN, DATABASE_URL, REMNAWAVE_*, ADMIN_TELEGRAM_ID
pip install -r requirements.txt
python main.py
```

`init_db()` создаёт таблицы (`users`, `subscriptions`, `payments`,
`referrals`) и индексы при старте.

### Переменные окружения

| Переменная | Описание |
|---|---|
| `BOT_TOKEN` | токен бота |
| `ADMIN_TELEGRAM_ID` | telegram id администратора |
| `DATABASE_URL` | `postgresql://user:pass@host:5432/db` |
| `REMNAWAVE_URL` / `REMNAWAVE_TOKEN` | панель VPN и API-токен (общие с Atlas) |
| `REMNAWAVE_MAIN_SQUAD_UUID` | squad, в который кладём всех юзеров Elma (обязателен) |
| `REMNAWAVE_USERNAME_PREFIX` | префикс username в панели (default `elma_`) |
| `PRICE_STARS` | цена подписки в звёздах (default 99) |
| `SUBSCRIPTION_DAYS` | длительность подписки (default 30) |
| `TRIAL_DAYS` | длительность бесплатного доступа (default 2) |
| `DEVICE_LIMIT` | лимит устройств на пользователя (default 5) |
| `TRAFFIC_LIMIT_BYTES` | лимит трафика в байтах, `0` = безлимит (default 0) |
| `REFERRAL_BONUS_DAYS` | бонус инвайтеру за купившего друга (default 7) |
| `DISCOUNT_TRIAL_END_PCT` / `DISCOUNT_SUB_END_PCT` / `DISCOUNT_REACTIVATION_PCT` | скидки в % (default 10/20/20) |
| `REACTIVATION_AFTER_DAYS` | через сколько дней после истечения слать оффер реактивации (default 3) |
| `APP_IOS_URL` / `APP_ANDROID_URL` / `APP_MACOS_URL` / `APP_WINDOWS_URL` / `APP_ANDROIDTV_URL` | ссылки на скачивание клиента на экранах подключения (по умолчанию — публичный Happ) |

## Деплой

Docker + Railway/VPS. См. `Dockerfile`, `railway.toml`, `Procfile`.

## Архитектура и грабли

Подробности — в [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): атомарная
выдача доступа, TIMESTAMPTZ везде, идемпотентность платежей, лимиты рассылок.
