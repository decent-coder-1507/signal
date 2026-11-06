"""Demo pipeline after fixture ingest (mock mode): RADAR processing, then later-milestone stages."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from signal_core.db.session import session_scope


async def run_demo_pipeline(now: datetime) -> dict[str, Any]:
    from signal_core.radar.pipeline import process

    async with session_scope() as s:
        out = await process(s, now)
    return {"radar": out}
