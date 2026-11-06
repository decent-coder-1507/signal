import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from signal_core.db import models  # noqa: F401  (register tables)
from signal_core.db.base import Base
from signal_core.settings import get_settings

target_metadata = Base.metadata


def _url() -> str:
    return context.config.get_main_option("sqlalchemy.url") or get_settings().database_url


def do_run(conn):  # type: ignore[no-untyped-def]
    context.configure(connection=conn, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as conn:
        await conn.run_sync(do_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_online())
