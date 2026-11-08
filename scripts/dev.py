#!/usr/bin/env python3
"""Cross-platform task runner (ADR-003). Usage: python scripts/dev.py <command>

setup        uv sync + pnpm install + Playwright Chromium
infra        start Postgres+pgvector (:5442) and Redis (:6390) in WSL/host Docker (project "signal")
migrate      alembic upgrade head        seed [--demo]   load config (+ fixture demo data)
up           infra + migrate + api, worker, scheduler, web (Ctrl+C stops)
mock         `up` with SIGNAL_MODE=mock and demo data
api|worker|scheduler|web   run one service in the foreground
lint         ruff + mypy + eslint + tsc
test         lint + pytest (mock) + vitest
e2e          reset e2e db, seed demo, Playwright
check        test + e2e (milestone gate)
runner-check one real headless Claude call through the Claude Runner (uses your subscription)
backup | restore <file>
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
IS_WIN = os.name == "nt"
UV = [sys.executable, "-m", "uv"] if shutil.which("uv") is None else ["uv"]
E2E_DB = "postgresql+asyncpg://signal:signal@localhost:5442/signal_e2e"


def sh(cmd: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None, check: bool = True) -> int:
    print("$", " ".join(cmd), flush=True)
    full_env = {**os.environ, **(env or {})}
    rc = subprocess.call(cmd, cwd=cwd, env=full_env, shell=IS_WIN and cmd[0] in ("pnpm", "npx"))
    if check and rc != 0:
        sys.exit(rc)
    return rc


def uv(*args: str, env: dict[str, str] | None = None, check: bool = True) -> int:
    return sh([*UV, "run", *args], env=env, check=check)


def docker(*args: str) -> int:
    if shutil.which("docker"):
        return sh(["docker", *args])
    # Windows host: Docker lives in the Alpine WSL distro (ADR-002).
    wsl_root = "/mnt/" + str(ROOT)[0].lower() + str(ROOT)[2:].replace("\\", "/")
    quoted = " ".join(f"'{a}'" for a in args)
    return sh(
        [
            "wsl",
            "-d",
            os.environ.get("SIGNAL_WSL_DISTRO", "Alpine"),
            "--",
            "sh",
            "-c",
            f'cd "{wsl_root}" && docker {quoted}',
        ]
    )


def cmd_setup() -> None:
    sh([*UV, "sync"])
    sh(["pnpm", "install"])
    sh(["pnpm", "exec", "playwright", "install", "chromium"], cwd=WEB)
    uv("python", "-m", "playwright", "install", "chromium", check=False)
    env_file = ROOT / ".env"
    if not env_file.exists():
        shutil.copy(ROOT / ".env.example", env_file)
        print("created .env from .env.example; set SIGNAL_ADMIN_PASSWORD and SIGNAL_SECRET_KEY")


def ensure_wsl_docker() -> None:
    """The Alpine WSL distro isn't booted by OpenRC, so dockerd doesn't auto-start after a reboot (RUNBOOK)."""
    if shutil.which("docker"):
        return
    distro = os.environ.get("SIGNAL_WSL_DISTRO", "Alpine")
    script = (
        "docker info >/dev/null 2>&1 || { rm -f /var/run/docker.pid; "
        "setsid nohup dockerd > /var/log/dockerd-manual.log 2>&1 < /dev/null & }; "
        "i=0; while [ $i -lt 40 ]; do docker info >/dev/null 2>&1 && exit 0; sleep 2; i=$((i+1)); done; exit 1"
    )
    rc = subprocess.call(["wsl", "-d", distro, "-u", "root", "--", "sh", "-c", script])
    if rc != 0:
        sys.exit("Docker daemon in WSL did not start; see /var/log/dockerd-manual.log inside the distro")


def cmd_infra() -> None:
    ensure_wsl_docker()
    docker("compose", "up", "-d", "db", "redis")
    for _ in range(40):
        if (
            uv(
                "python",
                "-c",
                "import asyncio,asyncpg;asyncio.run(asyncpg.connect("
                "'postgresql://signal:signal@localhost:5442/signal'))",
                check=False,
            )
            == 0
        ):
            return
        time.sleep(1.5)
    sys.exit("Postgres did not become ready on :5442")


def cmd_migrate() -> None:
    uv("python", "-m", "signal_core.cli", "migrate")


def cmd_seed(demo: bool = False) -> None:
    uv("python", "-m", "signal_core.cli", "seed", *(["--demo"] if demo else []))


SERVICES = {
    "api": [
        *UV,
        "run",
        "uvicorn",
        "signal_api.main:app",
        "--port",
        "8710",
        "--reload",
        "--reload-dir",
        "apps/api",
        "--reload-dir",
        "packages/core",
    ],
    "worker": [*UV, "run", "arq", "signal_worker.main.WorkerSettings"],
    "scheduler": [*UV, "run", "python", "-m", "signal_scheduler.main"],
    "web": ["pnpm", "--filter", "@signal/web", "dev"],
}


def cmd_up(mock: bool = False) -> None:
    cmd_infra()
    cmd_migrate()
    env = {"SIGNAL_USE_REDIS_QUEUE": "true"}
    if mock:
        env["SIGNAL_MODE"] = "mock"
        uv("python", "-m", "signal_core.cli", "seed", "--demo", env=env)
    else:
        cmd_seed()
    procs = []
    for name, cmd in SERVICES.items():
        print(f"starting {name}…", flush=True)
        procs.append(
            subprocess.Popen(cmd, cwd=ROOT, env={**os.environ, **env}, shell=IS_WIN and cmd[0] == "pnpm")
        )
    print("\nSIGNAL is up: web http://localhost:3710  api http://localhost:8710/docs  (Ctrl+C to stop)\n")
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                p.send_signal(
                    signal.CTRL_BREAK_EVENT if IS_WIN else signal.SIGINT
                ) if not IS_WIN else p.terminate()
        for p in procs:
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()


def cmd_lint() -> None:
    uv("ruff", "check", ".")
    uv("ruff", "format", "--check", ".")
    uv("mypy", "packages/core/signal_core", "apps")
    sh(["pnpm", "--filter", "@signal/web", "lint"])
    sh(["pnpm", "--filter", "@signal/web", "typecheck"])


def cmd_test() -> None:
    cmd_lint()
    uv("pytest", "--cov=signal_core", "--cov-report=term:skip-covered", "--cov-report=xml:coverage.xml")
    sh(["pnpm", "--filter", "@signal/web", "test"])


def cmd_e2e() -> None:
    env = {
        "SIGNAL_DATABASE_URL": E2E_DB,
        "SIGNAL_MODE": "mock",
        "SIGNAL_ADMIN_EMAIL": "owner@e2e.local",
        "SIGNAL_ADMIN_PASSWORD": "e2e-password-123",
        "SIGNAL_DATA_DIR": str(ROOT / "data" / "e2e"),
    }
    for c in ("ensure-db", "migrate", "reset-db"):
        uv("python", "-m", "signal_core.cli", c, env=env)
    uv("python", "-m", "signal_core.cli", "seed", "--demo", env=env)
    sh(["pnpm", "exec", "playwright", "test", *sys.argv[2:]], cwd=WEB, env={"CI": os.environ.get("CI", "")})


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        return
    c = sys.argv[1]
    if c == "setup":
        cmd_setup()
    elif c == "infra":
        cmd_infra()
    elif c == "migrate":
        cmd_migrate()
    elif c == "seed":
        cmd_seed("--demo" in sys.argv)
    elif c == "up":
        cmd_up()
    elif c == "mock":
        cmd_up(mock=True)
    elif c in SERVICES:
        sh(SERVICES[c])
    elif c == "lint":
        cmd_lint()
    elif c == "test":
        cmd_test()
    elif c == "e2e":
        cmd_e2e()
    elif c == "check":
        cmd_test()
        cmd_e2e()
    elif c == "runner-check":
        uv("python", "-m", "signal_core.cli", "runner-check")
    elif c in ("backup", "restore"):
        uv("python", "-m", "signal_core.ops.backup", *sys.argv[1:])
    else:
        sys.exit(f"unknown command {c!r}\n{__doc__}")


if __name__ == "__main__":
    main()
