"""Budget guard (§15.3). Spend = notional API-equivalent cost from the llm_calls ledger (ADR-001)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.config.schemas import BudgetCfg
from signal_core.db.models import LLMCall
from signal_core.llm.provider import BudgetExceeded, Tier

State = Literal["ok", "soft", "hard"]


@dataclass
class BudgetStatus:
    spent_usd: float
    limit_usd: float
    state: State
    calls_today: int
    projected_usd: float

    @property
    def pct(self) -> float:
        return 100.0 * self.spent_usd / self.limit_usd if self.limit_usd else 0.0

    @property
    def insight_cap(self) -> int | None:
        """Soft limit: reduce insights to top 15 (§15.3)."""
        return 15 if self.state != "ok" else None


def month_start(now: datetime, tz: str) -> datetime:
    local = now.astimezone(ZoneInfo(tz))
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def day_start(now: datetime, tz: str) -> datetime:
    local = now.astimezone(ZoneInfo(tz))
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


async def status(session: AsyncSession, cfg: BudgetCfg, tz: str, now: datetime | None = None) -> BudgetStatus:
    now = now or datetime.now(UTC)
    ms, ds = month_start(now, tz), day_start(now, tz)
    spent = (
        await session.execute(
            select(func.coalesce(func.sum(LLMCall.cost_usd), 0.0)).where(LLMCall.created_at >= ms)
        )
    ).scalar_one()
    calls_today = (
        await session.execute(
            select(func.count())
            .select_from(LLMCall)
            .where(LLMCall.created_at >= ds, LLMCall.cache_hit.is_(False), LLMCall.status != "budget_blocked")
        )
    ).scalar_one()
    elapsed_days = max((now - ms) / timedelta(days=1), 0.5)
    next_month = (ms.astimezone(ZoneInfo(tz)).replace(day=28) + timedelta(days=4)).replace(day=1)
    month_days = (next_month.astimezone(UTC) - ms) / timedelta(days=1)
    projected = float(spent) / elapsed_days * month_days
    # The monthly budget set in onboarding/Settings overrides config/budget.yaml.
    from signal_core.services.settings_store import get_setting

    limit = float(await get_setting(session, "budget_monthly_usd", cfg.monthly_usd) or cfg.monthly_usd)
    st: State = "hard" if spent >= limit else "soft" if spent >= limit * cfg.soft_limit_pct / 100 else "ok"
    return BudgetStatus(float(spent), limit, st, int(calls_today), projected)


def decide_tier(requested: Tier, st: BudgetStatus, cfg: BudgetCfg, user_initiated: bool) -> Tier:
    """Apply degrade paths. Raises BudgetExceeded when the call must not run."""
    if st.calls_today >= cfg.max_calls_per_day and not user_initiated:
        raise BudgetExceeded(f"daily call cap reached ({cfg.max_calls_per_day})")
    if st.state == "ok":
        return requested
    if st.state == "soft":
        return "balanced" if requested == "deep" else requested
    # hard: only fast tier + user-initiated actions
    if user_initiated:
        return "balanced" if requested == "deep" else requested
    if requested == "fast":
        return "fast"
    raise BudgetExceeded(f"monthly budget exhausted (${st.spent_usd:.2f} / ${st.limit_usd:.2f})")
