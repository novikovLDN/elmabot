# ELMA — Telegram VPN bot

Лёгкий бот, продающий **одну** VPN-подписку: бесплатные 2 дня → оплата
звёздами Telegram → автопродление, напоминания и админка. Один продукт,
один сервер, один платёжный поток.

## Возможности

- `/start` → онбординг ELMA (новый пользователь) или главное меню (вернувшийся).
- Команда на каждый экран меню: `/menu` (главное), `/connect` (подключиться),
  `/buy` (купить/продлить), `/account` (личный кабинет), `/invite` (рефералка),
  `/gift` (подарить), `/help` (помощь), `/about` (о сервисе).
- 🆓 Одноразовый бесплатный доступ на 2 дня (атомарная транзакция).
- 📱 Пошаговые экраны подключения: iOS, Android, MacOS, Windows, Android TV,
  Apple TV; «Поделиться» (ссылка) и QR-код для второго устройства.
- 🔐 Подписка отдаётся как Happ crypto-link `happ://crypt4/…` (RSA-4096 + PKCS#1
  v1.5 публичным ключом Happ, чистый stdlib — `app/services/happ_crypto.py`).
  Реальный адрес подписки скрыт от пользователя; ссылку понимает только Happ
  (и Happ-совместимые форки), не другие клиенты — это свойство формата.
- 🚀 Брендированная страница подключения `web/connect.html` (статический файл,
  залить на свой домен/хостинг). Кнопки «Открыть в Happ» / «Открыть в Incy»
  авто-открывают приложение и импортируют подписку; ключ передаётся в URL
  `#fragment` и на веб-сервер не попадает. Включается переменной
  `CONNECT_PAGE_URL` (напр. `https://your-domain/connect.html`) — тогда на
  экранах устройств появляются кнопки подключения. Не задана — показываем ключ
  текстом.
- 🟣 Поддержка **Incy** (`incy://crypt1/…`, AES-256-GCM) через официальный
  `@incy/link-encoder` — генерируется Node-сайдкаром `scripts/incy_encode.mjs`
  (см. `app/services/incy_crypto.py`). Требует Node + `npm install` (в Docker
  ставится автоматически). Если Node/пакета нет — кнопка «Открыть в Incy»
  просто скрыта, остальное работает. ⚠️ Форматы Happ и Incy несовместимы между
  собой (разные приложения и схемы), общий у них только обычный subscription-URL.
- 🎁 Подарить подписку: выбор тарифа → оплата (заглушка) → одноразовая
  ссылка-подарок (`?start=gift_<code>`), активация получателем.
- 🚫 Экран блокировки: `/block <id>` (админ) — отзыв доступа + уведомление.
- 🛠 `/admin` (только `ADMIN_TELEGRAM_ID` из env): дашборд, платежи, рефералы,
  поиск по `telegram_id`/`@username`, карточка пользователя с гибкой выдачей
  доступа (`1 мес 10 дней`, `12 часов`, `90 мин`…) и отзывом доступа.
  - 📊 <b>Дашборд</b>: новые/триал за 24ч·7д·30д, активации, и <b>выручка в ₽
    по периодам</b> (3·7·14·30 дн., 3·6·12 мес., всего) по всем платёжным
    системам. Суммы — настоящие рубли (каждый провайдер пишет цену в ₽×100).
  - 💳 <b>Платежи</b>: карусель по 10 (◀▶) — username, `telegram_id`, сумма,
    способ, тариф/срок, статус (🟢 успех / 🔴 ошибка с причиной / 🟡 ожидает /
    ↩️ возврат). Неуспешные подсвечены и логируются с причиной.
  - 🫂 <b>Рефералы</b>: карусель по 10 — кто, сколько пригласил, сколько
    оплатили, сколько дней заработал (`+REFERRAL_BONUS_DAYS` за каждого). Плюс
    отдельный поиск по `telegram_id`/`@username` (не задевает основной поиск).
- 💳 Тарифы 1 / 3 / 6 / 12 мес (`/buy`) с оплатой через **Platega** (СБП / карта).
  `purchase.cb_method` создаёт транзакцию (`app/services/platega.py`), отдаёт
  кнопку-ссылку «Оплатить»; Platega подтверждает оплату webhook'ом на
  `/platega/webhook` (`app/web.py`, aiohttp в том же процессе) → провижининг
  через `billing.complete_purchase` (идемпотентно). Без `PLATEGA_MERCHANT_ID/
  SECRET` оплата выключена (кнопки → «скоро подключим», webhook-сервер не
  поднимается). Оплата Telegram Stars (`successful_payment`) тоже поддержана.
- 👥 Реферальная программа (`/invite`): +7 дней за друга, который **купил**
  подписку (не триал).
- 🎁 Персональные скидки: −10% после триала (1 день), −20% в день окончания,
  −20% реактивация через 3 дня.
- 🔗 Выдача подписки через панель **Remnawave** (`subscription_service`).
- ⏳ Напоминания 24ч/3ч, авто-очистка истёкших, рассылка офферов.
- 🛠 Админка: статистика, выдать/отозвать доступ, рассылка по сегментам.
- 📢 Рассылка (`app/services/broadcaster.py`): фото с подписью или текст с
  HTML-разметкой, превью перед отправкой (валидирует теги), строгий темп
  `BROADCAST_RATE` (25/с, под лимитом Telegram ~30/с) с ограничением in-flight
  и глобальным back-off на `RetryAfter` — рассчитано на 50k+ получателей без
  тайм-аутов и без блокировки других корутин. Заблокировавшие бота помечаются
  `unreachable`. Инструкция по форматированию показывается админу прямо в боте.
  - 🎯 Сегменты: все · активная подписка · холодные (без триала и подписки) ·
    триал без покупки · триал истёк 3+ дн. без покупки · без подписок вообще ·
    ⏳ истекает через 1–7 дней (посуточные бакеты по активным подпискам для
    таргетированных напоминаний/офферов; список дней — `EXPIRY_DAY_BUCKETS`).
  - 🔘 Кнопки к сообщению: «Купить со скидкой» (админ задаёт % и срок действия;
    при нажатии скидка применяется ко <b>всем</b> тарифам пользователя через
    персональный оффер) и «Перейти в канал» (`CHANNEL_URL`, иначе заглушка).

## Стек

aiogram 3.x · PostgreSQL 14+ (`asyncpg`) · Remnawave REST · Telegram Stars ·
Python 3.11+. Один процесс, фоновые `asyncio`-таски — без Celery/APScheduler.

## Структура

```
main.py                  запуск: pool + bot (webhook/polling) + scheduler (3 loop'а)
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
| `PLATEGA_MERCHANT_ID` / `PLATEGA_SECRET` | креды Platega; пусто = оплата выключена |
| `PLATEGA_API_URL` | база API Platega (default `https://app.platega.io`) |
| `PLATEGA_RETURN_URL` / `PLATEGA_FAILED_URL` | редиректы браузера после оплаты (опц.) |
| `WEBHOOK_PORT` / `PORT` | порт HTTP-сервера (PaaS обычно задаёт `PORT`) |
| `WEBHOOK_BASE_URL` | публичный https-URL сервиса → бот работает на webhook (иначе polling). На Railway берётся из `RAILWAY_PUBLIC_DOMAIN` автоматически |
| `WEBHOOK_PATH` | путь для апдейтов Telegram (default `webhook/telegram`) |
| `TELEGRAM_WEBHOOK_SECRET` | секрет проверки апдейтов Telegram (default — из `BOT_TOKEN`) |
| `BROADCAST_RATE` / `BROADCAST_CONCURRENCY` | темп рассылки (msg/s) и лимит одновременных отправок (default 25 / 20) |

> **Транспорт.** Если задан `WEBHOOK_BASE_URL` (или есть `RAILWAY_PUBLIC_DOMAIN`),
> бот поднимает один aiohttp-сервер на `$PORT` и принимает **и** апдейты Telegram
> (`/webhook/telegram`), **и** колбэки Platega (`/platega/webhook`). При старте
> вызывается `bot.set_webhook(...)`. Без переменной — обычный long polling
> (удобно локально).
>
> Платежи Platega: задайте в ЛК Platega (Настройки → Callback URLs) адрес
> `https://<публичный-хост>/platega/webhook` (только HTTPS, валидный
> сертификат). Бот должен быть доступен по публичному домену.

## Второй бот (другой бренд) из той же кодовой базы

Один репозиторий обслуживает несколько ботов — не нужно копировать код. Деплойте
**тот же** репозиторий ещё раз (отдельный сервис на Railway) со своей группой
переменных. Имя бренда меняется одной переменной `BRAND_NAME`: middleware
(`app/brand.py`) подменяет слово `ELMA` на заданное во всех исходящих сообщениях.
При `BRAND_NAME=ELMA` middleware не подключается — оригинальный бот не меняется.

Что обязательно должно отличаться у второго бота:

| Переменная | Почему |
|---|---|
| `BOT_TOKEN` | другой бот у @BotFather |
| `BRAND_NAME` | новое имя бренда в текстах |
| `DATABASE_URL` | **своя БД** — иначе пользователи/платежи смешаются |
| `WEBHOOK_BASE_URL` | свой публичный домен (свой `set_webhook`) |
| `REMNAWAVE_USERNAME_PREFIX` | если та же панель Remnawave — **обязательно** другой префикс, иначе коллизия записей (или своя панель: `REMNAWAVE_URL`/`TOKEN`) |
| `PLATEGA_*` | свой мерчант/Callback URL |
| `SUPPORT_USERNAME`, `CHANNEL_URL`, `ADMIN_TELEGRAM_ID`, цены | под новый бренд |

Фото экранов (`app/screens.py`) показываются **только у бренда Elma** (file_id
привязаны к загрузкам Elma); у любого другого `BRAND_NAME` экраны отправляются
без фото, чистым текстом. Если другому бренду нужны свои картинки — вынесем
`SCREEN_IMAGES` в env/файл (скажите — добавлю).

## Деплой

Docker + Railway/VPS. См. `Dockerfile`, `railway.toml`, `Procfile`.

## Архитектура и грабли

Подробности — в [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): атомарная
выдача доступа, TIMESTAMPTZ везде, идемпотентность платежей, лимиты рассылок.
