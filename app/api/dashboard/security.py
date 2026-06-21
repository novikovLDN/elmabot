"""Auth primitives for the dashboard: password hashing, JWT, request guard.

Single-admin model — any valid JWT has full access (ТЗ §11). Passwords are
hashed with stdlib scrypt and tokens are HS256 JWTs implemented on the stdlib
(hmac/hashlib) — no third-party crypto dependency, which keeps the lite build's
footprint small and avoids native-lib breakage.
"""
import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from aiohttp import web

import config

_SCRYPT = dict(n=2**14, r=8, p=1, dklen=32)


# --- Passwords ------------------------------------------------------------


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, salt_hex, hash_hex = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex), **_SCRYPT
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), hash_hex)


# --- JWT (HS256, stdlib) --------------------------------------------------


class JWTError(Exception):
    """Raised for any malformed / invalid / expired token."""


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_dec(seg: str) -> bytes:
    return base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))


def _sign(signing_input: bytes) -> bytes:
    return hmac.new(config.JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest()


def make_jwt(telegram_id: int, username: str | None) -> str:
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": str(telegram_id),
        "username": username or "",
        "iat": now,
        "exp": now + config.JWT_TTL_DAYS * 86400,
    }
    seg = (
        _b64u(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64u(json.dumps(payload, separators=(",", ":")).encode())
    )
    return f"{seg}.{_b64u(_sign(seg.encode()))}"


def decode_jwt(token: str) -> dict[str, Any]:
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
    except (ValueError, AttributeError):
        raise JWTError("malformed token")
    expected = _sign(f"{header_b64}.{payload_b64}".encode())
    try:
        if not hmac.compare_digest(_b64u_dec(sig_b64), expected):
            raise JWTError("bad signature")
        payload = json.loads(_b64u_dec(payload_b64))
    except JWTError:
        raise
    except Exception:  # noqa: BLE001 - any decode error == invalid token
        raise JWTError("invalid token")
    if int(payload.get("exp", 0)) < int(time.time()):
        raise JWTError("expired")
    return payload


def require_admin(request: web.Request) -> dict[str, Any]:
    """Return the JWT payload for a valid Bearer token, else raise 401."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise web.HTTPUnauthorized(reason="missing token")
    try:
        return decode_jwt(auth[7:].strip())
    except JWTError:
        raise web.HTTPUnauthorized(reason="invalid token")
