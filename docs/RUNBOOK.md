# Runbook

## 1. Prerequisites (this machine)
- Windows 11 with the **Alpine** WSL2 distro running Docker. `scripts/dev.py infra` starts `dockerd` itself if it's down after a reboot (ADR-021).
- Node 24 + pnpm, and Python via uv: `python -m pip install --user uv` (uv installs Python 3.12 itself).
- Google Chrome installed (Playwright and the carousel renderer drive it; ADR-010).
- **Claude Code CLI logged in with your subscription.** Run `claude` once, then `/login`. Check it with `python scripts/dev.py runner-check`. There are no API keys anywhere (ADR-001).

## 2. First run
```
python scripts/dev.py setup        # uv sync + pnpm install (+ Playwright browsers where downloads are allowed)
copy .env.example .env             # then edit: SIGNAL_ADMIN_PASSWORD, SIGNAL_SECRET_KEY (long random), SIGNAL_MODE=live
python scripts/dev.py infra        # Postgres+pgvector :5442, Redis :6390 in WSL Docker (project "signal")
python scripts/dev.py migrate
python scripts/dev.py seed         # owner user, profile, 59 starter sources, routines, skills, voice v1
python -m signal_core.cli mcp-config   # (uv run …) writes data/mcp-signal.json for Ask + your own Claude apps
python scripts/dev.py up           # api :8710, worker, scheduler, web :3710
```
Open http://localhost:3710, sign in with `SIGNAL_ADMIN_EMAIL` / `SIGNAL_ADMIN_PASSWORD`, then complete onboarding.
For an offline demo with fictional fixture data, use `python scripts/dev.py mock` instead of `up`.

Local embeddings: `uv sync --all-packages --all-extras` installs fastembed. Set `SIGNAL_EMBEDDING_PROVIDER=fastembed`; the bge-small model (~130 MB) downloads on first use.

## 3. Daily operation
- The scheduler runs everything: ingest every 30 min, the weekday brief at 07:30 IST (weekends 09:00), cards at 13:00, the weekly review on Sunday 10:00, the monthly review on the 1st, and nightly maintenance at 02:30 (merge, retrain, source health, **backup**, evals sample, cache cleanup, scheduler health).
- Keep `python scripts/dev.py up` running. To start it at login, use Task Scheduler with "At log on → python scripts/dev.py up".
- **Telegram (optional):** create a bot with @BotFather and put `SIGNAL_TELEGRAM_BOT_TOKEN` and `SIGNAL_TELEGRAM_CHAT_ID` in `.env` (send `/start` to the bot, then look up your chat id via `getUpdates`). Turn on Settings → Channels → Telegram. Locally run `uv run python -m signal_core.notify.telegram_poll`. On a VPS use the webhook (`/telegram/webhook` with the `telegram_webhook_secret` setting).
- **Email (optional):** set `SIGNAL_SMTP_URL=smtp://user:pass@host:587` and turn on Settings → Channels → Email. In mock mode, or without SMTP, digests are written to `data/outbox/*.eml`.
- Health: `/health`, the Ops page (runs, LLM ledger, costs, evals, source health, dead letters) and Prometheus at `/metrics`.

## 4. Claude Runner
- Every LLM call goes through `signal_core.llm.router` → `ClaudeRunnerProvider` → `claude -p --output-format json --json-schema … --tools "" --no-session-persistence`, with the system prompt in a temp file and the prompt on stdin, run outside the repo.
- If the login expires, calls fail with "not authenticated". Routines keep running, and briefs degrade to extractive, cited summaries marked "degraded". Fix with `claude` → `/login`.
- Subscription limits (5-hour and weekly) are shared with your interactive Claude use. `config/budget.yaml` caps calls per day (600); `SIGNAL_RUNNER_CONCURRENCY` (default 4) caps parallel `claude -p` processes. The costs page shows **API-equivalent** spend; the soft limit (80%) downgrades deep → balanced and caps insights at 15, and the hard limit (100%) allows only fast-tier work and user-initiated actions.
- Terms: single-user personal use of your own login. Do not host SIGNAL in Runner mode for other people (ADR-001).

## 5. Tests
- `python scripts/dev.py test`: ruff, ruff format, mypy (strict), eslint, tsc, pytest (mock mode, DB `signal_test`, coverage) and vitest.
- `python scripts/dev.py e2e`: resets `signal_e2e`, seeds the demo, runs Playwright (desktop + 375 px mobile) against api :8711 + web :3711.
- `python scripts/dev.py check`: both, the milestone gate.
- `uv run python scripts/verify_sources.py`: probes every starter feed live.
- `SIGNAL_MODE=mock SIGNAL_DATABASE_URL=…/signal_e2e uv run python scripts/perf.py`: performance against the §16.1 targets.

## 6. Backup & restore (§16.5)
- Nightly (02:30 IST) `backup` step: a `pg_dump -Fc` to `data/backups/daily/signal-YYYYMMDD-HHMMSS.dump` (0600), plus an archive of `data/assets`. Sunday copies go to `weekly/`. Retention is **14 daily + 8 weekly**. Optional off-site copy: `SIGNAL_BACKUP_S3_URL=rclone:remote:bucket/path` (needs rclone).
- Manual: `uv run python -m signal_core.ops.backup backup`.
- **Restore:** stop `up`, then
  `uv run python -m signal_core.ops.backup restore data/backups/daily/<file>.dump postgresql+asyncpg://signal:signal@localhost:5442/signal`
  then start `up` again. Restore the assets archive with `tar -xzf assets-<stamp>.tar.gz -C data/`.
- **Restore drill** (run monthly; executed in M10, see PROGRESS): `uv run python -m signal_core.ops.backup drill`. It backs up, restores into the scratch DB `signal_restore_drill`, and compares row counts of 9 key tables (`"match": true`).
- Full export at any time: Library → Export (Obsidian vault zip, JSON dump, metrics CSV).

## 7. Deploy to a small VPS (optional)
2 vCPU / 4 GB is enough. On the VPS: install Docker, clone the repo, write `.env` (`SIGNAL_MODE=live`, `SIGNAL_COOKIE_SECURE=true`, `SIGNAL_WEB_ORIGIN=https://your.domain`), then:
```
SIGNAL_DOMAIN=your.domain docker compose --profile full --profile vps up -d --build
docker compose exec worker claude          # → /login once (credentials persist in the claude_home volume)
docker compose exec api uv run python -m signal_core.cli migrate
docker compose exec api uv run python -m signal_core.cli seed
```
Caddy provides HTTPS automatically. Point the Telegram webhook at `https://your.domain/api/telegram/webhook` with your secret.

## 8. Publishing terms (verified 2026-11-07, ADR-019)
- Default for every platform is **publish-assist**: SIGNAL copies the text, opens the composer, and you post and paste the URL. It never auto-posts.
- **Hashnode:** GraphQL `publishPost`, only when the `publish.hashnode_api` flag, `SIGNAL_HASHNODE_TOKEN`, the `hashnode_publication_id` setting, a Ready draft and an explicit confirm are all present.
- **LinkedIn:** the self-serve "Share on LinkedIn" product (`w_member_social`) allows posting to your own profile. Organic carousels are PDF document posts. Not automated in v1.
- **X:** pay-per-use API (~$0.015 per post). Not automated in v1 (would cost money).
- **Instagram:** needs a Business/Creator account and the Content Publishing API. Not automated in v1.

## 9. Troubleshooting
| Symptom | Fix |
|---|---|
| `ConnectionRefused` on :5442 | `python scripts/dev.py infra` (also restarts dockerd in WSL) |
| Briefs say "degraded" | Claude CLI login expired or subscription limit hit: `claude` → `/login`; check Ops → LLM ledger |
| A source shows "fix or disable" | Ops/Settings → Sources → Test; disable it or fix the URL (`scripts/verify_sources.py`) |
| Carousel render fails | Chrome must be installed; check `SIGNAL_RENDER_CHANNEL` |
| `DLL load failed … Application Control policy has blocked this file` | Windows Smart App Control blocked a compiled file in `.venv`; see ADR-022 (`uv sync --reinstall-package <pkg>` after adding it to `no-binary-package`) |
| Nothing in the brief | Quiet day (by design), or ingest hasn't run: Ops → Runs → `continuous_ingest` |
