"""Subscription aggregator.

Instead of handing the client the raw Remnawave subscription link (which exposes
the panel's address), we serve the user's configs from our own domain, rebranded
"Elma". A request to ``<base>/sub/<token>`` resolves the token to a telegram id,
fetches that user's subscription content from the panel, rewrites the per-config
names to our brand, and returns it with the right subscription headers.

The token is a stateless HMAC of the telegram id, so no storage is needed. While
``SUBSCRIPTION_ADMIN_ONLY`` is on (the MVP default), only admin ids are served.
"""
import base64
import hashlib
import hmac
import logging
from urllib.parse import quote

import httpx

import config

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(15.0)

# Response headers worth passing through from the panel (traffic/expiry the
# client shows, refresh hint, content type).
_PASSTHROUGH = ("subscription-userinfo", "profile-update-interval", "content-type")


# --- opaque per-user token -------------------------------------------------

def _sig(payload: str) -> str:
    return hmac.new(
        config.SUBSCRIPTION_SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:20]


def make_token(telegram_id: int) -> str:
    payload = base64.urlsafe_b64encode(str(int(telegram_id)).encode()).decode().rstrip("=")
    return f"{payload}.{_sig(payload)}"


def verify_token(token: str) -> int | None:
    """Telegram id encoded in ``token``, or ``None`` if it fails the HMAC."""
    try:
        payload, sig = token.split(".", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(sig, _sig(payload)):
        return None
    try:
        pad = "=" * (-len(payload) % 4)
        return int(base64.urlsafe_b64decode(payload + pad).decode())
    except Exception:  # noqa: BLE001
        return None


def sub_link(telegram_id: int) -> str:
    """Full aggregated subscription URL handed to the user / imported by clients."""
    base = (config.SUBSCRIPTION_BASE_URL or "").rstrip("/")
    return f"{base}/sub/{make_token(telegram_id)}"


# --- rebranding ------------------------------------------------------------

def _rebrand_uri_list(text: str, brand: str) -> str:
    """Rewrite the ``#remark`` of each proxy URI to ``brand N`` (keeps the config
    itself untouched — only the display name changes)."""
    out: list[str] = []
    idx = 0
    for line in text.splitlines():
        stripped = line.strip()
        if "://" in stripped:
            idx += 1
            out.append(f"{stripped.split('#', 1)[0]}#{quote(f'{brand} {idx}')}")
        else:
            out.append(line)
    return "\n".join(out)


def rebrand(body: bytes, brand: str) -> bytes:
    """Best-effort rebrand of subscription content.

    Handles the two common formats — a base64-encoded or a plaintext list of
    proxy URIs. Structured formats (Clash / sing-box YAML/JSON) pass through
    unchanged; the ``profile-title`` header still carries the brand there.
    """
    # base64-encoded URI list (the default subscription format)
    try:
        decoded = base64.b64decode(b"".join(body.split()), validate=True)
        if b"://" in decoded:
            rebranded = _rebrand_uri_list(decoded.decode("utf-8", "replace"), brand)
            return base64.b64encode(rebranded.encode())
    except Exception:  # noqa: BLE001 - not base64, fall through
        pass
    # plaintext URI list (not YAML/JSON)
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return body
    lstripped = text.lstrip()
    if "://" in text and "proxies:" not in text and not lstripped.startswith(("{", "[")):
        return _rebrand_uri_list(text, brand).encode()
    return body


async def fetch(subscription_url: str, user_agent: str) -> tuple[bytes, dict]:
    """GET the panel subscription content, forwarding the client's User-Agent so
    the panel returns the format that client expects. Returns
    ``(body, passthrough_headers)``."""
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(
            subscription_url, headers={"User-Agent": user_agent or "Happ"}
        )
        resp.raise_for_status()
        passthrough = {
            h: resp.headers[h] for h in _PASSTHROUGH if h in resp.headers
        }
        return resp.content, passthrough
