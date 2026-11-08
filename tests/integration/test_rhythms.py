"""M8 acceptance: default routines run on schedule in mock mode with expected outputs; Telegram commands against a
mock Telegram server; weekly review completable end-to-end; notification cap + quiet hours enforced."""

import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from asgi_lifespan import LifespanManager
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_api.main import create_app
from signal_core.db.models import Brief, Card, Idea, Item, Notification, Routine, Run
from signal_core.demo import fixture_client, seed_fixture_sources
from signal_core.notify import telegram
from signal_core.notify.dispatcher import dispatch, flush_queued
from signal_core.radar.jobs import ingest_all_due
from signal_core.radar.pipeline import process
from signal_core.routines.engine import next_fire
from signal_core.services.settings_store import set_setting
from signal_core.settings import get_settings

EMAIL, PW = "owner@test.local", "correct horse battery"
CHAT = "424242"


class FakeTelegram:
    """Mock Telegram Bot API server: records every call and replies ok."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []  # type: ignore[type-arg]

    def __call__(self, req: httpx.Request) -> httpx.Response:
        method = req.url.path.rsplit("/", 1)[-1]
        body = json.loads(req.content or b"{}")
        self.calls.append((method, body))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(self.calls)}})

    def texts(self) -> list[str]:
        return [b.get("text", "") for m, b in self.calls if m == "sendMessage"]


@pytest.fixture
def tg(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeTelegram]:
    fake = FakeTelegram()
    s = get_settings()
    monkeypatch.setattr(s, "telegram_bot_token", "123:TEST")
    monkeypatch.setattr(s, "telegram_chat_id", CHAT)
    telegram.set_transport(httpx.MockTransport(fake))
    yield fake
    telegram.set_transport(None)


@pytest.fixture
def outbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    return tmp_path / "outbox"


async def prepare(db: AsyncSession, now: datetime) -> None:
    await seed_fixture_sources(db, include_broken=False)
    await db.commit()
    await ingest_all_due(now, fixture_client(now))
    await process(db, now)
    await set_setting(db, "flags", {"channel.telegram": True, "channel.email": True})
    await db.commit()


def msg(text: str, chat: str = CHAT) -> dict:  # type: ignore[type-arg]
    return {"update_id": 1, "message": {"message_id": 1, "chat": {"id": int(chat)}, "text": text}}


def cb(data: str) -> dict:  # type: ignore[type-arg]
    return {
        "update_id": 2,
        "callback_query": {"id": "cb1", "data": data, "message": {"chat": {"id": int(CHAT)}}},
    }


EXPECTED = {
    "continuous_ingest": {"ingest_due_sources"},
    "daily_brief": {"score", "insights", "lab_spark", "gym_item", "assemble_brief"},
    "weekend_brief": {"score", "insights", "assemble_brief"},
    "cards_nudge": {"cards_due_check"},
    "weekly_review": {
        "weekly_recap",
        "content_plan",
        "idea_of_week",
        "learn_next",
        "quiz",
        "metrics_summary",
    },
    "monthly_review": {
        "state_of_tech",
        "moat_radar",
        "idea_pipeline_review",
        "skill_progress",
        "tuning_proposals",
        "cost_report",
    },
    "nightly_maintenance": {"cluster_merge", "retrain_preferences", "source_health"},
    "content_nudges": {"publish_assist_nudges", "flush_notifications"},
}


async def test_every_default_routine_runs_on_schedule(
    seeded: AsyncSession, tg: FakeTelegram, outbox: Path
) -> None:
    from signal_scheduler.main import tick

    base = datetime(2026, 10, 31, 18, 0, tzinfo=UTC)  # Sat 31 Oct 23:30 IST — before Sun/1st-of-month runs
    await prepare(seeded, base)
    routines = list((await seeded.execute(select(Routine))).scalars())
    for r in routines:
        r.created_at, r.last_run_at = base, base
    await seeded.commit()
    # Simulate the next 8 days (quarterly reset on 1 Jan is out of range and would replay everything in between).
    schedule = sorted(
        (t, r.name) for r in routines if (t := next_fire(r.cron, r.timezone, base)) < base + timedelta(days=8)
    )
    for t, _name in schedule:  # fire in chronological order, like real time would
        await tick(t + timedelta(seconds=1))
    runs: dict[str, Run] = {}
    for r in (await seeded.execute(select(Run).order_by(Run.started_at))).scalars():
        runs.setdefault(r.name, r)  # first run of each routine = its scheduled run
    for name, steps in EXPECTED.items():
        run = runs[name]
        assert run.status == "ok", (name, run.log)
        assert steps <= set(run.outputs), (name, sorted(run.outputs))
    # The fixture news is ~2 days old by Monday's 07:30 brief, so it is either fresh stories or the quiet-day rule.
    daily = await seeded.get(
        Brief, __import__("uuid").UUID(runs["daily_brief"].outputs["assemble_brief"]["brief_id"])
    )
    assert daily.content["stories"] or daily.content["quiet"]["message"].startswith("Quiet day")
    weekend = runs["weekend_brief"].outputs["assemble_brief"]
    assert weekend["stories"] >= 1  # Sunday brief, within the 60 h window
    assert runs["weekly_review"].outputs["_review_brief_id"]
    assert runs["monthly_review"].outputs["moat_radar"]["radar_id"]
    # Delivery: daily brief went to Telegram (mock server) and the weekly review to email (outbox).
    assert any("stories" in t for t in tg.texts())
    assert list(outbox.glob("*-weekly.eml")) and list(outbox.glob("*-monthly.eml"))


async def test_telegram_commands_against_mock_server(seeded: AsyncSession, tg: FakeTelegram) -> None:
    from signal_core.brief.assemble import assemble

    now = datetime.now(UTC) - timedelta(hours=1)
    await prepare(seeded, now)
    b = await assemble(seeded, now)
    sid = b.content["stories"][0]["story_id"]

    assert (await telegram.handle_update(seeded, msg("/brief")))["found"] is True
    assert "Your brief" in tg.texts()[-1]
    kb = [m for m in tg.calls if m[0] == "sendMessage"][-1][1]["reply_markup"]["inline_keyboard"]
    assert kb[0][0]["callback_data"] == f"fb:{sid}:useful"

    assert (await telegram.handle_update(seeded, cb(f"fb:{sid}:useful")))["kind"] == "useful"
    assert ("answerCallbackQuery", {"callback_query_id": "cb1"}) in tg.calls

    r = await telegram.handle_update(seeded, msg("/save https://blog.example/a-post"))
    assert (await seeded.get(Item, __import__("uuid").UUID(r["item_id"]))) is not None
    r = await telegram.handle_update(seeded, msg("/idea CLI that diffs model outputs"))
    assert (await seeded.get(Idea, __import__("uuid").UUID(r["idea_id"]))).status == "shortlisted"
    r = await telegram.handle_update(seeded, msg("Remember: try speculative decoding on the staging box"))
    assert r["cmd"] == "note"

    # Card mini-session: front → show → rate → next
    from signal_core.gym.service import explainer

    await explainer(seeded, "Agents & tool use", "plain")
    r = await telegram.handle_update(seeded, msg("/cards"))
    cid = r["card_id"]
    await telegram.handle_update(seeded, cb(f"card:{cid}:show"))
    assert "✅" in tg.texts()[-1]
    assert (await telegram.handle_update(seeded, cb(f"card:{cid}:3")))["rating"] == 3
    card = await seeded.get(Card, __import__("uuid").UUID(cid))
    assert card.due_at > datetime.now(UTC) + timedelta(days=1)

    r = await telegram.handle_update(seeded, msg("/post 1"))
    assert r["angles"] >= 3
    assert (await telegram.handle_update(seeded, msg("/brief", chat="999")))[
        "ignored"
    ]  # other chats are refused
    _ = Brief


async def test_notification_cap_and_quiet_hours(seeded: AsyncSession, tg: FakeTelegram) -> None:
    await set_setting(seeded, "flags", {"channel.telegram": True})
    noon = datetime(2026, 11, 9, 6, 30, tzinfo=UTC)  # 12:00 IST
    statuses = [
        (await dispatch(seeded, "telegram", "note", {"text": f"n{i}"}, noon)).status for i in range(6)
    ]
    assert statuses == ["sent"] * 4 + ["suppressed"] * 2  # max_per_day = 4
    assert len(tg.texts()) == 4
    apps = (await seeded.execute(select(Notification).where(Notification.channel == "app"))).scalars().all()
    assert len(apps) == 2  # suppressed ones stay visible in-app
    night = datetime(2026, 11, 9, 17, 45, tzinfo=UTC)  # 23:15 IST → quiet hours (22:30–07:00)
    n = await dispatch(seeded, "telegram", "note", {"text": "late"}, night)
    assert n.status == "queued" and n.payload["_reason"] == "quiet hours"
    morning = datetime(2026, 11, 10, 2, 0, tzinfo=UTC)  # 07:30 IST next day
    assert await flush_queued(seeded, morning) == 1
    assert tg.texts()[-1] == "late"
    next_night = night + timedelta(days=1)  # quiet hours again, but a fresh daily cap
    urgent = await dispatch(seeded, "telegram", "watch", {"text": "urgent"}, next_night, urgent=True)
    assert urgent.status == "sent"  # instant alerts bypass quiet hours (still within the daily cap)


@pytest.fixture
async def client(seeded: AsyncSession, outbox: Path) -> AsyncIterator[httpx.AsyncClient]:
    from signal_api.routers.auth import _attempts

    _attempts.clear()
    await prepare(seeded, datetime.now(UTC) - timedelta(hours=2))
    app = create_app()
    async with (
        LifespanManager(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=180) as c,
    ):
        r = await c.post("/auth/login", json={"email": EMAIL, "password": PW})
        c.headers["x-csrf-token"] = r.json()["csrf"]
        yield c


async def test_weekly_review_end_to_end(client: httpx.AsyncClient) -> None:
    rv = (await client.post("/reviews/generate?kind=weekly")).json()
    keys = [s["key"] for s in rv["content"]["sections"]]
    assert {"recap", "content_plan", "idea_of_week", "learn_next", "quiz", "metrics"} <= set(keys), (
        keys,
        rv.get("log"),
    )
    assert rv["content"]["flow"] == ["recap", "content_plan", "idea", "learn", "quiz", "metrics"]
    by_key = {s["key"]: s for s in rv["content"]["sections"]}
    for key in ("idea_of_week", "learn_next", "quiz"):  # readable: text or links, never only raw data
        assert by_key[key].get("text") or by_key[key].get("items"), by_key[key]
        assert all(i["href"].startswith(("/lab/", "/gym?")) for i in by_key[key].get("items", []))
    r = await client.post(f"/reviews/{rv['id']}/complete")
    assert r.status_code == 409 and r.json()["detail"]["missing"]
    plan = next(s for s in rv["content"]["sections"] if s["key"] == "content_plan")
    for step in rv["content"]["flow"]:
        data = {"accept": [p["story_id"] for p in plan["proposals"][:1]]} if step == "content_plan" else {}
        out = (await client.post(f"/reviews/{rv['id']}/step", json={"key": step, "data": data})).json()
        if step == "content_plan":
            assert out["angles_created"] >= 3
    done = (await client.post(f"/reviews/{rv['id']}/complete")).json()
    assert done["completed_at"]
    assert (await client.get("/reviews/latest?kind=weekly")).json()["id"] == rv["id"]


async def test_monthly_review_pdf(client: httpx.AsyncClient) -> None:
    rv = (await client.post("/reviews/generate?kind=monthly")).json()
    assert {"state_of_tech", "tuning", "costs"} <= {s["key"] for s in rv["content"]["sections"]}
    pdf = await client.get(f"/reviews/{rv['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


async def test_telegram_webhook_requires_secret(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/telegram/webhook", json=msg("/brief"), headers={"x-telegram-bot-api-secret-token": "x"}
    )
    assert r.status_code == 401
