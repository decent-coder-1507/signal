from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.db.models import Job, Routine, Run
from signal_core.routines import engine
from signal_core.routines.engine import STEPS, StepContext, execute, next_fire


def test_cron_is_interpreted_in_user_timezone() -> None:
    # Weekdays 07:30 IST == 02:00 UTC. Fri 6 Nov 2026 01:00 UTC -> fires 02:00 UTC same day.
    after = datetime(2026, 11, 6, 1, 0, tzinfo=UTC)
    assert next_fire("30 7 * * 1-5", "Asia/Kolkata", after) == datetime(2026, 11, 6, 2, 0, tzinfo=UTC)
    # After Friday's run the next weekday run is Monday 9 Nov.
    assert next_fire("30 7 * * 1-5", "Asia/Kolkata", datetime(2026, 11, 6, 2, 1, tzinfo=UTC)) == datetime(
        2026, 11, 9, 2, 0, tzinfo=UTC
    )


async def test_execute_runs_steps_and_isolates_failures(seeded: AsyncSession) -> None:
    async def ok_step(ctx: StepContext) -> dict[str, int]:
        return {"n": 1}

    async def bad_step(ctx: StepContext) -> None:
        raise RuntimeError("boom")

    STEPS["t_ok"], STEPS["t_bad"] = ok_step, bad_step
    try:
        r = Routine(name="t", cron="0 * * * *", steps=["t_bad", "t_ok", "missing_step"], channels=[])
        seeded.add(r)
        await seeded.flush()
        now = datetime(2026, 11, 6, 5, 0, tzinfo=UTC)
        run = await execute(seeded, r, now)
        assert run.status == "degraded" and run.outputs == {"t_ok": {"n": 1}}
        assert "boom" in run.log and "missing_step: not implemented" in run.log
        # hourly in IST (+05:30) fires at :30 UTC
        assert r.last_run_at == now and r.next_run_at == now + timedelta(minutes=30)
    finally:
        STEPS.pop("t_ok"), STEPS.pop("t_bad")


async def test_scheduler_tick_enqueues_due_routines_inline(seeded: AsyncSession) -> None:
    from signal_scheduler.main import tick

    routines = (await seeded.execute(select(Routine))).scalars().all()
    created = datetime(2026, 11, 5, 20, 0, tzinfo=UTC)
    for r in routines:
        r.created_at = created
        r.last_run_at = None
    await seeded.commit()
    # 02:00 UTC Fri = 07:30 IST: daily_brief is due; weekly (Sunday) is not.
    fired = await tick(datetime(2026, 11, 6, 2, 0, 30, tzinfo=UTC))
    assert "daily_brief" in fired and "weekly_review" not in fired
    runs = (await seeded.execute(select(Run.name))).scalars().all()
    assert "daily_brief" in runs
    jobs = (await seeded.execute(select(Job.status))).scalars().all()
    assert jobs and set(jobs) == {"ok"}
    # Second tick at the same moment fires nothing (idempotent).
    assert await tick(datetime(2026, 11, 6, 2, 0, 45, tzinfo=UTC)) == []


def test_engine_module_exports() -> None:
    assert callable(engine.is_due)
