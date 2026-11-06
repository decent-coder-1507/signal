"""Arq worker: `uv run arq signal_worker.main.WorkerSettings`. All jobs dispatch through signal_core.jobs."""

from __future__ import annotations

from typing import Any, ClassVar

from arq.connections import RedisSettings

from signal_core.jobs import load_job_modules, run_with_retries
from signal_core.logging import configure_logging
from signal_core.settings import get_settings


async def dispatch(ctx: dict[str, Any], name: str, key: str, kwargs: dict[str, Any]) -> Any:
    return await run_with_retries(name, key, kwargs, backoff_s=5.0)


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    load_job_modules()


class WorkerSettings:
    functions: ClassVar[list[Any]] = [dispatch]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 8
    job_timeout = 1800
    keep_result = 3600
