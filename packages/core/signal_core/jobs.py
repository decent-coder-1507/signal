"""Job registry + queue (§5.1/§16.4).

Jobs are idempotent (callers pass a natural key). With SIGNAL_USE_REDIS_QUEUE=true jobs go to Arq/Redis
and run in the worker; otherwise they run inline in-process (tests, single-process dev). Every attempt is
recorded in the `jobs` table; after MAX_ATTEMPTS failures the job is marked `dead` (dead-letter list in Ops).
"""

from __future__ import annotations

import asyncio
import traceback
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select

from signal_core.db.models import Job
from signal_core.db.session import session_scope
from signal_core.logging import get_logger
from signal_core.settings import get_settings

JobFn = Callable[..., Awaitable[Any]]
JOBS: dict[str, JobFn] = {}
MAX_ATTEMPTS = 3
log = get_logger("jobs")


def job(name: str) -> Callable[[JobFn], JobFn]:
    def deco(fn: JobFn) -> JobFn:
        JOBS[name] = fn
        return fn

    return deco


def load_job_modules() -> None:
    """Import modules that register jobs (side effect)."""
    import importlib

    for mod in (
        "signal_core.radar.jobs",
        "signal_core.routines.engine",
    ):
        try:
            importlib.import_module(mod)
        except ModuleNotFoundError as e:
            if not e.name or not mod.startswith(e.name):
                raise


async def _record(
    name: str, key: str, status: str, attempts: int, payload: dict[str, Any], error: str | None
) -> None:
    async with session_scope() as s:
        row = (await s.execute(select(Job).where(Job.key == key, Job.name == name))).scalar_one_or_none()
        if row is None:
            s.add(Job(name=name, key=key, status=status, attempts=attempts, payload=payload, error=error))
        else:
            row.status, row.attempts, row.error = status, attempts, error


async def run_with_retries(name: str, key: str, kwargs: dict[str, Any], backoff_s: float = 0.0) -> Any:
    load_job_modules()
    fn = JOBS[name]
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = await fn(**kwargs)
            await _record(name, key, "ok", attempt, kwargs, None)
            return result
        except Exception as e:
            err = "".join(traceback.format_exception_only(e)).strip()
            from signal_core.ops.metrics import JOB_FAILURES

            JOB_FAILURES.labels(name).inc()
            log.warning("job_failed", job=name, key=key, attempt=attempt, error=err)
            if attempt == MAX_ATTEMPTS:
                await _record(name, key, "dead", attempt, kwargs, err + "\n" + traceback.format_exc()[-2000:])
                raise
            await _record(name, key, "error", attempt, kwargs, err)
            if backoff_s:
                await asyncio.sleep(backoff_s * 2 ** (attempt - 1))
    return None


async def enqueue(name: str, *, key: str, **kwargs: Any) -> Any:
    """Enqueue (Redis) or run inline. Returns the job result when inline."""
    s = get_settings()
    if s.use_redis_queue:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(s.redis_url))
        try:
            await pool.enqueue_job("dispatch", name, key, kwargs, _job_id=f"{name}:{key}")
        finally:
            await pool.aclose()
        return None
    return await run_with_retries(name, key, kwargs)
