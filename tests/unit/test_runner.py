import asyncio
import json
from typing import Any

import pytest

from signal_core.llm import runner
from signal_core.llm.provider import LLMError, LLMInvalidOutput, LLMUnavailable, Msg
from signal_core.llm.runner import ClaudeRunnerProvider, build_args, flatten_messages, interpret


def test_args_never_use_bare_and_disable_tools() -> None:
    args = build_args(
        "claude", model="haiku", system_file="s.md", json_schema={"type": "object"}, mcp_config=None
    )
    assert "--bare" not in args
    assert args[args.index("--tools") + 1] == ""
    assert "--no-session-persistence" in args and "--strict-mcp-config" in args
    assert json.loads(args[args.index("--json-schema") + 1]) == {"type": "object"}


def test_mcp_args_only_allow_signal_tools() -> None:
    args = build_args("claude", model="sonnet", system_file="s.md", json_schema=None, mcp_config="m.json")
    assert args[args.index("--mcp-config") + 1] == "m.json"
    assert args[args.index("--allowedTools") + 1] == "mcp__signal"


def test_is_error_is_authoritative_even_with_success_subtype() -> None:
    payload = {
        "subtype": "success",
        "is_error": True,
        "result": "Failed to authenticate: OAuth session expired",
    }
    with pytest.raises(LLMUnavailable, match="/login"):
        interpret(payload, "haiku", 10, want_json=True)


def test_limits_map_to_unavailable_and_other_errors_to_llmerror() -> None:
    with pytest.raises(LLMUnavailable):
        interpret({"is_error": True, "result": "Claude usage limit reached"}, "m", 1, False)
    with pytest.raises(LLMError):
        interpret({"is_error": True, "result": "something odd"}, "m", 1, False)


def test_structured_output_preferred_then_result_text() -> None:
    ok = {
        "is_error": False,
        "result": "",
        "structured_output": {"answer": "x"},
        "total_cost_usd": 0.001,
        "usage": {"input_tokens": 10, "output_tokens": 3, "cache_read_input_tokens": 5},
    }
    r = interpret(ok, "haiku", 5, True)
    assert r.data == {"answer": "x"} and r.cost_usd == 0.001 and r.cache_read_tokens == 5
    fenced = {"is_error": False, "result": '```json\n{"answer": "y"}\n```'}
    assert interpret(fenced, "haiku", 5, True).data == {"answer": "y"}
    with pytest.raises(LLMInvalidOutput):
        interpret({"is_error": False, "result": "not json"}, "haiku", 5, True)


def test_flatten_multi_turn() -> None:
    assert flatten_messages([Msg("user", "hi")]) == "hi"
    s = flatten_messages([Msg("user", "a"), Msg("assistant", "b"), Msg("user", "c")])
    assert "<assistant>\nb\n</assistant>" in s and s.endswith("last user turn.")


class FakeProc:
    def __init__(self, out: bytes, rc: int = 0) -> None:
        self._out, self.returncode = out, rc
        self.stdin_data = b""

    async def communicate(self, data: bytes) -> tuple[bytes, bytes]:
        self.stdin_data = data
        return self._out, b""

    def kill(self) -> None: ...


async def test_provider_end_to_end_with_fake_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_exec(*args: str, **kw: Any) -> FakeProc:
        seen["args"], seen["cwd"] = args, kw.get("cwd")
        p = FakeProc(
            json.dumps(
                {
                    "is_error": False,
                    "result": "",
                    "structured_output": {"answer": "pong"},
                    "usage": {"input_tokens": 4, "output_tokens": 2},
                }
            ).encode()
        )
        seen["proc"] = p
        return p

    monkeypatch.setattr(runner.shutil, "which", lambda b: "C:/fake/claude.exe")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    prov = ClaudeRunnerProvider()
    r = await prov.complete(
        system="sys",
        messages=[Msg("user", "ping")],
        model="haiku",
        max_tokens=10,
        temperature=0,
        json_schema={"type": "object"},
    )
    assert r.data == {"answer": "pong"} and prov.healthy is True
    assert seen["proc"].stdin_data == b"ping"
    assert "--system-prompt-file" in seen["args"]
    assert "my software tools" not in str(seen["cwd"]).lower()  # never runs inside the repo


async def test_provider_marks_unhealthy_on_auth_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_exec(*args: str, **kw: Any) -> FakeProc:
        return FakeProc(
            json.dumps(
                {
                    "subtype": "success",
                    "is_error": True,
                    "result": "Failed to authenticate: OAuth session expired",
                }
            ).encode(),
            rc=1,
        )

    monkeypatch.setattr(runner.shutil, "which", lambda b: "C:/fake/claude.exe")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    prov = ClaudeRunnerProvider()
    with pytest.raises(LLMUnavailable):
        await prov.complete(system="", messages=[Msg("user", "x")], model="m", max_tokens=1, temperature=0)
    assert prov.healthy is False and "OAuth" in (prov.last_error or "")


async def test_provider_unavailable_when_cli_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner.shutil, "which", lambda b: None)
    with pytest.raises(LLMUnavailable):
        await ClaudeRunnerProvider().complete(
            system="", messages=[Msg("user", "x")], model="m", max_tokens=1, temperature=0
        )
