# Runbook

## Prerequisites (this machine)
- Windows 11 with the **Alpine** WSL2 distro running Docker (`wsl -d Alpine -- docker ps`).
- Node 24 + pnpm, uv (`pip install --user uv`; it provides Python 3.12).
- Claude Code CLI logged in with your subscription: run `claude`, then `/login`. Check with `python scripts/dev.py runner-check`.

## First run
```
python scripts/dev.py setup     # uv sync + pnpm install + playwright browsers
python scripts/dev.py infra     # Postgres :5442, Redis :6390 in WSL Docker (project "signal")
python scripts/dev.py migrate
python scripts/dev.py seed
python scripts/dev.py up        # api :8710, worker, scheduler, web :3710
```
Open http://localhost:3710 and follow the onboarding wizard. To run fully offline, use `python scripts/dev.py mock`.

## Tests
- `python scripts/dev.py test`: lint, types, unit and integration tests (mock mode).
- `python scripts/dev.py e2e`: Playwright.
- `python scripts/dev.py check`: the milestone gate.

## Modes
- `SIGNAL_MODE=mock`: no network, deterministic providers.
- `SIGNAL_MODE=live`: real feeds, and the Claude Runner for AI. If `claude` auth fails, the provider is marked unhealthy and briefs degrade (deterministic ranking + extractive summaries).

## Backup / restore
Filled in at M10.

## Publishing terms
Filled in at M5/M10 (Hashnode, X, LinkedIn, Instagram access rules).
