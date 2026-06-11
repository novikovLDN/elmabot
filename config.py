"""Central configuration. Every env var and constant lives here (one place).

No dictionaries of tariffs / countries / multipliers — this is the *lite*
build: one product, one server, one payment flow.
"""
import os


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


# --- Telegram ---
BOT_TOKEN = _get_str("BOT_TOKEN", "")
ADMIN_TELEGRAM_ID = _get_int("ADMIN_TELEGRAM_ID", 0)

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
# Optional branded landing page (web/connect.html) that auto-opens Happ and
# imports the subscription. When set, the connection screens show an "Открыть в
# Happ" button linking to it; the crypt key travels in the URL #fragment, so it
# never reaches the page's web server. Empty -> button hidden, key shown as text.
# Example: "https://your-domain/connect.html"
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

# --- Scheduler tuning ---
REMINDER_INTERVAL_SECONDS = _get_int("REMINDER_INTERVAL_SECONDS", 600)
EXPIRY_INTERVAL_SECONDS = _get_int("EXPIRY_INTERVAL_SECONDS", 600)

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
