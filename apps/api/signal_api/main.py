"""SIGNAL API (FastAPI). Config is validated at startup: invalid config fails fast (M0)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from signal_api.routers import auth, ops, settings
from signal_core.config import get_config
from signal_core.db.session import dispose
from signal_core.logging import configure_logging, get_logger
from signal_core.settings import get_settings


async def _warm_embedder() -> None:
    """Load the local embedding model in the background so the first user request never pays for it."""
    from signal_core.embeddings import get_embedder

    try:
        await get_embedder().embed(["warm-up"])
    except Exception as e:  # a missing/slow model must never block or crash startup
        get_logger("api").warning("embedder_warmup_failed", error=str(e))


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    get_config()  # raises ConfigError with a readable message if anything is wrong
    warm = None
    if get_settings().embedding_provider == "fastembed":
        warm = asyncio.create_task(_warm_embedder())
    yield
    if warm is not None and not warm.done():
        warm.cancel()
    await dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="SIGNAL API", version="0.1.0", lifespan=lifespan)
    for r in (ops.router, auth.router, settings.router):
        app.include_router(r)
    from signal_api.routers import register_all

    register_all(app)
    return app


app = create_app()
