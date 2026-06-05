# Архитектура — Telegram VPN bot (Атлас Lite)

Лёгкий клон: один продукт, один сервер, один платёжный поток. Никакого
магазина, мульти-тарифов, выбора стран, рефералов и игровых механик.

## 1. Что делает бот

1. `/start` → онбординг → опциональный **триал на 3 дня** (одноразово).
2. По окончании триала / по желанию — оплата подписки (фикс-цена за месяц).
3. Бот хранит подписку, продлевает её, выдаёт ссылку на VPN-клиент, шлёт
   напоминания за 24ч/3ч до конца.
4. Админ: статистика, выдать/отозвать доступ, рассылка.

## 2. Стек

| Слой | Технология |
|---|---|
| Бот | aiogram 3.x |
| Хранилище | PostgreSQL 14+ через `asyncpg` |
| Фоновые задачи | `asyncio.create_task` + scheduler-loop |
| VPN | Remnawave panel (REST), один сервер |
| Платежи | Telegram Stars (без вебхука) |
| Логи | `logging` → stdout |
| Деплой | Docker + Railway/VPS |

Python 3.11+ (для `asyncio.TaskGroup` и современного typing).

## 3. Структура

```
main.py                  запуск: pool + bot + scheduler
config.py                env-vars и константы (одно место)
database/
  core.py                pool, init_db, utcnow/to_db_utc
  users.py               CRUD пользователей
  subscriptions.py       подписки, платежи, триал, scheduler-запросы, stats
app/
  handlers/{common,trial,purchase,admin}/
  services/{vpn,payments,access,notifications}.py
  utils/telegram_safe.py safe_send / safe_edit / convert_tg_emoji
  keyboards.py, format.py
docs/ARCHITECTURE.md
```

Всё в одном репо, одиночный процесс с фоновыми тасками — покрывает
до ~50k пользователей.

## 4. Схема БД

Три таблицы: `users`, `subscriptions`, `payments` (см. `database/core.py`).

**Важно:** все даты — `TIMESTAMPTZ`, в коде всегда aware-`datetime`
(`database.utcnow()`). Наивные и aware datetime не смешиваем.

Индексы: `idx_subs_expiry` (partial по `status='active'`),
`idx_payments_status`.

## 5. Ключевые потоки

### 5.1 `/start`
INSERT/UPSERT пользователя, главное меню из 4 кнопок. Кнопка триала
скрыта, если `trial_used_at IS NOT NULL`.

### 5.2 Триал (`database.activate_trial`)
В одной транзакции: `SELECT ... FOR UPDATE` проверка `trial_used_at IS NULL`
→ `vpn.add_user` → `UPDATE users` → upsert `subscriptions(source='trial')`.
Провизия VPN вызывается **внутри** транзакции через callback. Если VPN упал
— ROLLBACK, `trial_used_at` не пишется, пользователь повторяет.

### 5.3 Покупка (Telegram Stars)
1. «Купить» → `create_pending_payment` (status `pending`) + `send_invoice`.
2. `pre_checkout_query` → `answer(ok=True)`.
3. `successful_payment` → `grant_days(..., invoice_id=payload)`:
   пометка `paid` и provision VPN — **в одной транзакции**.
4. Если provision упал — транзакция откатывается (payment остаётся
   `pending`), звёзды **возвращаются** (`refund_star_payment`), payment →
   `refunded`. Принцип: «оплатил → получил, либо возврат».

Идемпотентность: `payments.invoice_id` UNIQUE; повторный `successful_payment`
с тем же payload — no-op.

### 5.4 Продление
`grant_days` использует `GREATEST(expires_at, NOW()) + interval` — оплата при
активной подписке не сжигает остаток.

### 5.5 Напоминания / очистка (`app/services/notifications.py`)
- `reminder_loop` (каждые `REMINDER_INTERVAL_SECONDS`): выборка активных
  подписок в окне 24ч/3ч без флага → отправка → ставим флаг.
- `expiry_cleanup_loop`: `expires_at < NOW() AND status='active'` →
  `vpn.delete_user` → `status='expired'` → уведомление.

Каждый loop — `while True: sleep; try/except body`, один сбой не убивает цикл.

## 6. Внешние интеграции

### Remnawave (`app/services/vpn.py`)
Четыре метода: `add_user`, `update_user_expiry`, `delete_user`, `find_user`.
Идентификатор в панели — `tg_{telegram_id}` (позволяет восстановить связь
БД↔панель). Парсинг ответа защитный (поддержка `{...}` и `{"response": {...}}`).

### Платежи (`app/services/payments.py`)
Telegram Stars: `send_invoice(currency="XTR")`, без вебхука — всё в одном
потоке поллинга.

### Конфиг (`config.py`)
Всё в env: `BOT_TOKEN`, `ADMIN_TELEGRAM_ID`, `DATABASE_URL`, `REMNAWAVE_URL`,
`REMNAWAVE_TOKEN`, `PRICE_STARS`, `SUBSCRIPTION_DAYS`, `TRIAL_DAYS`.

## 7. Фоновые задачи
В `main.py` два `asyncio.create_task` — никакого APScheduler/Celery.

## 8. Админ-дашборд (`app/handlers/admin`)
Доступ по `from_user.id == ADMIN_TELEGRAM_ID` (router-level filter).
- 📊 Статистика: юзеры, активные подписки, платежи, выручка, MRR.
- 👤 Найти пользователя (по id/@username) → выдать 30 дней / отозвать / история.
- 📢 Рассылка по сегментам (все / активные / без подписки) через `copy_message`.

## 9. UX-паттерны
`safe_send`/`safe_edit` ловят `TelegramForbiddenError` (помечаем
`is_reachable=FALSE`) и `TelegramBadRequest`. Рассылка: `Semaphore(15)`,
батчи по 200 с паузой 2с, `return_exceptions=True`, обработка `RetryAfter`.
FSM — только для редких многошаговых сценариев (поиск юзера, рассылка).

## 10. Грабли (учтены в коде)

1. **TIMESTAMP vs TIMESTAMPTZ** — везде TIMESTAMPTZ + `utcnow()`.
2. **Атомарная выдача** — payment-row и provision-VPN в одной транзакции.
3. **`init_db` на больших таблицах** — `lock_timeout='5s'`,
   `statement_timeout='20s'` в начале схемы.
4. **Кастомные tg-emoji** — по умолчанию обычный Unicode; `convert_tg_emoji`
   превращает `![🎁](tg://emoji?id=…)` в `<tg-emoji>` для рассылок.
5. **Идемпотентность recovery** — GET-probe (`vpn.find_user`) перед UPDATE;
   `add_user` восстанавливает существующего пользователя панели.
6. **Тяжёлую логику не держим в обработчике события** — рассылка уходит в
   `asyncio.create_task`, пользователь получает мгновенный ответ.
7. **Не амендим продакшен-коммиты** — любой откат отдельным коммитом.

## 11. Вторая итерация (когда взлетит)
Промокоды, рефералка, A/B рассылок, аналитика, несколько тарифов/стран —
только после первой тысячи платящих.
