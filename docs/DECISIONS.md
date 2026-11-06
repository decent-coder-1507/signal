# Decisions (ADR log)

Format: context → decision → consequences. Newest at the bottom.

## ADR-001 · Claude Runner instead of the Anthropic SDK (2026-11-06)
**Context.** Spec §5.1/§15.1 specifies `AnthropicProvider` with `ANTHROPIC_API_KEY`. At kickoff Srijoy chose "no LLM API keys anywhere; all AI through a Claude Runner and MCP". (His message cited §5.0/§10.3, which the v1.0 PDF does not contain; he confirmed the Runner approach.)
**Decision.** `ClaudeRunnerProvider` implements `LLMProvider` by running the local Claude Code CLI as a subprocess:
`claude -p --output-format json --model <tier alias> --system-prompt-file <tmp> --json-schema <schema> --tools "" --strict-mcp-config --no-session-persistence --setting-sources ""`, prompt on stdin (avoids the Windows 32k command-line limit). For Ask SIGNAL the runner may pass `--mcp-config` pointing at SIGNAL's own read-only MCP server. Never `--bare` (it ignores OAuth and requires an API key).
Verified 2026-11-06 against CLI 2.1.319 `--help` and code.claude.com docs (headless, cli-reference, legal-and-compliance). A probe call returned keys `type, subtype, is_error, result, structured_output?, total_cost_usd, usage, modelUsage, session_id, …`. **A failed auth came back with `subtype: "success"` and `is_error: true`**, so the runner treats `is_error` as authoritative.
**Terms.** Docs permit an end user signing in to the unmodified CLI with their own subscription; products for *other* users must use API keys. SIGNAL is single-user and local, so it stays inside that line. Must not be shared or hosted for others in Runner mode. Subscription 5-hour and weekly limits are shared with interactive Claude use, so the router caps concurrency (default 2) and daily calls.
**Consequences.** No token-level prompt caching control and no Batches API (§15.2). Instead SIGNAL caches responses itself and batches items into one call. `total_cost_usd` is a client-side "API-equivalent" estimate; the ledger stores it and the budget guard (§15.3) applies to it, which keeps the degrade paths meaningful. Auth failures mark the provider unhealthy, and the brief degrades per §16.4.

## ADR-002 · Infra in Alpine WSL Docker, apps native (2026-11-06)
Postgres 16 + pgvector (`pgvector/pgvector:pg16`, host port 5442) and Redis 7 (6390) run in the WSL distro's Docker as compose project `signal`. api/worker/scheduler/web run natively on Windows, because the Runner needs the host's `claude` login. `docker-compose.yml` also defines app services (profile `full`) for a future Linux/VPS deploy, where the runner calls a `claude` installed in the worker image. Ports chosen to avoid the user's other projects (3000, 5173, 5433, 6379, 55432).

## ADR-003 · Task runner `scripts/dev.py` (2026-11-06)
There is no `make` on the Windows host. `scripts/dev.py` implements up/test/seed/mock/check, and a thin `Makefile` delegates to it so the spec's `make up` etc. still work on Linux/WSL.

## ADR-004 · SPEC.md generation (2026-11-06)
`docs/SPEC.md` is generated with `pdftotext -layout` + `scripts/pdf2md.py`. Prose is verbatim. Tables and code are preformatted blocks in their original layout. Emoji glyphs the PDF font could not map are dropped.

## ADR-005 · Python 3.12 via uv, Next.js 16 (2026-11-06)
Host Python is 3.14, but the spec says 3.12. uv pins 3.12 for wheel availability (fastembed/onnxruntime, asyncpg). Next.js 16.4.5 and @playwright/test 1.65.0 are current on npm today.

## ADR-006 · Model tiers → CLI aliases (2026-11-06)
`config/budget.yaml`: fast = `haiku` (claude-haiku-5-5), balanced = `sonnet` (claude-sonnet-5-5), deep = `opus` (claude-opus-5-5). Verified at models/overview and model-config docs. Prices come from published API pricing, stored in config and used only for notional cost.
