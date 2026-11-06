"""Single-user auth primitives (§16.2): argon2 passwords, signed session tokens, API tokens, TOTP."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.db.models import User

_ph = PasswordHasher()
SESSION_MAX_AGE = 60 * 60 * 24 * 30
MAX_FAILED = 5
LOCK_MINUTES = 15


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(hashed: str, pw: str) -> bool:
    try:
        return _ph.verify(hashed, pw)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt="signal-session")


def make_session_token(secret: str, user_id: uuid.UUID) -> str:
    return _serializer(secret).dumps({"uid": str(user_id), "n": secrets.token_hex(8)})


def read_session_token(secret: str, token: str) -> uuid.UUID | None:
    try:
        data = _serializer(secret).loads(token, max_age=SESSION_MAX_AGE)
        return uuid.UUID(data["uid"])
    except (BadSignature, SignatureExpired, KeyError, ValueError):
        return None


def hash_api_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_api_token() -> str:
    return "sig_" + secrets.token_urlsafe(32)


def new_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)


class LoginError(Exception):
    pass


async def authenticate(session: AsyncSession, email: str, password: str, totp: str | None = None) -> User:
    user = (
        await session.execute(select(User).where(User.email == email.lower().strip()))
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if user is None:
        verify_password(hash_password("x"), password)  # equalise timing
        raise LoginError("invalid credentials")
    if user.locked_until and user.locked_until > now:
        raise LoginError("account temporarily locked after repeated failures")
    ok = verify_password(user.password_hash, password)
    if ok and user.totp_secret:
        ok = bool(totp) and verify_totp(user.totp_secret, totp or "")
    if not ok:
        user.failed_logins += 1
        if user.failed_logins >= MAX_FAILED:
            user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            user.failed_logins = 0
        await session.flush()
        raise LoginError("invalid credentials")
    user.failed_logins = 0
    user.locked_until = None
    await session.flush()
    return user


async def user_by_api_token(session: AsyncSession, token: str) -> User | None:
    h = hash_api_token(token)
    return (await session.execute(select(User).where(User.api_token_hash == h))).scalar_one_or_none()
