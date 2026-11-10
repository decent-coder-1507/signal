"""ADR-027 trust + in-app features: brief provenance, change password + default-password flag, report inaccuracy
on any generated output, engine-quality status, in-app 'brief ready' notifications."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from asgi_lifespan import LifespanManager
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_api.main import create_app
from signal_core.auth import hash_password
from signal_core.db.models import EvalCase, Notification, User
from signal_core.demo import fixture_client, seed_fixture_sources
from signal_core.radar.jobs import ingest_all_due
from signal_core.radar.pipeline import process
from signal_core.settings import get_settings

NOW = datetime(2026, 11, 6, 1, 0, tzinfo=UTC)
EMAIL, PW = "owner@test.local", "correct horse battery"


class _PinnedDatetime(datetime):
    @classmethod
    def now(cls, tz: object = None) -> _PinnedDatetime:  # type: ignore[override]
        return cls.fromtimestamp((NOW + timedelta(hours=1)).timestamp(), tz=UTC)


async def _client(app_seeded: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    from signal_api.routers.auth import _attempts, _default_pw

    _attempts.clear()
    _default_pw.clear()
    app = create_app()
    async with (
        LifespanManager(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c,
    ):
        r = await c.post("/auth/login", json={"email": EMAIL, "password": PW})
        assert r.status_code == 200, r.text
        c.headers["x-csrf-token"] = r.json()["csrf"]
        yield c


@pytest.fixture
async def client(seeded: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    async for c in _client(seeded):
        yield c


@pytest.fixture
async def news_client(
    seeded: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    import signal_api.routers.briefs as briefs_router

    monkeypatch.setattr(briefs_router, "datetime", _PinnedDatetime)
    await seed_fixture_sources(seeded, include_broken=False)
    await seeded.commit()
    await ingest_all_due(NOW, fixture_client(NOW))
    await process(seeded, NOW)
    await seeded.commit()
    async for c in _client(seeded):
        yield c


# ---------------------------------------------------------------- provenance
async def test_brief_provenance_on_demand_and_routine(
    news_client: httpx.AsyncClient, seeded: AsyncSession
) -> None:
    b = (await news_client.post("/briefs/generate", json={"kind": "daily"})).json()
    p = (await news_client.get(f"/briefs/{b['id']}/provenance")).json()
    shown = len(b["content"]["stories"])
    assert p["stories"]["shown"] == shown >= 1
    # eligible = above the score bar; the exploration slot may add one story from just below it
    assert p["stories"]["considered"] >= max(p["stories"]["eligible"], shown)
    assert p["items"]["in_window"] >= p["items"]["passed_prefilter"] >= 1
    assert p["sources"]["scanned"] >= 1
    assert p["citations"]["total"] >= shown and p["citations"]["verified"] == p["citations"]["total"]
    assert p["ai"]["scope"] == "window" and p["run"] is None
    assert p["degraded"] is b["degraded"] and p["generated_at"]
    assert (await news_client.get(f"/briefs/{uuid.uuid4()}/provenance")).status_code == 404

    # A routine brief attributes exactly the ledger rows tagged with its run.
    routines = {r["name"]: r for r in (await news_client.get("/routines")).json()}
    run = (await news_client.post(f"/routines/{routines['daily_brief']['id']}/run-now")).json()
    rid = run["outputs"]["assemble_brief"]["brief_id"]
    p2 = (await news_client.get(f"/briefs/{rid}/provenance")).json()
    assert p2["ai"]["scope"] == "run" and p2["run"]["id"] == run["id"]
    assert p2["ai"]["calls"] >= 1 and p2["ai"]["models"] and p2["ai"]["tasks"]
    assert sum(m["calls"] for m in p2["ai"]["models"]) == p2["ai"]["calls"]
    # ...and leaves an in-app "brief ready" notification (ADR-027: everything happens in the app).
    notes = (await news_client.get("/notifications")).json()
    ready = [n for n in notes if n["kind"] == "brief" and n["payload"].get("brief_id") == rid]
    assert ready and ready[0]["payload"]["title"].startswith("Your daily brief is ready")
    assert (
        not (await seeded.execute(select(Notification).where(Notification.channel == "telegram")))
        .scalars()
        .all()
    )  # daily_brief no longer targets Telegram


# ---------------------------------------------------------------- password
async def test_change_password_flow(client: httpx.AsyncClient) -> None:
    me = (await client.get("/me")).json()
    assert me["default_password"] is False
    bad = await client.post("/auth/password", json={"current_password": "nope", "new_password": "x" * 14})
    assert bad.status_code == 403
    short = await client.post("/auth/password", json={"current_password": PW, "new_password": "short-pw"})
    assert short.status_code == 422 and "12" in short.json()["detail"]
    placeholder = await client.post(
        "/auth/password", json={"current_password": PW, "new_password": "change-me-now-but-long"}
    )
    assert (
        placeholder.status_code == 200
    )  # only the exact placeholder is refused; this is a different password
    new = "a much better passphrase"
    ok = await client.post(
        "/auth/password", json={"current_password": "change-me-now-but-long", "new_password": new}
    )
    assert ok.status_code == 200
    await client.post("/auth/logout")
    assert (await client.post("/auth/login", json={"email": EMAIL, "password": PW})).status_code == 401
    assert (await client.post("/auth/login", json={"email": EMAIL, "password": new})).status_code == 200


async def test_change_password_rejects_placeholder_and_is_rate_limited(client: httpx.AsyncClient) -> None:
    r = await client.post("/auth/password", json={"current_password": PW, "new_password": "change-me-now"})
    assert r.status_code == 422
    codes = [
        (
            await client.post("/auth/password", json={"current_password": "wrong", "new_password": "y" * 14})
        ).status_code
        for _ in range(11)
    ]
    assert codes[0] == 403 and codes[-1] == 429 and set(codes) == {403, 429}  # shares the login 10/min bucket


async def test_default_password_flag(client: httpx.AsyncClient, seeded: AsyncSession) -> None:
    user = (await seeded.execute(select(User))).scalar_one()
    user.password_hash = hash_password("change-me-now")
    await seeded.commit()
    assert (await client.get("/me")).json()["default_password"] is True


# ---------------------------------------------------------------- report inaccuracy
@pytest.mark.parametrize("target", ["explainer", "answer", "idea", "draft", "story"])
async def test_report_inaccuracy_creates_eval_case(
    client: httpx.AsyncClient, seeded: AsyncSession, target: str
) -> None:
    tid = str(uuid.uuid4())
    r = await client.post(
        "/feedback",
        json={"target_type": target, "target_id": tid, "kind": "wrong", "context": {"block": "x"}},
    )
    assert r.status_code == 201
    cases = (await seeded.execute(select(EvalCase).where(EvalCase.origin == "user_report"))).scalars().all()
    assert [c.task for c in cases] == [f"report:{target}"] and cases[0].input["target_id"] == tid


# ---------------------------------------------------------------- engine quality
async def test_bench_status_snapshot_spotcheck_and_background_run(
    client: httpx.AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from signal_core.ops.bench import status as bench_status

    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    s = (await client.get("/ops/bench")).json()
    assert s["latest"]["origin"] == "snapshot" and s["latest"]["metrics"]["cluster"]["f1"] > 0.5
    assert s["spotcheck"]["rows"] == 30 and s["running"] is False

    # The real run takes minutes; a stand-in child process writes a tiny result in the same format.
    fake = tmp_path / "fake_bench.py"
    fake.write_text(
        "import json,sys\n"
        "json.dump({'variant':'current','prefilter':{'recall':0.9,'precision':0.5,'auc':0.8},"
        "'cluster':{'precision':0.8,'recall':0.9,'f1':0.85},'ranking':{'test':{'ndcg@10':0.7,'p@7':0.8}},"
        "'labels':{'items':1,'pairs':1,'questions':0,'judged':0}}, open(sys.argv[-1],'w'))\n"
    )
    monkeypatch.setattr(bench_status.runner, "command", lambda out: [sys.executable, str(fake), str(out)])
    r = (await client.post("/ops/bench/run")).json()
    assert r["started"] is True
    for _ in range(100):
        if not bench_status.runner.running:
            break
        await asyncio.sleep(0.1)
    s = (await client.get("/ops/bench")).json()
    assert s["error"] is None, s["error"]
    assert s["latest"]["origin"] == "local" and s["latest"]["metrics"]["cluster"]["f1"] == 0.85
    assert s["latest"]["metrics"]["ask"] is None
    assert json.loads((tmp_path / "bench" / "latest.json").read_text())["duration_s"] is not None


def test_spotcheck_counts_marked_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from signal_core.ops.bench.status import spotcheck

    (tmp_path / "bench").mkdir()
    (tmp_path / "bench" / "SPOTCHECK.md").write_text(
        "| # | t | agree? (y/n) |\n|---|---|---|\n| 1 | a | y |\n| 2 | b | n |\n| 3 | c | Y |\n| 4 | d |  |\n"
    )
    monkeypatch.setattr(get_settings(), "fixtures_dir", tmp_path)
    assert spotcheck() == {"rows": 4, "agree": 2, "disagree": 1, "reviewed": True}
