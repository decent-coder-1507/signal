"""Engine quality for Ops (ADR-026/027): the last `bench run`, persisted as JSON, plus the label spot check.

The benchmark runs in a child process (`python -m signal_core.ops.bench run --json …`) so its numpy work, its
scratch Ask database and its fixture embedder never touch the API process. The result lands in
`data/bench/latest.json`; until a run happens here, the committed snapshot `fixtures/bench/latest.json` is shown.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from signal_core.logging import get_logger
from signal_core.settings import get_settings

log = get_logger("bench")
RUN_TIMEOUT_S = 900


def latest_path() -> Path:
    return get_settings().data_dir / "bench" / "latest.json"


def snapshot_path() -> Path:
    return get_settings().fixtures_dir / "bench" / "latest.json"


def _get(d: dict[str, Any], *path: str) -> float | None:
    x: Any = d
    for k in path:
        if not isinstance(x, dict) or k not in x:
            return None
        x = x[k]
    return float(x) if isinstance(x, int | float) else None


def summarise(res: dict[str, Any]) -> dict[str, Any]:
    """The headline numbers from a `bench run --json` result (same keys as print_report)."""
    metrics = {
        "prefilter": {
            "recall": _get(res, "prefilter", "recall"),
            "precision": _get(res, "prefilter", "precision"),
            "auc": _get(res, "prefilter", "auc"),
            "recall_pop": _get(res, "prefilter", "recall_pop"),
            "pass_rate_pop": _get(res, "prefilter", "pass_rate_pop"),
        },
        "cluster": {
            "precision": _get(res, "cluster", "precision"),
            "recall": _get(res, "cluster", "recall"),
            "f1": _get(res, "cluster", "f1"),
        },
        "ranking": {
            "ndcg@10": _get(res, "ranking", "test", "ndcg@10"),
            "p@7": _get(res, "ranking", "test", "p@7"),
        },
        "ask": {
            "recall@5": _get(res, "ask", "recall@5"),
            "recall@1": _get(res, "ask", "recall@1"),
            "mrr": _get(res, "ask", "mrr"),
        }
        if "ask" in res
        else None,
    }
    return {"variant": res.get("variant"), "labels": res.get("labels"), "metrics": metrics}


def _load(p: Path, origin: str) -> dict[str, Any] | None:
    if not p.exists():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if "result" not in doc:  # a raw `bench run --json` file
        doc = {"result": doc, "finished_at": None, "duration_s": None}
    return {**summarise(doc["result"]), **{k: v for k, v in doc.items() if k != "result"}, "origin": origin}


def load_latest() -> dict[str, Any] | None:
    return _load(latest_path(), "local") or _load(snapshot_path(), "snapshot")


def spotcheck() -> dict[str, Any]:
    """Counts the y/n column of fixtures/bench/SPOTCHECK.md (the user's agreement with Claude's labels)."""
    p = get_settings().fixtures_dir / "bench" / "SPOTCHECK.md"
    if not p.exists():
        return {"rows": 0, "agree": 0, "disagree": 0, "reviewed": False}
    rows = agree = disagree = 0
    for line in p.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or not re.fullmatch(r"\d+", cells[0]):
            continue
        rows += 1
        v = cells[-1].lower()
        if v.startswith("y"):
            agree += 1
        elif v.startswith("n"):
            disagree += 1
    return {"rows": rows, "agree": agree, "disagree": disagree, "reviewed": agree + disagree > 0}


class BenchRunner:
    """At most one background run per process; state is read by GET /ops/bench."""

    def __init__(self) -> None:
        self.task: asyncio.Task[None] | None = None
        self.started_at: datetime | None = None
        self.error: str | None = None

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    def command(self, out: Path) -> list[str]:
        return [sys.executable, "-m", "signal_core.ops.bench", "run", "--json", str(out)]

    def start(self) -> bool:
        if self.running:
            return False
        self.error, self.started_at = None, datetime.now(UTC)
        self.task = asyncio.create_task(self._run())
        return True

    async def _run(self) -> None:
        dest = latest_path()
        dest.parent.mkdir(parents=True, exist_ok=True)
        raw = dest.with_name("run-raw.json")
        t0 = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.command(raw), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
            )
            out, _ = await asyncio.wait_for(proc.communicate(), RUN_TIMEOUT_S)
            if proc.returncode != 0 or not raw.exists():
                tail = out.decode(errors="replace").strip().splitlines()[-3:]
                raise RuntimeError(f"bench exited {proc.returncode}: {' / '.join(tail)[:400]}")
            doc = {
                "result": json.loads(raw.read_text(encoding="utf-8")),
                "finished_at": datetime.now(UTC).isoformat(),
                "duration_s": round(time.monotonic() - t0, 1),
                "mode": get_settings().mode,
            }
            dest.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            raw.unlink(missing_ok=True)
        except Exception as e:
            self.error = f"{e.__class__.__name__}: {e}"[:500]
            log.warning("bench_run_failed", error=self.error)


runner = BenchRunner()


def status() -> dict[str, Any]:
    return {
        "latest": load_latest(),
        "running": runner.running,
        "started_at": runner.started_at.isoformat() if runner.started_at else None,
        "error": runner.error,
        "spotcheck": spotcheck(),
    }
