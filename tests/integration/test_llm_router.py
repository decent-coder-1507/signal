from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.db.models import LLMCall
from signal_core.db.session import session_scope
from signal_core.llm import router as llm
from signal_core.llm.mock import GENERATORS, MockProvider
from signal_core.llm.provider import BudgetExceeded, LLMInvalidOutput, LLMUnavailable


async def ledger(db: AsyncSession) -> list[LLMCall]:
    async with session_scope() as s:
        return list((await s.execute(select(LLMCall).order_by(LLMCall.created_at))).scalars())


async def test_call_writes_ledger_row_and_validates(seeded: AsyncSession) -> None:
    r = await llm.call("ping", {"message": "hi"}, session=seeded)
    assert r.output.answer == "pong: hi"
    assert r.prompt_version == "v1" and r.tier == "fast" and r.model == "claude-haiku-5-5"
    rows = await ledger(seeded)
    assert len(rows) == 1
    row = rows[0]
    assert row.task == "ping" and row.status == "ok" and row.provider == "mock"
    assert row.input_tokens > 0 and row.cost_usd > 0 and row.prompt_version == "v1"


async def test_second_call_is_cache_hit(seeded: AsyncSession) -> None:
    await llm.call("ping", {"message": "same"}, session=seeded)
    await seeded.commit()
    r2 = await llm.call("ping", {"message": "same"}, session=seeded)
    assert r2.cache_hit and r2.cost_usd == 0
    statuses = [c.status for c in await ledger(seeded)]
    assert statuses == ["ok", "cached"]


async def test_invalid_json_is_repaired_once(seeded: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def flaky(inputs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return {"wrong": True} if calls["n"] == 1 else {"answer": "fixed"}

    monkeypatch.setitem(GENERATORS, "ping", flaky)
    r = await llm.call("ping", {"message": "x"}, session=seeded, use_cache=False)
    assert r.output.answer == "fixed"
    assert [c.status for c in await ledger(seeded)] == ["invalid", "ok"]


async def test_invalid_twice_raises(seeded: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(GENERATORS, "ping", lambda i: {"nope": 1})
    with pytest.raises(LLMInvalidOutput):
        await llm.call("ping", {"message": "x"}, session=seeded, use_cache=False)
    assert [c.status for c in await ledger(seeded)] == ["invalid", "invalid"]


async def test_provider_outage_is_logged_and_raised(seeded: AsyncSession) -> None:
    p = MockProvider()
    p.fail_with = LLMUnavailable("auth expired")
    llm.set_provider(p)
    with pytest.raises(LLMUnavailable):
        await llm.call("ping", {"message": "x"}, session=seeded, use_cache=False)
    rows = await ledger(seeded)
    assert rows[0].status == "error" and "auth expired" in (rows[0].error or "")


async def _spend(amount: float) -> None:
    async with session_scope() as s:
        s.add(
            LLMCall(
                task="seed",
                tier="deep",
                model="claude-opus-5-5",
                prompt_version="x",
                status="ok",
                cost_usd=amount,
                created_at=datetime.now(UTC),
            )
        )


async def test_soft_limit_downgrades_deep_to_balanced(seeded: AsyncSession) -> None:
    await _spend(25.0)  # 83% of $30
    r = await llm.call("ping", {"message": "x"}, session=seeded, tier="deep", use_cache=False)
    assert r.tier == "balanced"


async def test_hard_limit_blocks_scheduled_non_fast_calls(seeded: AsyncSession) -> None:
    await _spend(31.0)
    with pytest.raises(BudgetExceeded):
        await llm.call("ping", {"message": "x"}, session=seeded, tier="balanced", use_cache=False)
    fast = await llm.call("ping", {"message": "y"}, session=seeded, tier="fast", use_cache=False)
    assert fast.tier == "fast"
    user = await llm.call(
        "ping", {"message": "z"}, session=seeded, tier="deep", user_initiated=True, use_cache=False
    )
    assert user.tier == "balanced"
    assert "budget_blocked" in [c.status for c in await ledger(seeded)]
