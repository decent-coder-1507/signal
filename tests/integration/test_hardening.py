"""M10 acceptance: budget soft/hard limits (costs page), degraded-brief fallback, evals report, restore drill,
ops endpoints, and 7 consecutive days of briefs without manual intervention (time-travel simulation)."""

import shutil
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from asgi_lifespan import LifespanManager
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_api.main import create_app
from signal_core.brief.assemble import assemble
from signal_core.db.models import Brief, Job, LLMCall, Routine, Run
from signal_core.db.session import session_scope
from signal_core.demo import fixture_client, seed_fixture_sources
from signal_core.llm import router as llm
from signal_core.llm.mock import MockProvider
from signal_core.llm.provider import LLMUnavailable
from signal_core.radar.jobs import ingest_all_due
from signal_core.radar.pipeline import process
from signal_core.routines.engine import next_fire
from signal_core.services.settings_store import set_setting
from signal_core.settings import get_settings

EMAIL, PW = "owner@test.local", "correct horse battery"


async def prepare(db: AsyncSession, now: datetime) -> None:
    await seed_fixture_sources(db, include_broken=False)
    await db.commit()
    await ingest_all_due(now, fixture_client(now))
    await process(db, now)
    await db.commit()


async def test_degraded_brief_when_llm_unavailable(seeded: AsyncSession) -> None:
    now = datetime.now(UTC) - timedelta(hours=1)
    await seed_fixture_sources(seeded, include_broken=False)
    await seeded.commit()
    p = MockProvider()
    p.fail_with = LLMUnavailable("Claude CLI not authenticated")
    llm.set_provider(p)
    await ingest_all_due(now, fixture_client(now))
    await process(seeded, now)  # enrichment/insights unavailable → nothing crashes
    b = await assemble(seeded, now)
    assert b.degraded is True
    # Without enrichment there are no stories yet; the brief is still produced (quiet message) and marked degraded.
    assert b.content["stories"] or b.content["quiet"]


async def test_degraded_insight_when_llm_dies_after_scoring(seeded: AsyncSession) -> None:
    now = datetime.now(UTC) - timedelta(hours=1)
    await seed_fixture_sources(seeded, include_broken=False)
    await seeded.commit()
    await ingest_all_due(now, fixture_client(now))
    from signal_core.radar.pipeline import process as proc

    await proc(seeded, now, insights=False)  # stories scored, no insights yet
    p = MockProvider()
    p.fail_with = LLMUnavailable("usage limit reached")
    llm.set_provider(p)
    b = await assemble(seeded, now)
    assert b.degraded and b.content["stories"]
    assert all(s["degraded"] for s in b.content["stories"])
    assert all(s["citations"] for s in b.content["stories"])  # extractive, still cited


@pytest.fixture
async def client(
    seeded: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    from signal_api.routers.auth import _attempts

    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    _attempts.clear()
    await prepare(seeded, datetime.now(UTC) - timedelta(hours=2))
    app = create_app()
    async with (
        LifespanManager(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=300) as c,
    ):
        r = await c.post("/auth/login", json={"email": EMAIL, "password": PW})
        c.headers["x-csrf-token"] = r.json()["csrf"]
        yield c


async def test_costs_page_reflects_budget_states(client: httpx.AsyncClient) -> None:
    c = (await client.get("/costs")).json()
    assert c["state"] == "ok" and c["by_task"] and c["by_day"] and c["limit"] == 30
    async with session_scope() as s:
        s.add(
            LLMCall(
                task="seed",
                tier="deep",
                model="claude-opus-5-5",
                prompt_version="x",
                status="ok",
                cost_usd=25.0,
            )
        )
    assert (await client.get("/costs")).json()["state"] == "soft"
    async with session_scope() as s:
        s.add(
            LLMCall(
                task="seed",
                tier="deep",
                model="claude-opus-5-5",
                prompt_version="x",
                status="ok",
                cost_usd=6.0,
            )
        )
    c = (await client.get("/costs")).json()
    assert c["state"] == "hard" and c["projected"] >= c["month_spent"]
    # The monthly budget set in onboarding overrides config: $31 spent of $100 is fine again.
    async with session_scope() as s:
        await set_setting(s, "budget_monthly_usd", 100)
    c = (await client.get("/costs")).json()
    assert c["limit"] == 100 and c["state"] == "ok"
    led = (await client.get("/llm-calls?limit=5")).json()
    assert len(led) == 5 and {"task", "model", "cost_usd", "status"} <= set(led[0])


async def test_evals_report_meets_targets(client: httpx.AsyncClient) -> None:
    assert (await client.get("/evals/report")).json() is None
    r = (await client.post("/evals/run")).json()
    m = r["metrics"]
    assert r["cases"]["enrich"] >= 30 and r["cases"]["factcheck"] >= 30
    for name in (
        "enrich_json_valid",
        "enrich_quote_span_accuracy",
        "cluster_purity",
        "factcheck_recall",
        "banned_phrase_rate",
    ):
        assert m[name]["passed"], (name, m[name])
    assert r["passed"] is True
    again = (await client.get("/evals/report")).json()
    assert again["id"] == r["id"]


async def test_dead_letters_visible(client: httpx.AsyncClient) -> None:
    from signal_core.jobs import JOBS, run_with_retries

    async def boom() -> None:
        raise RuntimeError("source exploded")

    JOBS["t_boom"] = boom
    try:
        with pytest.raises(RuntimeError):
            await run_with_retries("t_boom", "k1", {})
    finally:
        JOBS.pop("t_boom")
    dead = (await client.get("/ops/jobs?status=dead")).json()
    assert dead and dead[0]["attempts"] == 3 and "source exploded" in dead[0]["error"]
    _ = Job


@pytest.mark.skipif(
    not (shutil.which("pg_dump") or shutil.which("docker") or shutil.which("wsl")),
    reason="needs pg_dump, docker or WSL docker",
)
async def test_restore_drill(seeded: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from signal_core.ops.backup import _prune, drill

    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    await prepare(seeded, datetime.now(UTC) - timedelta(hours=2))
    r = drill()
    assert r["match"] and r["source_counts"]["items"] > 0 and r["size_bytes"] > 0
    daily = tmp_path / "backups" / "daily"
    for k in range(20):
        (daily / f"signal-20260101-0000{k:02d}.dump").write_bytes(b"x")
    _prune(daily, 14)
    assert len(list(daily.glob("signal-*.dump"))) == 14


async def test_seven_days_of_briefs_without_intervention(
    seeded: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Time-travel: the scheduler alone produces a brief every day for 7 days (weekday 07:30 / weekend 09:00 IST),
    the nightly maintenance and the weekly review run, and no run fails. Continuous ingest runs at 06:00 IST in the
    simulation (48 fetches/day would only re-fetch the same fixtures)."""
    from signal_scheduler.main import tick

    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    monkeypatch.setattr(
        "signal_core.ops.backup.backup",
        lambda now=None, **kw: type("R", (), {"dump": Path("sim.dump"), "size_bytes": 1, "pruned": []})(),
    )
    start = datetime(2026, 11, 9, 0, 0, tzinfo=UTC)  # Monday 05:30 IST
    await seed_fixture_sources(seeded, include_broken=False)
    for r in (await seeded.execute(select(Routine))).scalars():
        r.created_at, r.last_run_at = start, start
        if r.name == "continuous_ingest":
            r.cron = "0 6 * * *"
        if r.name in ("content_nudges", "metrics_prompts"):
            r.cron = "0 */6 * * *"
        if r.name in ("monthly_review", "quarterly_reset"):
            r.enabled = False  # outside the 7-day window anyway
    await seeded.commit()
    routines = list((await seeded.execute(select(Routine).where(Routine.enabled.is_(True)))).scalars())
    fires: list[datetime] = []
    for r in routines:
        t = start
        while True:
            t = next_fire(r.cron, r.timezone, t)
            if t >= start + timedelta(days=7):
                break
            fires.append(t)
    for t in sorted(set(fires)):
        await tick(t + timedelta(seconds=1))
    runs = list((await seeded.execute(select(Run))).scalars())
    failed = [(r.name, r.log[-300:]) for r in runs if r.status != "ok"]
    assert not failed, failed
    briefs = list(
        (
            await seeded.execute(
                select(Brief)
                .where(Brief.kind.in_(["daily", "weekend", "catchup"]))
                .order_by(Brief.created_at)
            )
        ).scalars()
    )
    days = {b.period_end.date() for b in briefs}
    assert len(days) == 7, sorted(days)
    assert briefs[0].content["stories"]  # the first morning has real stories
    assert sum(1 for r in runs if r.name == "nightly_maintenance") == 7
    assert any(r.name == "weekly_review" for r in runs)
