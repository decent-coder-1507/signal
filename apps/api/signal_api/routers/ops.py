from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis.asyncio import Redis
from sqlalchemy import text

from signal_api.deps import DB, CurrentUser
from signal_core.config import get_config
from signal_core.llm import router as llm
from signal_core.settings import get_settings

router = APIRouter(tags=["ops"])


@router.get("/health")
async def health(db: DB) -> dict[str, Any]:
    s = get_settings()
    checks: dict[str, Any] = {}
    try:
        await db.execute(text("select 1"))
        checks["db"] = "ok"
    except Exception as e:  # pragma: no cover - surfaced to the caller
        checks["db"] = f"error: {e.__class__.__name__}"
    try:
        get_config()
        checks["config"] = "ok"
    except Exception as e:  # pragma: no cover
        checks["config"] = f"error: {e}"
    if s.use_redis_queue:
        try:
            r = Redis.from_url(s.redis_url)
            await r.ping()
            await r.aclose()
            checks["redis"] = "ok"
        except Exception as e:  # pragma: no cover
            checks["redis"] = f"error: {e.__class__.__name__}"
    p = llm.get_provider()
    checks["llm"] = {
        "provider": p.name,
        "healthy": getattr(p, "healthy", True),
        "last_error": getattr(p, "last_error", None),
    }
    ok = all(v == "ok" for k, v in checks.items() if k != "llm")
    return {"status": "ok" if ok else "degraded", "mode": s.mode, "checks": checks}


@router.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.post("/ops/llm-ping")
async def llm_ping(_: CurrentUser, db: DB, message: str = "hello") -> dict[str, Any]:
    """Proves router → provider → ledger (M0 acceptance)."""
    r = await llm.call("ping", {"message": message}, session=db, user_initiated=True, use_cache=False)
    return {
        "answer": r.output.answer,
        "model": r.model,
        "prompt_version": r.prompt_version,
        "call_id": str(r.call_id),
    }
