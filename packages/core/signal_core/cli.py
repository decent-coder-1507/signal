"""`python -m signal_core.cli <command>` — DB + data maintenance used by scripts/dev.py."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from signal_core.settings import REPO_ROOT, get_settings


def migrate(url: str | None = None) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "packages/core/signal_core/db/migrations"))
    cfg.set_main_option("sqlalchemy.url", url or get_settings().database_url)
    command.upgrade(cfg, "head")


async def ensure_database(url: str) -> None:
    u = make_url(url)
    admin = create_async_engine(u.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as c:
        exists = (
            await c.execute(text("select 1 from pg_database where datname=:n"), {"n": u.database})
        ).first()
        if not exists:
            await c.execute(text(f'CREATE DATABASE "{u.database}"'))
    await admin.dispose()
    eng = create_async_engine(url)
    async with eng.begin() as c:
        await c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    await eng.dispose()


async def reset(url: str) -> None:
    from signal_core.db import models  # noqa: F401
    from signal_core.db.base import Base

    eng = create_async_engine(url)
    names = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
    async with eng.begin() as c:
        await c.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    await eng.dispose()


async def seed(with_fixtures: bool = False) -> dict[str, Any]:
    from signal_core.config import get_config
    from signal_core.db.session import dispose, session_scope
    from signal_core.services.seed import seed_all

    s = get_settings()
    async with session_scope() as db:
        out = await seed_all(db, get_config(), s.admin_email, s.admin_password, s.timezone)
    if with_fixtures:
        from signal_core.demo import load_demo

        out["demo"] = await load_demo()
    await dispose()
    return out


async def runner_check() -> dict[str, Any]:
    from signal_core.llm.provider import Msg
    from signal_core.llm.runner import ClaudeRunnerProvider

    p = ClaudeRunnerProvider(get_settings().claude_bin, 1, 120)
    try:
        r = await p.complete(
            system="Reply with JSON only.",
            messages=[Msg("user", "Health check. Put the single word ok in the answer field.")],
            model="haiku",
            max_tokens=20,
            temperature=0,
            json_schema={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        )
        return {"ok": True, "data": r.data, "latency_ms": r.latency_ms, "notional_cost_usd": r.cost_usd}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="signal")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    sub.add_parser("ensure-db")
    sub.add_parser("reset-db")
    sp = sub.add_parser("seed")
    sp.add_argument("--demo", action="store_true", help="also load recorded fixture data (mock demo)")
    sub.add_parser("runner-check")
    sub.add_parser("check-config")
    sub.add_parser("mcp-config")
    args = ap.parse_args(argv)
    url = get_settings().database_url
    if args.cmd == "ensure-db":
        asyncio.run(ensure_database(url))
    elif args.cmd == "migrate":
        migrate(url)
    elif args.cmd == "reset-db":
        asyncio.run(reset(url))
    elif args.cmd == "seed":
        print(json.dumps(asyncio.run(seed(args.demo)), default=str))
    elif args.cmd == "runner-check":
        res = asyncio.run(runner_check())
        print(json.dumps(res, indent=2, default=str))
        return 0 if res["ok"] else 1
    elif args.cmd == "mcp-config":
        from signal_core.mcp.server import write_config

        print(write_config())
    elif args.cmd == "check-config":
        from signal_core.config import ConfigError, load_config

        try:
            load_config(get_settings().config_dir)
        except ConfigError as e:
            print(e, file=sys.stderr)
            return 2
        print("config ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
