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

# --- Product / pricing ---
PRICE_STARS = _get_int("PRICE_STARS", 99)
SUBSCRIPTION_DAYS = _get_int("SUBSCRIPTION_DAYS", 30)
TRIAL_DAYS = _get_int("TRIAL_DAYS", 3)

# --- Scheduler tuning ---
REMINDER_INTERVAL_SECONDS = _get_int("REMINDER_INTERVAL_SECONDS", 600)
EXPIRY_INTERVAL_SECONDS = _get_int("EXPIRY_INTERVAL_SECONDS", 600)

# --- VPN provisioning ---
# Per-user traffic cap in gigabytes. 0 means unlimited.
VPN_TRAFFIC_LIMIT_GB = _get_int("VPN_TRAFFIC_LIMIT_GB", 0)

# --- Logging ---
LOG_LEVEL = _get_str("LOG_LEVEL", "INFO")

# --- Derived constants ---
# Username format inside the panel. Lets us *recover* the DB<->panel link
# by walking the panel by username.
PANEL_USERNAME_PREFIX = "tg_"


def panel_username(telegram_id: int) -> str:
    return f"{PANEL_USERNAME_PREFIX}{telegram_id}"
