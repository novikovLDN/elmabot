"""Subscription aggregator.

Instead of handing the client the raw Remnawave subscription link (which exposes
the panel's address), we serve the user's configs from our own domain, rebranded
"Elma". A request to ``<base>/sub/<token>`` resolves the token to a telegram id,
fetches that user's subscription content from the panel, rewrites the per-config
names to our brand, and returns it with the right subscription headers.

The token is a per-user secret in the DB (revocable by reissue). By default all
users are served; set ``SUBSCRIPTION_ADMIN_ONLY`` to restrict to admin ids.
"""
import asyncio
import base64
import logging
import re
import time
from collections import OrderedDict
from urllib.parse import quote, unquote

import httpx

import config

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0)

# NB: we deliberately do NOT pass the panel's own headers (content-type etc.)
# through to the client — we always serve text/plain (a panel that returns
# application/json for a client-specific UA otherwise breaks the client with
# "unknown content type"), and fetch() negotiates a UA that yields a mergeable
# base64 vless list, never that JSON template.

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


def add_link(token: str) -> str:
    """Clickable https one-tap "add to Happ" link — /add 302-redirects to the
    ``happ://add/...`` deep link (usable in Telegram buttons, unlike happ://)."""
    base = (config.SUBSCRIPTION_BASE_URL or "").rstrip("/")
    return f"{base}/add/{token}"


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


# Remembered UA that last yielded a mergeable uri-list — tried first so the
# steady state is a single upstream request (self-heals if the panel remaps UAs).
_good_ua: str | None = None


async def fetch(subscription_url: str) -> tuple[bytes, dict]:
    """GET the panel subscription content as a base64 vless URI list.

    Panels serve a *different* body per User-Agent (base64 vless list vs a
    client-specific JSON/Clash template) and can change that mapping at any time.
    So rather than trusting one fixed UA, we try an ordered list
    (``SUBSCRIPTION_UPSTREAM_UAS``) and return the first response that decodes to
    a mergeable uri-list — the last good UA is remembered and tried first next
    time, so steady state is a single request. Returns ``(body, {})``."""
    global _good_ua
    client = _get_client()
    uas = list(config.SUBSCRIPTION_UPSTREAM_UAS)
    if _good_ua and _good_ua in uas:  # try the known-good UA first
        uas = [_good_ua] + [u for u in uas if u != _good_ua]

    last_body = b""
    for ua in uas:
        resp = await client.get(
            subscription_url,
            headers={
                "User-Agent": ua,
                # Always pull the current configs/usage — never a cached copy.
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            },
        )
        resp.raise_for_status()
        body = resp.content
        if _extract_uris(body) is not None:  # mergeable — this UA works
            if _good_ua != ua:
                logger.info("aggregator: using upstream UA %r (yields uri-list)", ua)
            _good_ua = ua
            return body, {}
        last_body = body
    # No UA produced a uri-list — return the last body; combine() rejects it and
    # the caller fails over to the stale copy (or 503) instead of serving JSON.
    logger.warning(
        "aggregator: no UA yielded a uri-list for %s (tried %d)", subscription_url, len(uas)
    )
    return last_body, {}


async def probe(url: str, ua: str | None = None) -> dict:
    """Diagnostic fetch of a subscription URL: reports the shape of the response
    (HTTP status, content-type, first bytes, decoded server count, whether it's a
    mergeable URI list). Used by the /aggcheck admin command to prove the panel
    returns a base64 vless list (not a JSON template) under our fixed UA, and that
    our public link serves text/plain to every client UA."""
    resp = await _get_client().get(
        url,
        headers={
            "User-Agent": ua or config.SUBSCRIPTION_UPSTREAM_UA,
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    body = resp.content
    uris = _extract_uris(body)
    return {
        "status": resp.status_code,
        "content_type": resp.headers.get("content-type", ""),
        "head": body[:48].decode("utf-8", "replace"),
        "servers": len(uris) if uris else 0,
        "is_uri_list": uris is not None,
    }


# --- production serving: cache + singleflight + stale fallback --------------
#
# The panel is the slow, failure-prone dependency. Clients poll their /sub link
# on a schedule (Profile-Update-Interval), so a short in-process cache absorbs
# duplicate/near-simultaneous fetches, singleflight collapses a thundering herd
# on one token into a single upstream round-trip, and a last-good copy keeps the
# link working through a panel outage. All state is in-memory (one worker); TTLs
# are short so nothing goes meaningfully stale. Adapted from the aggregator TZ
# to our aiohttp + per-user users.sub_token model (no sub_pairs table).

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{4,128}$")

# Seconds a body is served without refetching the panel. Small by design so a
# client refresh reflects the current server list near-instantly; concurrent
# fetches are still collapsed by singleflight regardless of this value.
FRESH_TTL = float(config.SUBSCRIPTION_CACHE_TTL)
STALE_TTL = 24 * 3600.0    # seconds a body may still be served on panel failure
NEG_TTL = 60.0             # seconds an unknown token is remembered as missing
MAX_CACHE_ENTRIES = 20_000  # LRU cap (body + negative caches)


class SubscriptionNotFound(Exception):
    """Unknown/revoked token or the user has no subscription (-> 404)."""


class SubscriptionUnavailable(Exception):
    """Panel failed and there is no stale copy to fall back to (-> 503)."""


# token -> [fresh_until, stale_until, body, headers]
_cache: "OrderedDict[str, list]" = OrderedDict()
# token -> monotonic expiry (remembered-missing, guards against token flooding)
_neg: "OrderedDict[str, float]" = OrderedDict()
# token -> in-flight Future (concurrent callers for one token share one fetch)
_inflight: dict[str, asyncio.Future] = {}

_metrics = {
    "hits": 0,          # fresh-cache hits
    "misses": 0,        # upstream builds
    "stale": 0,         # last-good served through a panel failure
    "upstream_ok": 0,
    "upstream_fail": 0,
    "singleflight_wait": 0,
    "not_found": 0,
}


def valid_token(token: str) -> bool:
    return bool(token) and _TOKEN_RE.match(token) is not None


def _cache_get(token: str):
    """(is_fresh, body, headers) for a live entry, else None. Prunes a fully
    expired entry (past its stale window) lazily."""
    entry = _cache.get(token)
    if entry is None:
        return None
    now = time.monotonic()
    if now >= entry[1]:  # past stale_until
        _cache.pop(token, None)
        return None
    _cache.move_to_end(token)
    return now < entry[0], entry[2], entry[3]


def _cache_put(token: str, body: bytes, headers: dict) -> None:
    now = time.monotonic()
    _cache[token] = [now + FRESH_TTL, now + STALE_TTL, body, dict(headers)]
    _cache.move_to_end(token)
    while len(_cache) > MAX_CACHE_ENTRIES:
        _cache.popitem(last=False)


def clear_cache(token: str) -> None:
    """Forget everything cached for a token (both body and negative caches)."""
    _cache.pop(token, None)
    _neg.pop(token, None)


def _neg_get(token: str) -> bool:
    exp = _neg.get(token)
    if exp is None:
        return False
    if time.monotonic() >= exp:
        _neg.pop(token, None)
        return False
    return True


def _neg_put(token: str) -> None:
    _neg[token] = time.monotonic() + NEG_TTL
    _neg.move_to_end(token)
    while len(_neg) > MAX_CACHE_ENTRIES:
        _neg.popitem(last=False)


async def serve(token: str, builder):
    """Return ``(body, headers, x_cache)`` for a subscription token.

    ``builder`` is an async callable returning ``(body, headers)``; it does the
    resolve + upstream fetch + merge + header build. It must raise
    :class:`SubscriptionNotFound` for an unknown token / no subscription, and any
    other exception for an upstream failure (which triggers the stale fallback).

    Guarantees: a fresh cached body is returned instantly; concurrent callers for
    one token share a single build (singleflight); a panel failure serves the
    last-good copy when one exists, else raises :class:`SubscriptionUnavailable`.
    """
    if not valid_token(token):
        _metrics["not_found"] += 1
        raise SubscriptionNotFound

    cached = _cache_get(token)
    if cached is not None and cached[0]:
        _metrics["hits"] += 1
        return cached[1], cached[2], "hit"

    if _neg_get(token):
        _metrics["not_found"] += 1
        raise SubscriptionNotFound

    inflight = _inflight.get(token)
    if inflight is not None:
        _metrics["singleflight_wait"] += 1
        body, headers = await inflight
        return body, headers, "miss"

    fut: asyncio.Future = asyncio.get_event_loop().create_future()
    # When no follower is waiting on this future, retrieving its exception here
    # avoids a spurious "Future exception was never retrieved" warning.
    fut.add_done_callback(lambda f: f.cancelled() or f.exception())
    _inflight[token] = fut
    try:
        try:
            body, headers = await builder()
        except SubscriptionNotFound:
            _neg_put(token)
            _metrics["not_found"] += 1
            raise
        except Exception as exc:  # noqa: BLE001 - upstream failure -> stale/503
            _metrics["upstream_fail"] += 1
            stale = _cache_get(token)
            if stale is not None:
                _metrics["stale"] += 1
                result = (stale[1], stale[2])
                fut.set_result(result)
                logger.warning("aggregator: serving stale copy for token (upstream failed): %s", exc)
                return result[0], result[1], "stale"
            raise SubscriptionUnavailable from exc
        else:
            _metrics["misses"] += 1
            _metrics["upstream_ok"] += 1
            _cache_put(token, body, headers)
            fut.set_result((body, headers))
            return body, headers, "miss"
    except BaseException as exc:  # noqa: BLE001 - propagate to followers too
        if not fut.done():
            fut.set_exception(exc)
        raise
    finally:
        _inflight.pop(token, None)


def metrics_snapshot() -> dict:
    served = _metrics["hits"] + _metrics["misses"] + _metrics["stale"]
    return {
        **_metrics,
        "cache_entries": len(_cache),
        "neg_entries": len(_neg),
        "inflight": len(_inflight),
        "hit_ratio": round(_metrics["hits"] / served, 4) if served else 0.0,
    }


async def invalidate(telegram_id: int) -> None:
    """Drop a user's cached subscription body after a mutation (purchase, renew,
    GB top-up) so their next fetch rebuilds from fresh panel data. Read-only DB
    lookup; best-effort (never fail the purchase over a cache clear)."""
    try:
        from database import get_user

        row = await get_user(telegram_id)
        token = row["sub_token"] if row else None
    except Exception:  # noqa: BLE001
        logger.exception("aggregator.invalidate lookup failed for %s", telegram_id)
        return
    if token:
        clear_cache(token)
