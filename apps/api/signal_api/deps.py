from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.auth import read_session_token, user_by_api_token
from signal_core.db.models import User
from signal_core.db.session import sessionmaker
from signal_core.settings import get_settings

SESSION_COOKIE = "signal_session"
CSRF_COOKIE = "signal_csrf"
CSRF_HEADER = "x-csrf-token"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


async def get_db() -> AsyncIterator[AsyncSession]:
    async with sessionmaker()() as s:
        try:
            yield s
            await s.commit()
        except Exception:
            await s.rollback()
            raise


# scope="function": commit BEFORE the response is sent. The default ("request") commits after sending, so a
# client that immediately uses a returned id (e.g. angles -> drafts) could race the commit and get a 404.
DB = Annotated[AsyncSession, Depends(get_db, scope="function")]


async def current_user(request: Request, db: DB) -> User:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        user = await user_by_api_token(db, auth[7:].strip())
        if user is None:
            raise HTTPException(401, "invalid API token")
        request.state.via_token = True
        return user
    token = request.cookies.get(SESSION_COOKIE)
    uid = read_session_token(get_settings().secret_key, token) if token else None
    user = await db.get(User, uid) if uid else None
    if user is None:
        raise HTTPException(401, "not authenticated")
    if request.method in UNSAFE:
        sent, cookie = request.headers.get(CSRF_HEADER), request.cookies.get(CSRF_COOKIE)
        if not sent or not cookie or not secrets.compare_digest(sent, cookie):
            raise HTTPException(403, "CSRF token missing or invalid")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
