from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from signal_core.settings import get_settings

_engine: AsyncEngine | None = None
_maker: async_sessionmaker[AsyncSession] | None = None


def get_engine(url: str | None = None) -> AsyncEngine:
    global _engine, _maker
    if _engine is None or (url and str(_engine.url) != url):
        _engine = create_async_engine(url or get_settings().database_url, pool_pre_ping=True, pool_size=10)
        _maker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _maker is not None
    return _maker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with sessionmaker()() as s:
        try:
            yield s
            await s.commit()
        except Exception:
            await s.rollback()
            raise


async def dispose() -> None:
    global _engine, _maker
    if _engine is not None:
        await _engine.dispose()
    _engine, _maker = None, None
