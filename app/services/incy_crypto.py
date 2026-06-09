"""Incy crypto-link (``incy://crypt1/``) generation.

Incy (a Happ-style xray client) imports a subscription from an
``incy://crypt1/<payload>`` deep link. Unlike Happ's RSA crypt4, Incy's crypt1
is **AES-256-GCM** whose key is derived from constants/assets shipped inside the
Incy clients and the official ``@incy/link-encoder`` package. There is no public
algorithm/key we could reimplement in pure Python, so we shell out to that
package via a tiny Node sidecar (``scripts/incy_encode.mjs``).

Like Happ crypt4 this is obfuscation (hide the address from scanners/sharing),
not secrecy — the symmetric key is recoverable from the shipped clients.

Requires Node + ``npm install`` at the repo root. If Node or the package is
missing, generation degrades gracefully to None (the Incy button is hidden) and
the rest of the bot is unaffected.
"""
import asyncio
import logging
import os

logger = logging.getLogger(__name__)

DEEP_LINK_PREFIX = "incy://crypt1/"
_SCRIPT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "incy_encode.mjs")
)

# Set once a hard, unrecoverable failure is seen (Node absent / package not
# installed) so we stop spawning processes that will only fail again.
_disabled = False


async def to_incy_link(url: str | None) -> str | None:
    """Encode ``url`` into an ``incy://crypt1/`` link, or None if unavailable."""
    global _disabled
    if not url or _disabled:
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            "node",
            _SCRIPT,
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
    except FileNotFoundError:
        _disabled = True
        logger.warning("Node not found; Incy crypt links disabled")
        return None
    except Exception:  # noqa: BLE001 - never break the calling handler
        logger.exception("Failed to spawn Incy encoder")
        return None

    if proc.returncode != 0:
        msg = err.decode(errors="replace").strip()[:300]
        if "ERR_MODULE_NOT_FOUND" in msg or "Cannot find package" in msg:
            _disabled = True
            logger.warning(
                "@incy/link-encoder not installed (run `npm install`); "
                "Incy crypt links disabled: %s",
                msg,
            )
        else:
            logger.error("Incy encoder failed: %s", msg)
        return None

    link = out.decode().strip()
    return link if link.startswith(DEEP_LINK_PREFIX) else None
