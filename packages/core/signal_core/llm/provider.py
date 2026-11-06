"""Provider interfaces (§15.1). Implementations: ClaudeRunnerProvider (live, ADR-001), MockProvider."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Tier = Literal["fast", "balanced", "deep"]


@dataclass
class Msg:
    role: Literal["user", "assistant"]
    content: str


@dataclass
class LLMResult:
    text: str
    data: Any | None  # parsed structured output when a json_schema was given
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float | None = None  # provider-reported notional cost, if any
    latency_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


class LLMError(RuntimeError):
    pass


class LLMUnavailable(LLMError):
    """Provider cannot serve requests (auth expired, CLI missing, rate-limited). Callers degrade (§16.4)."""


class LLMInvalidOutput(LLMError):
    pass


class BudgetExceeded(LLMError):
    pass


class LLMProvider(Protocol):
    name: str

    async def complete(
        self,
        *,
        system: str,
        messages: list[Msg],
        model: str,
        max_tokens: int,
        temperature: float,
        json_schema: dict[str, Any] | None = None,
        cache_prefix: bool = True,
        meta: dict[str, Any] | None = None,
    ) -> LLMResult: ...


class EmbeddingProvider(Protocol):
    name: str
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
