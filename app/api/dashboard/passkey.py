"""WebAuthn / Passkey: register a key while signed in, sign in with it.

The ``webauthn`` library depends on ``cryptography``; if either is unavailable
the endpoints degrade to HTTP 501 and the rest of the dashboard keeps working
(password login stays the primary path). Challenges are kept in a small in-memory
store with a short TTL — single-instance, like the rest of the live bus.

Endpoints (all under /auth/, exempt from the JWT middleware — register handlers
enforce the admin guard manually):
  POST /auth/passkey/register/begin      (admin)  -> creation options
  POST /auth/passkey/register/complete   (admin)  -> store credential
  POST /auth/passkey/login/begin                  -> request options (+ flow id)
  POST /auth/passkey/login/complete               -> verify -> JWT
  GET  /auth/passkey/available                     -> {available, enabled}
"""
import json
import logging
import secrets
import time

from aiohttp import web

import config
import database

from .security import make_jwt, require_admin
from .util import json_ok, read_json

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()

# Lazy capability probe — never let a broken/missing crypto stack crash import.
try:
    import webauthn as _wa
    from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria,
        PublicKeyCredentialDescriptor,
        ResidentKeyRequirement,
        UserVerificationRequirement,
    )

    AVAILABLE = True
except Exception as exc:  # noqa: BLE001 - any import/native failure disables passkeys
    logger.warning("WebAuthn unavailable (%s); passkey login disabled", exc)
    AVAILABLE = False


def _origin() -> str:
    return config.DASHBOARD_BASE_URL.rstrip("/")


# challenge store: key -> (challenge_bytes, expiry_ts)
_challenges: dict[str, tuple[bytes, float]] = {}
_TTL = 300.0


def _put(key: str, challenge: bytes) -> None:
    now = time.time()
    for k, (_c, exp) in list(_challenges.items()):
        if exp < now:
            _challenges.pop(k, None)
    _challenges[key] = (challenge, now + _TTL)


def _take(key: str) -> bytes | None:
    item = _challenges.pop(key, None)
    if item is None or item[1] < time.time():
        return None
    return item[0]


def _require_available() -> None:
    if not AVAILABLE:
        raise web.HTTPNotImplemented(reason="passkeys unavailable on this server")


@routes.get("/auth/passkey/available")
async def available(request: web.Request) -> web.Response:
    enabled = False
    if AVAILABLE:
        pool = database.get_pool()
        enabled = bool(await pool.fetchval("SELECT COUNT(*) FROM webauthn_credentials"))
    return json_ok({"available": AVAILABLE, "enabled": enabled})


@routes.post("/auth/passkey/register/begin")
async def register_begin(request: web.Request) -> web.Response:
    _require_available()
    admin = require_admin(request)
    tg = int(admin["sub"])
    existing = await database.webauthn_list(tg)
    options = _wa.generate_registration_options(
        rp_id=config.WEBAUTHN_RP_ID,
        rp_name=config.WEBAUTHN_RP_NAME,
        user_id=str(tg).encode(),
        user_name=admin.get("username") or str(tg),
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(c["credential_id"]))
            for c in existing
        ],
    )
    _put(f"reg:{tg}", options.challenge)
    return web.Response(text=_wa.options_to_json(options), content_type="application/json")


@routes.post("/auth/passkey/register/complete")
async def register_complete(request: web.Request) -> web.Response:
    _require_available()
    admin = require_admin(request)
    tg = int(admin["sub"])
    body = await read_json(request)
    challenge = _take(f"reg:{tg}")
    if challenge is None:
        raise web.HTTPBadRequest(reason="challenge expired")
    try:
        ver = _wa.verify_registration_response(
            credential=json.dumps(body.get("credential", body)),
            expected_challenge=challenge,
            expected_rp_id=config.WEBAUTHN_RP_ID,
            expected_origin=_origin(),
        )
    except Exception as exc:  # noqa: BLE001
        raise web.HTTPBadRequest(reason=f"verification failed: {exc}")
    await database.webauthn_add(
        tg,
        bytes_to_base64url(ver.credential_id),
        bytes_to_base64url(ver.credential_public_key),
        ver.sign_count,
        label=str(body.get("label") or "Passkey"),
    )
    await database.log_audit(tg, "passkey_add")
    return json_ok({"ok": True})


@routes.post("/auth/passkey/login/begin")
async def login_begin(request: web.Request) -> web.Response:
    _require_available()
    options = _wa.generate_authentication_options(
        rp_id=config.WEBAUTHN_RP_ID,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    flow_id = secrets.token_urlsafe(16)
    _put(f"log:{flow_id}", options.challenge)
    payload = json.loads(_wa.options_to_json(options))
    return json_ok({"flow_id": flow_id, "options": payload})


@routes.post("/auth/passkey/login/complete")
async def login_complete(request: web.Request) -> web.Response:
    _require_available()
    body = await read_json(request)
    flow_id = str(body.get("flow_id", ""))
    challenge = _take(f"log:{flow_id}")
    if challenge is None:
        raise web.HTTPBadRequest(reason="challenge expired")

    credential = body.get("credential")
    if not isinstance(credential, dict) or "id" not in credential:
        raise web.HTTPBadRequest(reason="bad credential")
    stored = await database.webauthn_get(str(credential["id"]))
    if stored is None:
        raise web.HTTPUnauthorized(reason="unknown passkey")

    try:
        ver = _wa.verify_authentication_response(
            credential=json.dumps(credential),
            expected_challenge=challenge,
            expected_rp_id=config.WEBAUTHN_RP_ID,
            expected_origin=_origin(),
            credential_public_key=base64url_to_bytes(stored["public_key"]),
            credential_current_sign_count=stored["sign_count"],
            require_user_verification=False,
        )
    except Exception as exc:  # noqa: BLE001
        raise web.HTTPUnauthorized(reason=f"verification failed: {exc}")

    await database.webauthn_touch(stored["credential_id"], ver.new_sign_count)
    tg = stored["telegram_id"]
    user = await database.get_user(tg)
    username = user["username"] if user else None
    return json_ok({"token": make_jwt(tg, username), "telegram_id": tg})
