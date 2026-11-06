"""MockProvider (§15.1): deterministic outputs keyed by task + input hash.

Lookup order: fixtures/llm/<task>/<hash12>.json (golden file) → registered generator for the task.
Generators are pure functions of the inputs and obey the truthfulness rules (they only ever quote
text that exists in the inputs), so mock mode exercises the same validators as live mode.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from signal_core.llm.provider import LLMError, LLMResult, Msg

Generator = Callable[[dict[str, Any]], Any]
GENERATORS: dict[str, Generator] = {}


def mock_generator(task: str) -> Callable[[Generator], Generator]:
    def deco(fn: Generator) -> Generator:
        GENERATORS[task] = fn
        return fn

    return deco


def input_hash(task: str, inputs: dict[str, Any]) -> str:
    blob = json.dumps({"task": task, "inputs": inputs}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


class MockProvider:
    name = "mock"

    def __init__(self, fixtures_dir: Path | None = None) -> None:
        self.fixtures_dir = fixtures_dir
        self.calls: list[dict[str, Any]] = []
        self.fail_with: Exception | None = None  # tests can simulate outages

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
    ) -> LLMResult:
        if self.fail_with:
            raise self.fail_with
        meta = meta or {}
        task = str(meta.get("task", "unknown"))
        inputs = meta.get("inputs", {})
        self.calls.append({"task": task, "model": model, "inputs": inputs, "attempt": meta.get("attempt", 1)})
        data = self._golden(task, inputs)
        if data is None:
            # Ensure generators are registered (import side effect).
            from signal_core.llm import mock_generators  # noqa: F401

            gen = GENERATORS.get(task)
            if gen is None:
                raise LLMError(f"MockProvider: no golden file or generator for task '{task}'")
            data = gen(inputs)
        text = json.dumps(data, ensure_ascii=False) if json_schema is not None else str(data)
        prompt_len = len(system) + sum(len(m.content) for m in messages)
        return LLMResult(
            text=text,
            data=data if json_schema is not None else None,
            model=model,
            input_tokens=prompt_len // 4,
            output_tokens=len(text) // 4,
            latency_ms=1,
        )

    def _golden(self, task: str, inputs: dict[str, Any]) -> Any | None:
        if not self.fixtures_dir:
            return None
        path = self.fixtures_dir / "llm" / task / f"{input_hash(task, inputs)[:12]}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None
