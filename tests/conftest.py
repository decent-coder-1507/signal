"""Test harness: mock mode, dedicated Postgres database `signal_test` (created by scripts/db-init)."""

from __future__ import annotations

import os

os.environ["SIGNAL_MODE"] = "mock"
os.environ["SIGNAL_ENV"] = "test"
os.environ.setdefault("SIGNAL_DATABASE_URL", "postgresql+asyncpg://signal:signal@localhost:5442/signal_test")
os.environ["SIGNAL_USE_REDIS_QUEUE"] = "false"
os.environ["SIGNAL_ADMIN_EMAIL"] = "owner@test.local"
os.environ["SIGNAL_ADMIN_PASSWORD"] = "correct horse battery"
os.environ["SIGNAL_SECRET_KEY"] = "test-secret"

import asyncio
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.config import get_config
from signal_core.db.base import Base
from signal_core.db.session import dispose, get_engine, sessionmaker
from signal_core.settings import REPO_ROOT, get_settings

_migrated = False


async def _migrate() -> None:
    global _migrated
    if _migrated:
        return
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "packages/core/signal_core/db/migrations"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    await asyncio.to_thread(command.upgrade, cfg, "head")
    _migrated = True


async def truncate_all() -> None:
    names = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
    async with get_engine().begin() as conn:
        await conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


def reset_singletons() -> None:
    from signal_core.embeddings import set_embedder
    from signal_core.llm import router as llm

    llm.set_provider(None)
    set_embedder(None)


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    await _migrate()
    await truncate_all()
    reset_singletons()
    async with sessionmaker()() as s:
        yield s
        await s.rollback()


@pytest.fixture
async def seeded(db: AsyncSession) -> AsyncSession:
    from signal_core.services.seed import seed_all

    s = get_settings()
    await seed_all(db, get_config(), s.admin_email, s.admin_password, s.timezone)
    await db.commit()
    return db


@pytest.fixture(scope="session", autouse=True)
async def _dispose_engine() -> AsyncIterator[None]:
    yield
    await dispose()
