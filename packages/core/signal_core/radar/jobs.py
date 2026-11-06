"""RADAR ingestion jobs + the `ingest_due_sources` routine step."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from signal_core.db.session import session_scope
from signal_core.jobs import job
from signal_core.radar.ingest import (
    apply_phase,
    due_sources,
    fetch_phase,
    ingest_source,
    screen_new_items,
    spec_of,
)
from signal_core.routines.engine import StepContext, step
from signal_core.settings import get_settings
from signal_core.sources.http import PoliteClient


@job("ingest_source")
async def ingest_source_job(source_id: str, now: str | None = None) -> dict[str, Any]:
    async with session_scope() as s:
        st = await ingest_source(s, uuid.UUID(source_id), now=datetime.fromisoformat(now) if now else None)
        return {"source": st.source, "status": st.status, "new": st.new, "passed": st.passed}


async def ingest_all_due(
    now: datetime | None = None, http: PoliteClient | None = None
) -> list[dict[str, Any]]:
    """Phase 1: fetch every due source concurrently over HTTP, holding no DB connection.
    Phase 2: store each source's entries in its own short transaction (sequential, so the DB pool is never
    exhausted). Phase 3: screen (dedupe + prefilter) everything once, oldest first."""
    now = now or datetime.now(UTC)
    async with session_scope() as s:
        specs = [spec_of(src) for src in await due_sources(s, now)]
    own = http is None
    if http is None and get_settings().is_mock:
        from signal_core.demo import fixture_client

        http = fixture_client(now)
    client = http or PoliteClient(
        concurrency=get_settings().http_concurrency, timeout_s=get_settings().http_timeout_s
    )
    try:
        outcomes = await asyncio.gather(*(fetch_phase(sp, client) for sp in specs))
    finally:
        if own:
            await client.aclose()
    results: list[dict[str, Any]] = []
    for oc in outcomes:
        try:
            async with session_scope() as s:
                st = await apply_phase(s, oc, now, screen=False)
            results.append(
                {
                    "source": st.source,
                    "status": st.status,
                    "found": st.found,
                    "new": st.new,
                    "passed": 0,
                    "duplicates": 0,
                    "error": st.error,
                }
            )
        except Exception as e:
            results.append(
                {
                    "source": str(oc.source_id),
                    "status": "error",
                    "found": 0,
                    "new": 0,
                    "passed": 0,
                    "duplicates": 0,
                    "error": f"store failed: {e.__class__.__name__}: {e}"[:500],
                }
            )
    # Screen (dedupe + prefilter) once everything is committed, sequentially and oldest-first.
    async with session_scope() as s:
        sc = await screen_new_items(s, now)
    results.append(
        {
            "source": "_screen",
            "status": "ok",
            "found": 0,
            "new": 0,
            "passed": sc.passed,
            "duplicates": sc.duplicates,
            "prefiltered_out": sc.prefiltered_out,
            "error": None,
        }
    )
    return results


@step("ingest_due_sources")
async def step_ingest(ctx: StepContext) -> dict[str, Any]:
    results = await ingest_all_due(ctx.now)
    return {
        "sources": len(results),
        "new_items": sum(r["new"] for r in results),
        "passed_prefilter": sum(r["passed"] for r in results),
        "errors": [r["source"] for r in results if r["status"] == "error"],
    }
