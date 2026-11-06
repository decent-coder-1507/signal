# SIGNAL — working rules for Claude Code

Personal tech-intelligence app (RADAR · STUDIO · LAB · GYM) for Srijoy Paul. Full spec: `docs/SPEC.md` (verbatim copy of the v1.0 PDF). Progress: `docs/PROGRESS.md`. Decisions: `docs/DECISIONS.md`. Ops: `docs/RUNBOOK.md`.

## Non-negotiable rules
1. **No LLM API keys anywhere.** All AI goes through the **Claude Runner** (`signal_core.llm.runner`), which shells out to the local Claude Code CLI headless (`claude -p --output-format json --json-schema …`) under the user's own subscription login. Never use `--bare` (it forces API-key auth). Never add `anthropic`/`openai` SDK keys to `.env`. SIGNAL's own data is exposed to Claude through the SIGNAL MCP server (`signal_core.mcp`). See ADR-001.
2. **Never invent facts.** Every factual sentence in generated output cites a stored item id (or a raw-material id for personal facts). Validators: verbatim `quote_span`, claim→source fact-check, URL whitelist (`signal_core.truth`). Mock outputs obey the same rules.
3. **Mock mode is first-class.** `SIGNAL_MODE=mock` runs everything offline and deterministically (MockProvider, MockEmbeddingProvider, recorded fixtures). All tests run in mock mode.
4. All LLM calls go through `llm.router.call(task, inputs, tier)` — prompt loading, JSON-schema validation + one repair retry, caching, ledger row in `llm_calls`, budget guard.
5. Jobs are idempotent (natural keys). Times stored UTC, displayed in Asia/Kolkata. Every generated row stores `prompt_version`, `model`, `source_item_ids`/citations.
6. Third-party numbers (feeds, limits, model IDs, prices) live in `config/*.yaml`, never hard-coded. Verify at build time, log in DECISIONS.md.
7. Never auto-post. Publishing adapters require an explicit per-post approval.
8. Don't touch other Docker projects in the Alpine WSL distro (buildx-* containers).

## Layout
```
apps/api        FastAPI app (signal_api)         port 8710
apps/worker     Arq worker + jobs (signal_worker)
apps/scheduler  cron → enqueue routines (signal_scheduler)
apps/web        Next.js 16 App Router PWA        port 3710
packages/core   signal_core: db, config, llm, embeddings, sources, extraction,
                scoring, clustering, studio, lab, gym, render, notify, truth, mcp
config/         profile, sources, scoring, routines, voice, platforms, budget, skills (.yaml)
prompts/        <task>/<version>.md with YAML front-matter
fixtures/       recorded feeds, golden LLM outputs (mock), labelled eval sets
docs/           SPEC, PROGRESS, DECISIONS, RUNBOOK, USER_GUIDE
scripts/        dev.py (task runner), pdf2md.py, backup/restore
```

## Commands (Windows: `python scripts/dev.py <cmd>`; Linux/WSL: `make <cmd>`)
| cmd | does |
|---|---|
| `infra` | start Postgres 16+pgvector (5442) and Redis 7 (6390) in WSL Docker, compose project `signal` |
| `up` | infra + api + worker + scheduler + web (native processes) |
| `migrate` / `seed` | alembic upgrade head / load config + starter data |
| `mock` | `up` with `SIGNAL_MODE=mock` |
| `test` | ruff + mypy + pytest (mock) + vitest + tsc + eslint |
| `e2e` | Playwright against api+web in mock mode |
| `check` | everything `test` + `e2e` does (milestone gate) |

Python: uv workspace, Python 3.12 (`uv run …`). JS: pnpm workspace.

## Conventions
- Python: ruff (lint+format), mypy strict on `packages/core`, pytest-asyncio, respx for HTTP, freezegun for time. SQLAlchemy 2 async + Alembic. UUID v7 ids, `user_id` on every table.
- TS: strict, ESLint, Vitest, TanStack Query, Tailwind, shadcn-style components in `apps/web/components/ui`.
- Conventional commits (`feat:`, `fix:`, `chore:`, `test:`, `docs:`). Commit after each milestone with PROGRESS.md updated.
- A milestone is done only when `scripts/dev.py check` is green and its acceptance criteria are ticked in PROGRESS.md.
- Default to a sensible choice + ADR in DECISIONS.md rather than asking. Stop only for irreversible or money-costing actions.
