"""Central configuration. Every env var and constant lives here (one place).

No dictionaries of tariffs / countries / multipliers — this is the *lite*
build: one product, one server, one payment flow.
"""
import os
import hashlib


def _get_str(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Required environment variable {name!r} is not set")
    return value


def _get_int(name: str, default: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        if default is None:
            raise RuntimeError(f"Required environment variable {name!r} is not set")
        return default
    try:
        return int(raw)
    except ValueError as exc:  # pragma: no cover - defensive
        raise RuntimeError(f"Environment variable {name!r} must be an integer") from exc


def _get_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# --- Telegram ---
BOT_TOKEN = _get_str("BOT_TOKEN", "")
# Product brand name. Screens hard-code the default ("ELMA"); set BRAND_NAME to
# rebrand a deployment — a request middleware rewrites the brand token in every
# outgoing message. Default keeps the original bot byte-for-byte unchanged.
BRAND_NAME = _get_str("BRAND_NAME", "ELMA").strip() or "ELMA"
ADMIN_TELEGRAM_ID = _get_int("ADMIN_TELEGRAM_ID", 0)
# Extra admins: a second id via ADMIN_TELEGRAM_ID_2, and/or a comma-separated
# list via ADMIN_TELEGRAM_IDS. ADMIN_IDS is the full set used to gate /admin.
_ADMIN_ID_2 = _get_int("ADMIN_TELEGRAM_ID_2", 0)
_ADMIN_IDS_RAW = _get_str("ADMIN_TELEGRAM_IDS", "")
ADMIN_IDS = frozenset(
    i
    for i in (
        ADMIN_TELEGRAM_ID,
        _ADMIN_ID_2,
        *(
            int(p.strip())
            for p in _ADMIN_IDS_RAW.replace(";", ",").split(",")
            if p.strip().lstrip("-").isdigit()
        ),
    )
    if i
)

# --- Database ---
DATABASE_URL = _get_str("DATABASE_URL", "")

# --- Remnawave VPN panel ---
REMNAWAVE_URL = _get_str("REMNAWAVE_URL", "").rstrip("/")
REMNAWAVE_TOKEN = _get_str("REMNAWAVE_TOKEN", "")
# Squad (inbound group) every Elma user is placed into. Without it a created
# panel user is attached to no inbound and the subscription does not work.
REMNAWAVE_MAIN_SQUAD_UUID = _get_str("REMNAWAVE_MAIN_SQUAD_UUID", "")
# Username prefix in the panel. Isolates Elma records from other bots sharing
# the same panel (e.g. Atlas Secure uses ``tg_<id>_premium``).
REMNAWAVE_USERNAME_PREFIX = _get_str("REMNAWAVE_USERNAME_PREFIX", "elma_")

# --- Product / pricing ---
PRICE_STARS = _get_int("PRICE_STARS", 99)
SUBSCRIPTION_DAYS = _get_int("SUBSCRIPTION_DAYS", 30)
TRIAL_DAYS = _get_int("TRIAL_DAYS", 2)
# Per-user device limit and traffic cap in the panel. 0 bytes = unlimited.
DEVICE_LIMIT = _get_int("DEVICE_LIMIT", 5)
TRAFFIC_LIMIT_BYTES = _get_int("TRAFFIC_LIMIT_BYTES", 0)

# --- Referral ---
# Days added to the referrer when an invited friend makes their first *paid*
# purchase (a trial does not count).
REFERRAL_BONUS_DAYS = _get_int("REFERRAL_BONUS_DAYS", 7)

# --- Discounts (percent off) ---
# −10% on the first purchase right after the trial ends (valid 1 day).
DISCOUNT_TRIAL_END_PCT = _get_int("DISCOUNT_TRIAL_END_PCT", 10)
# −20% to renew on the day a subscription ends.
DISCOUNT_SUB_END_PCT = _get_int("DISCOUNT_SUB_END_PCT", 20)
# −20% to reactivate 3 days after a subscription was disconnected.
DISCOUNT_REACTIVATION_PCT = _get_int("DISCOUNT_REACTIVATION_PCT", 20)
# How many days after expiry the reactivation offer fires.
REACTIVATION_AFTER_DAYS = _get_int("REACTIVATION_AFTER_DAYS", 3)

# --- Branding / onboarding ---
# Branded landing page (web/connect.html, served by this service at /connect)
# that auto-opens Happ and imports the subscription in one tap. The connection
# screens link to it; the crypt key travels in the URL #fragment, so it never
# reaches the web server. When left empty it auto-resolves to "<base>/connect"
# below (once WEBHOOK_BASE_URL / RAILWAY_PUBLIC_DOMAIN is known); set explicitly
# to host the page elsewhere. Empty + no base -> button hidden, key shown as text.
CONNECT_PAGE_URL = _get_str("CONNECT_PAGE_URL", "").rstrip("/")
# Per-platform app download links shown on the device connection screens.
# Default to the public Happ client pages; override per deployment if needed.
APP_IOS_URL = _get_str(
    "APP_IOS_URL", "https://apps.apple.com/app/happ-proxy-utility/id6504287215"
)
APP_ANDROID_URL = _get_str(
    "APP_ANDROID_URL",
    "https://play.google.com/store/apps/details?id=com.happproxy",
)
APP_MACOS_URL = _get_str(
    "APP_MACOS_URL", "https://apps.apple.com/app/happ-proxy-utility/id6504287215"
)
APP_WINDOWS_URL = _get_str(
    "APP_WINDOWS_URL", "https://github.com/Happ-proxy/happ-desktop/releases/latest"
)
APP_ANDROIDTV_URL = _get_str(
    "APP_ANDROIDTV_URL",
    "https://play.google.com/store/apps/details?id=com.happproxy",
)
# iOS shows two Happ store links (Russia / other region) plus an optional Incy
# link. Both Happ links default to APP_IOS_URL; the Incy download button is
# hidden until APP_INCY_IOS_URL is set.
APP_IOS_RU_URL = _get_str("APP_IOS_RU_URL", APP_IOS_URL)
APP_IOS_INTL_URL = _get_str("APP_IOS_INTL_URL", APP_IOS_URL)
APP_INCY_IOS_URL = _get_str("APP_INCY_IOS_URL", "")

# --- Platega payments (SBP / card via app.platega.io) ---
# Credentials from the Platega dashboard (Настройки). When MERCHANT_ID/SECRET are
# empty, payments stay a placeholder and no webhook server is started.
PLATEGA_MERCHANT_ID = _get_str("PLATEGA_MERCHANT_ID", "")
PLATEGA_SECRET = _get_str("PLATEGA_SECRET", "")
PLATEGA_API_URL = _get_str("PLATEGA_API_URL", "https://app.platega.io").rstrip("/")
# Browser redirects after the hosted payment page (optional). Default both to the
# bot so the user lands back in Telegram. Empty -> Platega's own result pages.
PLATEGA_RETURN_URL = _get_str("PLATEGA_RETURN_URL", "")
PLATEGA_FAILED_URL = _get_str("PLATEGA_FAILED_URL", "")
# Port the webhook HTTP server binds to (Railway/most PaaS inject $PORT).
WEBHOOK_PORT = _get_int("PORT", _get_int("WEBHOOK_PORT", 8080))

PAYMENTS_ENABLED = bool(PLATEGA_MERCHANT_ID and PLATEGA_SECRET)

# --- Transport: webhook vs polling ---
# Public base URL of this service (https). Railway exposes a generated domain via
# $RAILWAY_PUBLIC_DOMAIN; an explicit WEBHOOK_BASE_URL overrides it. When set, the
# bot runs fully on webhooks (Telegram + Platega on the same aiohttp server / port);
# when empty, it falls back to long polling (handy for local dev).
_railway_domain = _get_str("RAILWAY_PUBLIC_DOMAIN", "")
WEBHOOK_BASE_URL = _get_str(
    "WEBHOOK_BASE_URL", f"https://{_railway_domain}" if _railway_domain else ""
).rstrip("/")
# Path Telegram delivers updates to (kept separate from /platega/webhook).
WEBHOOK_PATH = "/" + _get_str("WEBHOOK_PATH", "webhook/telegram").lstrip("/")
# Secret token Telegram echoes back in X-Telegram-Bot-Api-Secret-Token so we can
# reject forged requests. Defaults to a stable value derived from the bot token.
TELEGRAM_WEBHOOK_SECRET = _get_str("TELEGRAM_WEBHOOK_SECRET", "") or hashlib.sha256(
    BOT_TOKEN.encode()
).hexdigest()

USE_WEBHOOK = bool(WEBHOOK_BASE_URL)

# If no explicit connect page was configured, serve our own /connect route off
# the public base URL (Railway domain). Keeps one-tap connect working out of the
# box on webhook deployments; stays empty on plain local polling.
if not CONNECT_PAGE_URL and WEBHOOK_BASE_URL:
    CONNECT_PAGE_URL = f"{WEBHOOK_BASE_URL}/connect"

# --- Admin dashboard (web) ---
# Single-admin web panel served by the same aiohttp process under /dashboard/.
# Disabled by default; set DASHBOARD_ENABLED=true to mount the API + SPA.
DASHBOARD_ENABLED = _get_bool("DASHBOARD_ENABLED", False)
# Secret used to sign dashboard JWTs. Defaults to a stable value derived from the
# bot token so tokens survive restarts without extra config (override in prod).
JWT_SECRET = _get_str("JWT_SECRET", "") or hashlib.sha256(
    ("dashboard:" + BOT_TOKEN).encode()
).hexdigest()
# How long a dashboard access token stays valid.
JWT_TTL_DAYS = _get_int("JWT_TTL_DAYS", 5)
# Public base URL used to build magic-links from the bot. Defaults to the
# webhook/Railway domain; the dashboard lives at "<base>/dashboard/".
DASHBOARD_BASE_URL = _get_str("DASHBOARD_BASE_URL", "") or WEBHOOK_BASE_URL
# Relying-Party id for WebAuthn/Passkey (the bare domain, no scheme/port).
# Derived from DASHBOARD_BASE_URL when not set explicitly.
_dash_host = (
    DASHBOARD_BASE_URL.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
)
WEBAUTHN_RP_ID = _get_str("WEBAUTHN_RP_ID", "") or _dash_host
WEBAUTHN_RP_NAME = _get_str("WEBAUTHN_RP_NAME", f"{BRAND_NAME} Admin")

# --- Scheduler tuning ---
REMINDER_INTERVAL_SECONDS = _get_int("REMINDER_INTERVAL_SECONDS", 600)
EXPIRY_INTERVAL_SECONDS = _get_int("EXPIRY_INTERVAL_SECONDS", 600)

# --- Channel ---
# Public channel link for the "Перейти в канал" broadcast button. Override via
# the CHANNEL_URL env var; empty disables it (button shows a "скоро" stub).
CHANNEL_URL = _get_str("CHANNEL_URL", "https://t.me/elma_vpn")

# --- Broadcast (admin fan-out) ---
# Telegram throttles bulk sends to ~30 msg/s to *different* users before it
# returns 429/RetryAfter. We pace strictly below that and cap in-flight sends so
# a 50k broadcast drips out steadily without flooding or starving other tasks.
BROADCAST_RATE = _get_int("BROADCAST_RATE", 25)          # messages per second
BROADCAST_CONCURRENCY = _get_int("BROADCAST_CONCURRENCY", 20)  # max in-flight

# --- Support / contacts ---
SUPPORT_USERNAME = _get_str("SUPPORT_USERNAME", "elma_supboperator").lstrip("@")
SUPPORT_URL = f"https://t.me/{SUPPORT_USERNAME}"

# --- Legal documents (shown on the Documents screen) ---
PRIVACY_POLICY_URL = _get_str(
    "PRIVACY_POLICY_URL",
    "https://telegra.ph/Politika-konfidencialnosti-06-08-18",
)
TERMS_URL = _get_str(
    "TERMS_URL",
    "https://telegra.ph/Polzovatelskoe-soglashenie-06-08-14",
)

# --- Logging ---
LOG_LEVEL = _get_str("LOG_LEVEL", "INFO")


# --- Derived constants ---
def build_username(telegram_id: int) -> str:
    """Panel username for a Telegram user.

    Remnawave caps usernames at 32 chars; ``elma_<id>`` fits with room to spare.
    The prefix lets us *recover* the DB<->panel link by walking the panel.
    """
    return f"{REMNAWAVE_USERNAME_PREFIX}{telegram_id}"[:32]
