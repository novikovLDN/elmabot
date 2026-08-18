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
import logging
from urllib.parse import quote, unquote

import httpx

import config

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0)

# Response headers worth passing through from the panel (traffic/expiry the
# client shows, refresh hint, content type).
_PASSTHROUGH = ("subscription-userinfo", "profile-update-interval", "content-type")

# Shared keep-alive client — avoids a fresh TLS handshake on every fetch (the
# aggregator does two upstream requests per subscription load).
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True)
    return _client


async def close() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None


# --- per-user link ---------------------------------------------------------

def sub_link(token: str) -> str:
    """Full aggregated subscription URL for a user's token (unique + revocable;
    the token lives in the DB, so reissuing it kills the old link)."""
    base = (config.SUBSCRIPTION_BASE_URL or "").rstrip("/")
    return f"{base}/sub/{token}"


# --- rebranding ------------------------------------------------------------

_GB = 1024 ** 3


def _fmt_gb(num_bytes: int) -> str:
    return f"{num_bytes / _GB:.2f} ГБ"


def build_announce(*, has_premium: bool, has_bypass: bool, remaining_bytes: int | None) -> str:
    """Subscription description shown at the top of the client.

    Explains the two server types and, when we know it, the remaining bypass
    (LTE) traffic. When the remaining is unknown we still show the legend, just
    without the amount.
    """
    lines: list[str] = []
    if has_premium:
        lines.append("🚀 UNLIMITED — безлимитные сервера, не тратят трафик.")
    if has_bypass:
        lines.append("🌐 LTE — тарификация по ГБ трафика (обход блокировок).")
        if remaining_bytes is not None:
            lines.append(f"⚠️ Осталось {_fmt_gb(remaining_bytes)} трафика обхода.")
    return "\n".join(lines)


def _extract_uris(body: bytes) -> list[str] | None:
    """Pull the proxy-URI lines out of a subscription body (base64 or plaintext
    list). Returns ``None`` for structured formats (Clash / sing-box / JSON)."""
    compact = b"".join(body.split())
    pad = b"=" * (-len(compact) % 4)
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            decoded = decoder(compact + pad)
        except Exception:  # noqa: BLE001 - not this base64 variant
            continue
        if b"://" in decoded:
            return [l.strip() for l in decoded.decode("utf-8", "replace").splitlines() if "://" in l]
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if "://" in text and "proxies:" not in text and not text.lstrip().startswith(("{", "[")):
        return [l.strip() for l in text.splitlines() if "://" in l]
    return None


def _with_note(uri: str, note: str) -> str:
    """Append ``note`` as a second line under the server's original name.

    The name/note are joined with a real newline that ``quote`` encodes as
    ``%0A`` — the URI line itself stays intact (no literal newline to break the
    list), and the client renders the ``%0A`` as a subtitle under the name."""
    base, _, frag = uri.partition("#")
    name = unquote(frag) if frag else ""
    label = f"{name}\n{note}" if name else note
    return f"{base}#{quote(label)}"


def combine(groups: list[tuple[str, bytes]]) -> bytes | None:
    """Merge several subscription bodies (each ``(note, body)``) into one base64
    URI list, keeping each server's **original name** and appending ``note`` as a
    subtitle. Every server from every source is kept — nothing is de-duplicated
    across sources, so premium and bypass servers all show together. Returns
    ``None`` if none of the sources is a URI list (nothing mergeable)."""
    lines: list[str] = []
    for note, body in groups:
        uris = _extract_uris(body)
        if not uris:
            logger.warning("aggregator: source %r is not a URI list (%d bytes)", note, len(body))
            continue
        lines.extend(_with_note(uri, note) if note else uri for uri in uris)
    if not lines:
        return None
    return base64.b64encode("\n".join(lines).encode())


async def fetch(subscription_url: str) -> tuple[bytes, dict]:
    """GET the panel subscription content as a base64 vless URI list.

    We send a fixed plain-client User-Agent (``SUBSCRIPTION_UPSTREAM_UA``) rather
    than the caller's, so the panel returns a mergeable URI list instead of a
    JSON/Clash template keyed to the real client. Returns
    ``(body, passthrough_headers)``."""
    resp = await _get_client().get(
        subscription_url,
        headers={
            "User-Agent": config.SUBSCRIPTION_UPSTREAM_UA,
            # Always pull the current configs/usage — never a cached copy.
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    resp.raise_for_status()
    passthrough = {h: resp.headers[h] for h in _PASSTHROUGH if h in resp.headers}
    return resp.content, passthrough
