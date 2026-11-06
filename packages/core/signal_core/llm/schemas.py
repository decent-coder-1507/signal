"""Pydantic output schemas for every LLM task (§15.5). Registered by name for prompt front-matter."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Out(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Ping(Out):
    """Health-check task: proves the router → provider → ledger path works."""

    answer: str
    ok: bool = True


SCHEMAS: dict[str, type[BaseModel]] = {}


def register(*models: type[BaseModel]) -> None:
    for m in models:
        SCHEMAS[m.__name__] = m


register(Ping)

# Task schemas are added per milestone in signal_core.llm.task_schemas and registered on import.
from signal_core.llm import task_schemas  # noqa: E402,F401

__all__ = ["SCHEMAS", "Field", "Literal", "Out", "Ping", "register"]
