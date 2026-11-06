"""Deterministic mock outputs per task. Only ever echo/quote text that exists in the inputs."""

from __future__ import annotations

from typing import Any

from signal_core.llm.mock import mock_generator


@mock_generator("ping")
def ping(inputs: dict[str, Any]) -> dict[str, Any]:
    return {"answer": f"pong: {inputs.get('message', '')}", "ok": True}
