"""Versioned prompt templates (§15.4): prompts/<task>/<version>.md with YAML front-matter.

Body format: system template, then a line `---user---`, then the user template (Jinja2).
Every system prompt is prefixed with the shared preamble: date, time zone, truthfulness rules.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import frontmatter
from jinja2 import Environment, StrictUndefined

from signal_core.llm.provider import Tier

PREAMBLE = """Today is {today} ({tz}).
You work inside SIGNAL, a personal tech-intelligence tool for one software & AI engineer.
Truthfulness rules (non-negotiable):
- Never invent facts, numbers, names, quotes, dates or URLs. Use only the material provided in this request.
- Every factual statement must be traceable to a provided source id; cite it exactly as instructed.
- Personal facts about the user may come only from the provided raw-material entries or answers.
- If the material does not support an answer, say you don't know or that it is not in the sources.
- Mark uncertainty explicitly (single source, unconfirmed, company claim, self-reported benchmark).
Return only what the output format asks for, with no commentary.
"""

_env = Environment(undefined=StrictUndefined, autoescape=False, trim_blocks=True, lstrip_blocks=True)
_env.filters["tojson_compact"] = lambda v: __import__("json").dumps(v, ensure_ascii=False, default=str)


@dataclass
class PromptTemplate:
    task: str
    version: str
    tier: Tier
    output_schema: str | None
    temperature: float
    max_tokens: int
    system_tpl: str
    user_tpl: str
    traffic_split: float = 1.0
    changelog: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def render(
        self, inputs: dict[str, Any], tz: str = "Asia/Kolkata", now: datetime | None = None
    ) -> tuple[str, str]:
        now = now or datetime.now(ZoneInfo(tz))
        pre = PREAMBLE.format(today=now.strftime("%A %d %B %Y"), tz=tz)
        system = pre + "\n" + _env.from_string(self.system_tpl).render(**inputs)
        user = _env.from_string(self.user_tpl).render(**inputs)
        return system.strip(), user.strip()


class PromptNotFound(LookupError):
    pass


def _parse(path: Path) -> PromptTemplate:
    post = frontmatter.load(str(path))
    m: dict[str, Any] = dict(post.metadata)
    body = post.content
    if m.get("tier", "balanced") not in ("fast", "balanced", "deep"):
        raise ValueError(f"{path}: tier must be fast|balanced|deep")
    if "---user---" not in body:
        raise ValueError(f"{path}: missing '---user---' separator")
    sys_part, user_part = body.split("---user---", 1)
    return PromptTemplate(
        task=str(m["task"]),
        version=str(m["version"]),
        tier=m.get("tier", "balanced"),
        output_schema=m.get("output_schema"),
        temperature=float(m.get("temperature", 0.3)),
        max_tokens=int(m.get("max_tokens", 2000)),
        system_tpl=sys_part.strip(),
        user_tpl=user_part.strip(),
        traffic_split=float(m.get("traffic_split", 1.0)),
        changelog=str(m.get("changelog", "")),
        meta=dict(m),
    )


@lru_cache(maxsize=256)
def load_versions(prompts_dir: str, task: str) -> tuple[PromptTemplate, ...]:
    d = Path(prompts_dir) / task
    if not d.is_dir():
        raise PromptNotFound(f"no prompt directory for task '{task}' in {prompts_dir}")
    versions = sorted((_parse(p) for p in d.glob("*.md")), key=lambda t: t.version)
    if not versions:
        raise PromptNotFound(f"no prompt versions for task '{task}'")
    return tuple(versions)


def select(prompts_dir: Path, task: str, rng: random.Random | None = None) -> PromptTemplate:
    """Latest version wins, unless it declares traffic_split < 1 (A/B against the previous one)."""
    versions = load_versions(str(prompts_dir), task)
    latest = versions[-1]
    if latest.traffic_split < 1.0 and len(versions) > 1:
        r = (rng or random).random()
        return latest if r < latest.traffic_split else versions[-2]
    return latest
