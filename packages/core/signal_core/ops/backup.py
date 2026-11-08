"""Backups & restore (§16.5): nightly compressed pg_dump (custom format), 14 daily + 8 weekly retained, assets folder
archived alongside; a restore drill restores the latest dump into a scratch database and compares row counts.

pg_dump/pg_restore are found in this order: on PATH (VPS/worker image) → `docker exec` into the db container →
via the Alpine WSL distro's Docker (Windows host, ADR-002). CLI: `python -m signal_core.ops.backup backup|restore|drill`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

from signal_core.settings import get_settings

DAILY_KEEP, WEEKLY_KEEP = 14, 8
CONTAINER = os.environ.get("SIGNAL_DB_CONTAINER", "signal-db-1")


@dataclass
class BackupResult:
    dump: Path
    assets: Path | None
    size_bytes: int
    pruned: list[str]


def _pg_cmd(tool: str, args: list[str], db_url: str) -> list[str]:
    """Command line that runs pg_dump/pg_restore/psql against the configured database."""
    u = make_url(db_url)
    if shutil.which(tool):
        return [
            tool,
            f"--dbname=postgresql://{u.username}:{u.password}@{u.host}:{u.port}/{u.database}",
            *args,
        ]
    inner = [tool, "-U", str(u.username), "-d", str(u.database), *args]
    if shutil.which("docker"):
        return ["docker", "exec", "-i", CONTAINER, *inner]
    return [
        "wsl",
        "-d",
        os.environ.get("SIGNAL_WSL_DISTRO", "Alpine"),
        "--",
        "docker",
        "exec",
        "-i",
        CONTAINER,
        *inner,
    ]


def _run(cmd: list[str], stdin: bytes | None = None) -> bytes:
    p = subprocess.run(cmd, input=stdin, capture_output=True, check=False)
    if p.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:4])}… failed: {p.stderr.decode('utf-8', 'replace')[:500]}")
    return p.stdout


def backup(now: datetime | None = None, root: Path | None = None, db_url: str | None = None) -> BackupResult:
    s = get_settings()
    now = now or datetime.now(UTC)
    root = root or s.data_dir / "backups"
    daily = root / "daily"
    weekly = root / "weekly"
    daily.mkdir(parents=True, exist_ok=True)
    weekly.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%d-%H%M%S")
    data = _run(
        _pg_cmd("pg_dump", ["-Fc", "-Z", "6", "--no-owner"], db_url or s.database_url.replace("+asyncpg", ""))
    )
    dump = daily / f"signal-{stamp}.dump"
    dump.write_bytes(data)
    assets = None
    adir = s.data_dir / "assets"
    if adir.exists() and any(adir.rglob("*")):
        assets = daily / f"assets-{stamp}.tar.gz"
        with tarfile.open(assets, "w:gz") as tar:
            tar.add(adir, arcname="assets")
    if now.weekday() == 6:  # Sunday copy goes to the weekly set
        shutil.copy2(dump, weekly / dump.name)
        if assets:
            shutil.copy2(assets, weekly / assets.name)
    pruned = _prune(daily, DAILY_KEEP) + _prune(weekly, WEEKLY_KEEP)
    if s.backup_s3_url:
        _offsite(dump, s.backup_s3_url)
    return BackupResult(dump, assets, len(data), pruned)


def _prune(folder: Path, keep: int) -> list[str]:
    dumps = sorted(folder.glob("signal-*.dump"))
    gone = []
    for d in dumps[:-keep] if len(dumps) > keep else []:
        stamp = d.stem.removeprefix("signal-")
        for f in (d, folder / f"assets-{stamp}.tar.gz"):
            if f.exists():
                f.unlink()
                gone.append(f.name)
    return gone


def _offsite(path: Path, url: str) -> None:
    """Optional S3-compatible copy via rclone (`SIGNAL_BACKUP_S3_URL=rclone:remote:bucket/path`)."""
    if url.startswith("rclone:") and shutil.which("rclone"):
        _run(["rclone", "copy", str(path), url.removeprefix("rclone:")])


def latest_dump(root: Path | None = None) -> Path:
    root = root or get_settings().data_dir / "backups"
    dumps = sorted((root / "daily").glob("signal-*.dump")) + sorted((root / "weekly").glob("signal-*.dump"))
    if not dumps:
        raise FileNotFoundError("no backups found")
    return max(dumps, key=lambda p: p.stem)


def restore(dump: Path, target_db_url: str, create: bool = True) -> None:
    """Restore a dump into the target database (dropping existing objects). Used by the drill and real restores."""
    u = make_url(target_db_url.replace("+asyncpg", ""))
    if create:
        admin = str(u.set(database="postgres"))
        q = f"select 1 from pg_database where datname='{u.database}';"
        exists = _run(_pg_cmd("psql", ["-tA", "-f", "-"], admin), stdin=q.encode())
        if not exists.strip():
            _run(_pg_cmd("psql", ["-f", "-"], admin), stdin=f'CREATE DATABASE "{u.database}";'.encode())
    _run(
        _pg_cmd("pg_restore", ["--clean", "--if-exists", "--no-owner", "--exit-on-error"], str(u)),
        stdin=dump.read_bytes(),
    )


def row_counts(db_url: str, tables: list[str]) -> dict[str, int]:
    # SQL goes through stdin: the WSL hop passes argv through a shell that would mangle quotes, * and |.
    sql = " union all ".join(f"select '{t}', count(*) from \"{t}\"" for t in tables) + ";"
    out = _run(
        _pg_cmd("psql", ["-tA", "-F", ",", "-f", "-"], db_url.replace("+asyncpg", "")), stdin=sql.encode()
    ).decode()
    return {ln.split(",")[0]: int(ln.split(",")[1]) for ln in out.strip().splitlines() if "," in ln}


def drill(db_url: str | None = None, scratch_db: str = "signal_restore_drill") -> dict[str, Any]:
    """Restore drill (§16.5, M10): backup → restore into a scratch DB → compare row counts of key tables."""
    s = get_settings()
    src = (db_url or s.database_url).replace("+asyncpg", "")
    res = backup(db_url=src)
    target = str(make_url(src).set(database=scratch_db))
    t0 = datetime.now(UTC)
    restore(res.dump, target)
    seconds = (datetime.now(UTC) - t0).total_seconds()
    tables = [
        "items",
        "stories",
        "story_insights",
        "briefs",
        "drafts",
        "ideas",
        "cards",
        "llm_calls",
        "sources",
    ]
    a, b = row_counts(src, tables), row_counts(target, tables)
    return {
        "dump": str(res.dump),
        "size_bytes": res.size_bytes,
        "restore_seconds": round(seconds, 1),
        "source_counts": a,
        "restored_counts": b,
        "match": a == b,
    }


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "backup"
    if cmd == "backup":
        r = backup()
        print(f"backup ok: {r.dump} ({r.size_bytes} bytes); pruned {len(r.pruned)}")
    elif cmd == "restore":
        target = sys.argv[3] if len(sys.argv) > 3 else get_settings().database_url
        restore(Path(sys.argv[2]) if len(sys.argv) > 2 else latest_dump(), target)
        print("restore ok")
    elif cmd == "drill":
        import json

        print(json.dumps(drill(), indent=2))
    else:
        sys.exit("usage: backup | restore [dump] [target_url] | drill")
