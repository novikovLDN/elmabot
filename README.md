# Атлас Lite — Telegram VPN bot

Лёгкий бот, продающий **одну** VPN-подписку: триал на 3 дня → оплата
звёздами Telegram → автопродление, напоминания и админка. Один продукт,
один сервер, один платёжный поток.

## Возможности

- `/start` → онбординг и главное меню.
- 🆓 Одноразовый триал на 3 дня (атомарная транзакция).
- 💳 Покупка/продление через **Telegram Stars** (без вебхуков).
- 🔗 Выдача VLESS-ссылки через панель **Remnawave**.
- ⏳ Напоминания за 24ч/3ч и авто-очистка истёкших подписок.
- 🛠 Админка: статистика, выдать/отозвать доступ, рассылка по сегментам.

## Стек

aiogram 3.x · PostgreSQL 14+ (`asyncpg`) · Remnawave REST · Telegram Stars ·
Python 3.11+. Один процесс, фоновые `asyncio`-таски — без Celery/APScheduler.

## Структура

```
main.py                  запуск: pool + bot + scheduler
config.py                все env-vars и константы
database/                core (pool/init/helpers), users, subscriptions
app/
  handlers/              common · trial · purchase · admin
  services/              vpn (Remnawave) · payments (Stars) · access · notifications
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

`init_db()` создаёт три таблицы и индексы при старте.

### Переменные окружения

| Переменная | Описание |
|---|---|
| `BOT_TOKEN` | токен бота |
| `ADMIN_TELEGRAM_ID` | telegram id администратора |
| `DATABASE_URL` | `postgresql://user:pass@host:5432/db` |
| `REMNAWAVE_URL` / `REMNAWAVE_TOKEN` | панель VPN и API-токен |
| `PRICE_STARS` | цена подписки в звёздах (default 99) |
| `SUBSCRIPTION_DAYS` | длительность подписки (default 30) |
| `TRIAL_DAYS` | длительность триала (default 3) |

## Деплой

Docker + Railway/VPS. См. `Dockerfile`, `railway.toml`, `Procfile`.

## Архитектура и грабли

Подробности — в [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): атомарная
выдача доступа, TIMESTAMPTZ везде, идемпотентность платежей, лимиты рассылок.
