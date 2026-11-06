"""SIGNAL API (FastAPI). Config is validated at startup: invalid config fails fast (M0)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from signal_api.routers import auth, ops, settings
from signal_core.config import get_config
from signal_core.db.session import dispose
from signal_core.logging import configure_logging


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    get_config()  # raises ConfigError with a readable message if anything is wrong
    yield
    await dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="SIGNAL API", version="0.1.0", lifespan=lifespan)
    for r in (ops.router, auth.router, settings.router):
        app.include_router(r)
    from signal_api.routers import register_all

    register_all(app)
    return app


app = create_app()
