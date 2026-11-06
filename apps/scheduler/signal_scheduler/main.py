"""Scheduler service: reads the routines table every 30 s and enqueues due runs (§5.1).

Also writes a heartbeat setting; a missed-window alert is raised by nightly maintenance (§16.4).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from signal_core.db.session import session_scope
from signal_core.jobs import enqueue
from signal_core.logging import configure_logging, get_logger
from signal_core.routines.engine import due_routines
from signal_core.services.settings_store import set_setting

log = get_logger("scheduler")
TICK_S = 30


async def tick(now: datetime | None = None) -> list[str]:
    now = now or datetime.now(UTC)
    async with session_scope() as s:
        due = await due_routines(s, now)
        for r in due:  # claim before enqueue so a slow run is never double-enqueued
            r.last_run_at = now
        await set_setting(s, "scheduler_heartbeat", now.isoformat())
        names = [(str(r.id), r.name) for r in due]
    for rid, name in names:
        log.info("enqueue_routine", routine=name)
        await enqueue(
            "run_routine", key=f"{rid}:{now.strftime('%Y%m%d%H%M')}", routine_id=rid, now=now.isoformat()
        )
    return [n for _, n in names]


async def main() -> None:
    configure_logging()
    while True:
        try:
            await tick()
        except Exception as e:
            log.error("tick_failed", error=str(e))
        await asyncio.sleep(TICK_S)


if __name__ == "__main__":
    asyncio.run(main())
