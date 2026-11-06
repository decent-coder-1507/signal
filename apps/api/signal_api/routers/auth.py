from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque

import pyotp
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from signal_api.deps import CSRF_COOKIE, DB, SESSION_COOKIE, CurrentUser
from signal_core.auth import (
    SESSION_MAX_AGE,
    LoginError,
    authenticate,
    hash_api_token,
    make_session_token,
    new_api_token,
    new_totp_secret,
    verify_password,
    verify_totp,
)
from signal_core.db.models import User
from signal_core.settings import get_settings

router = APIRouter(tags=["auth"])

_attempts: dict[str, deque[float]] = defaultdict(deque)
RATE_WINDOW_S, RATE_MAX = 60.0, 10


def _rate_limit(ip: str) -> None:
    q, now = _attempts[ip], time.monotonic()
    while q and now - q[0] > RATE_WINDOW_S:
        q.popleft()
    if len(q) >= RATE_MAX:
        raise HTTPException(429, "too many login attempts; wait a minute")
    q.append(now)


class LoginIn(BaseModel):
    email: str
    password: str
    totp: str | None = None


def _set_cookies(resp: Response, token: str) -> str:
    s = get_settings()
    csrf = secrets.token_urlsafe(24)
    resp.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=s.cookie_secure,
        path="/",
    )
    resp.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=SESSION_MAX_AGE,
        httponly=False,
        samesite="lax",
        secure=s.cookie_secure,
        path="/",
    )
    return csrf


@router.post("/auth/login")
async def login(body: LoginIn, request: Request, response: Response, db: DB) -> dict[str, object]:
    _rate_limit(request.client.host if request.client else "?")
    try:
        user = await authenticate(db, body.email, body.password, body.totp)
    except LoginError as e:
        await db.commit()  # persist failed-attempt counters
        raise HTTPException(401, str(e)) from e
    csrf = _set_cookies(response, make_session_token(get_settings().secret_key, user.id))
    return {"ok": True, "csrf": csrf, "onboarded": user.onboarded_at is not None}


@router.post("/auth/logout")
async def logout(response: Response, _: CurrentUser) -> dict[str, bool]:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
async def me(user: CurrentUser) -> dict[str, object]:
    return {
        "id": str(user.id),
        "email": user.email,
        "timezone": user.timezone,
        "totp_enabled": bool(user.totp_secret),
        "has_api_token": bool(user.api_token_hash),
        "onboarded": user.onboarded_at is not None,
    }


class ReauthIn(BaseModel):
    password: str
    current_totp: str | None = None


def require_reauth(request: Request, user: User, body: ReauthIn) -> None:
    """Security-sensitive changes need a browser session (not the API token) plus fresh proof of the
    password and, when 2FA is already on, the current authenticator code."""
    if getattr(request.state, "via_token", False):
        raise HTTPException(403, "session required (API token cannot change credentials)")
    if not verify_password(user.password_hash, body.password):
        raise HTTPException(403, "password incorrect")
    if user.totp_secret and not (body.current_totp and verify_totp(user.totp_secret, body.current_totp)):
        raise HTTPException(403, "current authenticator code required")


class TotpIn(ReauthIn):
    secret: str | None = None
    code: str | None = None


@router.post("/auth/totp/setup")
async def totp_setup(body: TotpIn, request: Request, user: CurrentUser, db: DB) -> dict[str, object]:
    """Step 1 (password only): returns a new secret + otpauth URI. Step 2: send secret + code to enable."""
    require_reauth(request, user, body)
    if not body.secret:
        secret = new_totp_secret()
        uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="SIGNAL")
        return {"secret": secret, "otpauth_uri": uri, "enabled": False}
    if not body.code or not verify_totp(body.secret, body.code):
        raise HTTPException(400, "code does not match")
    user.totp_secret = body.secret
    await db.flush()
    return {"enabled": True}


@router.post("/auth/api-token")
async def rotate_api_token(body: ReauthIn, request: Request, user: CurrentUser, db: DB) -> dict[str, str]:
    """Create or rotate the API token used by the bookmarklet / Telegram bridge. Shown once."""
    require_reauth(request, user, body)
    token = new_api_token()
    user.api_token_hash = hash_api_token(token)
    await db.flush()
    return {"token": token}
