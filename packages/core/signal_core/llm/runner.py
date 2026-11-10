"""Claude Runner: LLM provider backed by the local Claude Code CLI in headless mode (ADR-001).

No API keys. The CLI authenticates with the user's own subscription login. We never pass --bare
(bare mode ignores OAuth and requires ANTHROPIC_API_KEY).

Verified against CLI 2.1.319 (2026-11-06): -p, --output-format json, --json-schema, --model,
--system-prompt-file, --tools "", --strict-mcp-config, --mcp-config, --no-session-persistence,
--setting-sources. Result JSON keys: type, subtype, is_error, result, structured_output?,
total_cost_usd, usage, modelUsage, session_id. NOTE: an auth failure returned subtype="success"
with is_error=true, so is_error is authoritative.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from signal_core.llm.provider import LLMError, LLMInvalidOutput, LLMResult, LLMUnavailable, Msg

AUTH_PATTERNS = re.compile(r"authenticat|oauth|log ?in|credential|401|unauthori", re.I)
LIMIT_PATTERNS = re.compile(r"usage limit|rate limit|429|overloaded|quota", re.I)


def flatten_messages(messages: list[Msg]) -> str:
    if len(messages) == 1:
        return messages[0].content
    parts = [f"<{m.role}>\n{m.content}\n</{m.role}>" for m in messages]
    return (
        "Conversation so far:\n\n"
        + "\n\n".join(parts)
        + "\n\nRespond as the assistant to the last user turn."
    )


def parse_json_text(text: str) -> Any:
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    return json.loads(t)


def build_args(
    bin_path: str,
    *,
    model: str,
    system_file: str,
    json_schema: dict[str, Any] | None,
    mcp_config: str | None,
) -> list[str]:
    args = [
        bin_path,
        "-p",
        "--output-format",
        "json",
        "--model",
        model,
        "--system-prompt-file",
        system_file,
        "--no-session-persistence",
        "--setting-sources",
        "",
        "--strict-mcp-config",
    ]
    if mcp_config:
        # Ask SIGNAL: Claude may use SIGNAL's read-only MCP tools, nothing else.
        args += [
            "--mcp-config",
            mcp_config,
            "--tools",
            "",
            "--permission-mode",
            "dontAsk",
            "--allowedTools",
            "mcp__signal",
        ]
    else:
        args += ["--tools", ""]
    if json_schema is not None:
        args += ["--json-schema", json.dumps(json_schema, separators=(",", ":"))]
    return args


def interpret(payload: dict[str, Any], model: str, latency_ms: int, want_json: bool) -> LLMResult:
    if payload.get("is_error") or str(payload.get("subtype", "")).startswith("error"):
        msg = str(payload.get("result") or payload.get("errors") or payload.get("subtype"))
        if AUTH_PATTERNS.search(msg):
            raise LLMUnavailable(f"Claude CLI not authenticated: {msg}. Run `claude` then /login.")
        if LIMIT_PATTERNS.search(msg):
            raise LLMUnavailable(f"Claude subscription limit reached: {msg}")
        raise LLMError(f"Claude CLI error: {msg}")
    text = str(payload.get("result") or "")
    data: Any = None
    if want_json:
        data = payload.get("structured_output")
        if data is None:
            try:
                data = parse_json_text(text)
            except (json.JSONDecodeError, ValueError) as e:
                raise LLMInvalidOutput(f"runner returned non-JSON output: {text[:200]}") from e
    usage = payload.get("usage") or {}
    return LLMResult(
        text=text if not want_json else json.dumps(data),
        data=data,
        model=model,
        input_tokens=int(usage.get("input_tokens", 0)) + int(usage.get("cache_creation_input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        cache_read_tokens=int(usage.get("cache_read_input_tokens", 0)),
        cost_usd=float(payload.get("total_cost_usd") or 0.0),
        latency_ms=latency_ms,
        raw={k: payload.get(k) for k in ("session_id", "num_turns", "subtype", "modelUsage")},
    )


class ClaudeRunnerProvider:
    name = "claude_runner"

    def __init__(
        self,
        claude_bin: str = "claude",
        concurrency: int = 2,
        timeout_s: int = 180,
        mcp_config: str | None = None,
    ) -> None:
        self.claude_bin = claude_bin
        self.timeout_s = timeout_s
        self.mcp_config = mcp_config
        self._sem = asyncio.Semaphore(concurrency)
        self.healthy: bool | None = None
        self.last_error: str | None = None

    def _resolve_bin(self) -> str:
        found = shutil.which(self.claude_bin)
        if not found:
            raise LLMUnavailable(f"Claude Code CLI '{self.claude_bin}' not found on PATH")
        return found

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
        # max_tokens/temperature have no CLI flag; prompts state length limits instead (ADR-001).
        if not any(m.content.strip() for m in messages):
            task = (meta or {}).get("task", "?")
            raise LLMError(f"empty user prompt for task '{task}' (the prompt template rendered nothing)")
        bin_path = self._resolve_bin()
        use_mcp = bool(meta and meta.get("use_mcp") and self.mcp_config)
        fd, sys_path = tempfile.mkstemp(prefix="signal-sys-", suffix=".md")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(system)
            args = build_args(
                bin_path,
                model=model,
                system_file=sys_path,
                json_schema=json_schema,
                mcp_config=self.mcp_config if use_mcp else None,
            )
            async with self._sem:
                t0 = time.monotonic()
                proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=tempfile.gettempdir(),  # never run inside the repo: no CLAUDE.md pickup
                )
                try:
                    out, err = await asyncio.wait_for(
                        proc.communicate(flatten_messages(messages).encode("utf-8")), self.timeout_s
                    )
                except TimeoutError as e:
                    proc.kill()
                    raise LLMError(f"Claude CLI timed out after {self.timeout_s}s") from e
                latency = int((time.monotonic() - t0) * 1000)
            try:
                payload = json.loads(out.decode("utf-8", "replace"))
            except json.JSONDecodeError as e:
                msg = (err or out).decode("utf-8", "replace")[:500]
                if AUTH_PATTERNS.search(msg):
                    self.healthy, self.last_error = False, msg
                    raise LLMUnavailable(msg) from e
                raise LLMError(f"Claude CLI produced no JSON (exit {proc.returncode}): {msg}") from e
            try:
                res = interpret(payload, model, latency, json_schema is not None)
            except LLMUnavailable as e:
                self.healthy, self.last_error = False, str(e)
                raise
            self.healthy, self.last_error = True, None
            return res
        finally:
            Path(sys_path).unlink(missing_ok=True)
