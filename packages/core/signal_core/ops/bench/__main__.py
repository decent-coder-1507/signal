"""CLI: python -m signal_core.ops.bench run [--json PATH] [--sweep] [--update-cache] | build <step>"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m signal_core.ops.bench")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="recompute all benchmark metrics from fixtures/bench")
    r.add_argument("--json", type=Path, help="write the metrics as JSON here")
    r.add_argument("--sweep", action="store_true", help="also print threshold sweeps (prefilter, clustering)")
    r.add_argument("--update-cache", action="store_true", help="embed cache misses with fastembed")
    r.add_argument("--no-ask", action="store_true", help="skip the Ask retrieval part (needs Postgres)")
    r.add_argument("--baseline", action="store_true", help="measure the pre-ADR-026 engines instead")
    b = sub.add_parser("build", help="sample + label (live mode, scratch DB signal_bench* only)")
    b.add_argument("step")
    sub.add_parser(
        "subset", help="(re)write fixtures/bench/regression.json for tests/integration/test_bench.py"
    )
    a = ap.parse_args(argv)
    if a.cmd == "subset":
        from signal_core.ops.bench.engines import run_regression_writer

        print(json.dumps(asyncio.run(run_regression_writer()), indent=2))
        return 0
    if a.cmd == "build":
        from signal_core.ops.bench.build import run_step

        out = asyncio.run(run_step(a.step))
        print(json.dumps(out, indent=2, default=str)[:4000] if not isinstance(out, str) else out[:2000])
        return 0
    from signal_core.ops.bench.engines import print_report, run_all

    res = asyncio.run(
        run_all(sweep=a.sweep, update_cache=a.update_cache, ask=not a.no_ask, baseline=a.baseline)
    )
    print_report(res)
    if a.json:
        a.json.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
