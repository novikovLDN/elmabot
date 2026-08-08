"""Sanitising user-provided text before it is stored, shown, or forwarded.

Telegram usernames and names are arbitrary user input. If the bot persists or
relays them verbatim (DB, admin dashboard, the payment provider), forbidden
content, invisible/bidi tricks or "impossible" unicode could ride along and put
the bot at risk. Everything user-supplied passes through here first.
"""
import re
import unicodedata

from .content_filter import is_forbidden

# Telegram usernames are 5–32 chars of [A-Za-z0-9_]; Telegram enforces that, but
# we clamp to the same safe set defensively so nothing else can ever be stored
# or forwarded as a "username".
_USERNAME_DISALLOWED = re.compile(r"[^A-Za-z0-9_]")


def clean_username(username: str | None) -> str | None:
    """Whitelist a Telegram username to ``[A-Za-z0-9_]`` (max 32 chars, no ``@``).

    Returns ``None`` if nothing valid remains **or** the handle references
    forbidden content — so junk / forbidden / unicode-spoofed handles never reach
    the DB, the dashboard or the payment provider.
    """
    if not username:
        return None
    cleaned = _USERNAME_DISALLOWED.sub("", username.lstrip("@"))[:32]
    if not cleaned or is_forbidden(username) or is_forbidden(cleaned):
        return None
    return cleaned


def clean_text(text: str | None, *, limit: int = 128, max_combining: int = 2) -> str:
    """Sanitise arbitrary user text for safe storage / display.

    NFKC-normalises, then drops every Unicode "Other" code point — control
    (``Cc``), format i.e. zero-width & bidi overrides (``Cf``), surrogate
    (``Cs``), private-use (``Co``) and unassigned / "nonexistent" (``Cn``) —
    caps runs of combining marks (kills Zalgo), collapses whitespace and hard-
    limits the length. Returns ``""`` when nothing usable is left.
    """
    if not text or is_forbidden(text):
        return ""
    out: list[str] = []
    combining_run = 0
    for ch in unicodedata.normalize("NFKC", text):
        cat = unicodedata.category(ch)
        if cat[0] == "C":  # control / format / surrogate / private / unassigned
            continue
        if cat in ("Mn", "Me", "Mc"):
            combining_run += 1
            if combining_run > max_combining:
                continue
        else:
            combining_run = 0
        out.append(ch)
    return re.sub(r"\s+", " ", "".join(out)).strip()[:limit]
