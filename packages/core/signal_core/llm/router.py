"""llm.router.call(task, inputs, tier) — the only way SIGNAL talks to an LLM (§5.4).

Loads a versioned prompt, enforces JSON-schema output (Pydantic; one repair retry with the error
appended), caches by (prompt_version, input hash), writes an llm_calls ledger row, checks the budget.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.config import get_config
from signal_core.config.schemas import BudgetCfg
from signal_core.db.models import LLMCache, LLMCall
from signal_core.llm import budget as budget_mod
from signal_core.llm.prompts import select as select_prompt
from signal_core.llm.provider import (
    BudgetExceeded,
    LLMError,
    LLMInvalidOutput,
    LLMProvider,
    LLMResult,
    LLMUnavailable,
    Msg,
    Tier,
)
from signal_core.llm.schemas import SCHEMAS
from signal_core.settings import get_settings

T = TypeVar("T", bound=BaseModel)

_provider: LLMProvider | None = None


def get_provider() -> LLMProvider:
    global _provider
    if _provider is None:
        s = get_settings()
        if s.is_mock or get_config().budget.provider == "mock":
            from signal_core.llm.mock import MockProvider

            _provider = MockProvider(s.fixtures_dir)
        else:
            from signal_core.llm.runner import ClaudeRunnerProvider

            _provider = ClaudeRunnerProvider(
                s.claude_bin,
                s.runner_concurrency,
                s.runner_timeout_s,
                mcp_config=str(s.data_dir / "mcp-signal.json"),
            )
    return _provider


def set_provider(p: LLMProvider | None) -> None:
    global _provider
    _provider = p


@dataclass
class CallResult(Generic[T]):
    output: T
    model: str
    prompt_version: str
    tier: Tier
    cache_hit: bool
    cost_usd: float
    call_id: uuid.UUID | None


def cost_of(res: LLMResult, model_id: str, cfg: BudgetCfg) -> float:
    if res.cost_usd:
        return res.cost_usd
    p = cfg.prices_per_mtok.get(model_id)
    if not p:
        return 0.0
    return (
        res.input_tokens * p.input + res.output_tokens * p.output + res.cache_read_tokens * p.cache_read
    ) / 1e6


def cache_key(task: str, version: str, inputs: dict[str, Any]) -> str:
    blob = json.dumps({"t": task, "v": version, "i": inputs}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


async def call(
    task: str,
    inputs: dict[str, Any],
    *,
    session: AsyncSession,
    tier: Tier | None = None,
    run_id: uuid.UUID | None = None,
    user_initiated: bool = False,
    use_cache: bool = True,
    use_mcp: bool = False,
    messages: list[Msg] | None = None,
    now: datetime | None = None,
) -> CallResult[Any]:
    settings, cfg = get_settings(), get_config()
    tpl = select_prompt(settings.prompts_dir, task)
    schema_model = SCHEMAS[tpl.output_schema] if tpl.output_schema else None
    requested: Tier = tier or tpl.tier

    st = await budget_mod.status(session, cfg.budget, settings.timezone, now)
    try:
        eff_tier = budget_mod.decide_tier(requested, st, cfg.budget, user_initiated)
    except BudgetExceeded as e:
        await _ledger(
            session,
            task=task,
            tier=requested,
            model="-",
            version=tpl.version,
            status="budget_blocked",
            run_id=run_id,
            error=str(e),
            provider=get_provider().name,
        )
        raise
    alias = cfg.budget.models[eff_tier]
    model_id = cfg.budget.model_id(alias)

    key = cache_key(task, tpl.version, inputs)
    if use_cache and messages is None:
        hit = (await session.execute(select(LLMCache).where(LLMCache.key == key))).scalar_one_or_none()
        if hit and hit.expires_at > datetime.now(UTC):
            out = schema_model.model_validate(hit.output) if schema_model else hit.output
            cid = await _ledger(
                session,
                task=task,
                tier=eff_tier,
                model=hit.model,
                version=tpl.version,
                status="cached",
                cache_hit=True,
                run_id=run_id,
                provider=get_provider().name,
            )
            return CallResult(out, hit.model, tpl.version, eff_tier, True, 0.0, cid)

    system, user = tpl.render(inputs, settings.timezone, now)
    json_schema = schema_model.model_json_schema() if schema_model else None
    convo = (messages or []) + [Msg("user", user)]
    provider = get_provider()
    max_tokens = cfg.budget.task_max_tokens.get(task, tpl.max_tokens)

    last_err: str | None = None
    for attempt in (1, 2):
        t0 = time.monotonic()
        try:
            res = await provider.complete(
                system=system,
                messages=convo,
                model=alias,
                max_tokens=max_tokens,
                temperature=tpl.temperature,
                json_schema=json_schema,
                meta={"task": task, "inputs": inputs, "attempt": attempt, "use_mcp": use_mcp},
            )
        except LLMUnavailable as e:
            await _ledger(
                session,
                task=task,
                tier=eff_tier,
                model=model_id,
                version=tpl.version,
                status="error",
                run_id=run_id,
                error=str(e),
                provider=provider.name,
            )
            raise
        except LLMError as e:
            await _ledger(
                session,
                task=task,
                tier=eff_tier,
                model=model_id,
                version=tpl.version,
                status="error",
                run_id=run_id,
                error=str(e),
                provider=provider.name,
            )
            raise
        latency = res.latency_ms or int((time.monotonic() - t0) * 1000)
        cost = cost_of(res, model_id, cfg.budget)
        try:
            if schema_model is None:
                output: Any = res.text
            else:
                if res.data is None:
                    raise LLMInvalidOutput("no structured output")
                output = schema_model.model_validate(res.data)
        except (ValidationError, LLMInvalidOutput) as e:
            last_err = str(e)[:2000]
            await _ledger(
                session,
                task=task,
                tier=eff_tier,
                model=model_id,
                version=tpl.version,
                status="invalid",
                res=res,
                cost=cost,
                latency=latency,
                run_id=run_id,
                error=last_err,
                provider=provider.name,
            )
            convo = [
                *convo,
                Msg("assistant", res.text[:4000]),
                Msg("user", f"Your previous output was invalid:\n{last_err}\nReturn corrected JSON only."),
            ]
            continue
        cid = await _ledger(
            session,
            task=task,
            tier=eff_tier,
            model=model_id,
            version=tpl.version,
            status="ok",
            res=res,
            cost=cost,
            latency=latency,
            run_id=run_id,
            provider=provider.name,
        )
        if use_cache and messages is None:
            await session.execute(delete(LLMCache).where(LLMCache.key == key))
            session.add(
                LLMCache(
                    key=key,
                    task=task,
                    model=model_id,
                    output=output.model_dump(mode="json") if isinstance(output, BaseModel) else output,
                    expires_at=datetime.now(UTC) + timedelta(hours=cfg.budget.cache_ttl_hours),
                )
            )
            await session.flush()
        return CallResult(output, model_id, tpl.version, eff_tier, False, cost, cid)
    raise LLMInvalidOutput(f"{task}: invalid output after repair retry: {last_err}")


async def _ledger(
    session: AsyncSession,
    *,
    task: str,
    tier: str,
    model: str,
    version: str,
    status: str,
    res: LLMResult | None = None,
    cost: float = 0.0,
    latency: int = 0,
    cache_hit: bool = False,
    run_id: uuid.UUID | None = None,
    error: str | None = None,
    provider: str = "",
) -> uuid.UUID:
    """Ledger rows are written in their own transaction so failed/blocked calls are never rolled back
    together with the caller's work (the budget must see every spend)."""
    from signal_core.db.session import session_scope

    row = LLMCall(
        task=task,
        tier=tier,
        model=model,
        prompt_version=version,
        status=status,
        cache_hit=cache_hit,
        input_tokens=res.input_tokens if res else 0,
        output_tokens=res.output_tokens if res else 0,
        cache_read_tokens=res.cache_read_tokens if res else 0,
        cost_usd=cost,
        latency_ms=latency,
        run_id=run_id,
        error=error,
        provider=provider,
    )
    async with session_scope() as s:
        s.add(row)
        await s.flush()
        return row.id
