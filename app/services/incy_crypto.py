"""Incy crypto-link (``incy://crypt1/``) generation.

Incy (a Happ-style xray client) imports a subscription from an
``incy://crypt1/<payload>`` deep link. Unlike Happ's RSA crypt4, Incy's crypt1
is **AES-256-GCM** whose key is derived from constants/assets shipped inside the
Incy clients and the official ``@incy/link-encoder`` package. There is no public
algorithm/key we could reimplement in pure Python, so we shell out to that
package via a tiny Node sidecar (``scripts/incy_encode.mjs``).

Like Happ crypt4 this is obfuscation (hide the address from scanners/sharing),
not secrecy — the symmetric key is recoverable from the shipped clients.

Requires Node + ``npm install`` at the repo root. Degradation is graceful:

* sidecar works                 -> ``incy://crypt1/…`` (domain hidden)
* Node / package missing / slow -> ``to_incy_link`` falls back to the legacy
  ``incy://add/<plain-url>`` (always works, but exposes the domain)

Results are cached in-memory (sub_url -> link) so re-rendering a screen never
re-spawns Node, and a permanent failure flips a kill-switch so we stop spawning
processes that will only fail again.
"""
import asyncio
import logging
import os
from urllib.parse import quote

logger = logging.getLogger(__name__)

DEEP_LINK_PREFIX = "incy://crypt1/"
LEGACY_PREFIX = "incy://add/"

_SCRIPT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "incy_encode.mjs")
)
# Repo root (scripts/..) — used as the subprocess cwd so Node resolves
# ``node_modules/@incy/link-encoder`` regardless of where the bot is launched.
_REPO_ROOT = os.path.dirname(os.path.dirname(_SCRIPT))

# Kill a wedged sidecar rather than letting it stall a handler.
_TIMEOUT = 2.0

# Set once a hard, unrecoverable failure is seen (Node absent / package not
# installed) so we stop spawning processes that will only fail again.
_disabled = False
# sub_url -> ready ``incy://crypt1/…`` link. crypt1 is deterministic per URL, so
# caching is safe and amortises the ~150 ms Node spawn across screen renders.
_cache: dict[str, str] = {}


async def to_incy_link_crypt1(url: str | None) -> str | None:
    """Encode ``url`` into an ``incy://crypt1/`` link via the Node sidecar, or
    None if the sidecar is unavailable/slow/broken."""
    global _disabled
    if not url or _disabled:
        return None
    cached = _cache.get(url)
    if cached is not None:
        return cached

    try:
        proc = await asyncio.create_subprocess_exec(
            "node",
            _SCRIPT,
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=_REPO_ROOT,
        )
    except FileNotFoundError:
        _disabled = True
        logger.warning("INCY_SPAWN_FAIL: node not on PATH; Incy crypt1 disabled")
        return None
    except Exception:  # noqa: BLE001 - never break the calling handler
        logger.exception("INCY_SPAWN_FAIL: could not start Incy encoder")
        return None

    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("INCY_TIMEOUT: encoder exceeded %.1fs; killing", _TIMEOUT)
        try:
            proc.kill()
            await proc.wait()
        except Exception:  # noqa: BLE001
            pass
        return None

    if proc.returncode != 0:
        msg = (err or b"").decode(errors="replace").strip()[:300]
        if "ERR_MODULE_NOT_FOUND" in msg or "Cannot find package" in msg:
            _disabled = True
            logger.warning(
                "INCY_NODE_RC=%s: @incy/link-encoder not installed "
                "(run `npm install`); Incy crypt1 disabled: %s",
                proc.returncode,
                msg,
            )
        else:
            logger.error("INCY_NODE_RC=%s: encoder failed: %s", proc.returncode, msg)
        return None

    link = (out or b"").decode().strip()
    if not link.startswith(DEEP_LINK_PREFIX):
        logger.error("INCY_BAD_OUTPUT: %r", link[:80])
        return None
    _cache[url] = link
    return link


async def to_incy_link(url: str | None) -> str | None:
    """Universal entry point: prefer ``incy://crypt1/`` (domain hidden); when the
    sidecar is unavailable, fall back to the legacy ``incy://add/<plain>`` link,
    which always works. None only when there is no URL to encode."""
    if not url:
        return None
    crypt1 = await to_incy_link_crypt1(url)
    if crypt1:
        return crypt1
    # Legacy fallback — works everywhere, but exposes the subscription domain.
    return LEGACY_PREFIX + quote(url, safe="")


async def selftest() -> bool:
    """Probe the crypt1 sidecar at startup and log INCY_SELFTEST_OK / _FAIL.

    A failure is non-fatal: Incy just degrades to legacy links and Happ is
    unaffected. Returns True when a real ``incy://crypt1/…`` link was produced.
    """
    sample = await to_incy_link_crypt1("https://example.com/sub/selftest")
    ok = bool(sample and sample.startswith(DEEP_LINK_PREFIX))
    logger.info("INCY_SELFTEST_%s", "OK" if ok else "FAIL")
    return ok
