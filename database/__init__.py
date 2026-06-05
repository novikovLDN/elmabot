"""Database package — re-export every public function (one import surface)."""
from .core import (
    close_db,
    get_pool,
    init_db,
    to_db_utc,
    utcnow,
)
from .subscriptions import (
    activate_trial,
    create_pending_payment,
    due_reminders,
    expired_active,
    get_subscription,
    grant_days,
    mark_expired,
    mark_payment_refunded,
    mark_reminder_sent,
    payment_history,
    recipients,
    revoke_subscription,
    stats,
)
from .users import (
    find_user_by_username,
    get_user,
    mark_reachable,
    mark_unreachable,
    trial_available,
    upsert_user,
)

__all__ = [
    # core
    "init_db",
    "close_db",
    "get_pool",
    "utcnow",
    "to_db_utc",
    # users
    "upsert_user",
    "get_user",
    "find_user_by_username",
    "mark_unreachable",
    "mark_reachable",
    "trial_available",
    # subscriptions
    "get_subscription",
    "activate_trial",
    "grant_days",
    "create_pending_payment",
    "mark_payment_refunded",
    "revoke_subscription",
    "due_reminders",
    "mark_reminder_sent",
    "expired_active",
    "mark_expired",
    "stats",
    "payment_history",
    "recipients",
]
