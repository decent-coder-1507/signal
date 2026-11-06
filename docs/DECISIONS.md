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

## ADR-007 · Job queue: Arq + inline fallback (2026-11-06)
`signal_core.jobs`: with `SIGNAL_USE_REDIS_QUEUE=true` jobs go to Arq/Redis (idempotent `_job_id = name:key`). Otherwise they run inline (tests, single-process dev). Every attempt goes in `jobs`. After 3 failures a job is `dead` (dead-letter list for Ops). The scheduler claims due routines (sets `last_run_at`) before enqueueing, so a slow run is never double-fired.

## ADR-008 · Auth details (2026-11-06)
Signed session cookie (itsdangerous, 30 days, HttpOnly, SameSite=Lax) plus a double-submit CSRF cookie and the `x-csrf-token` header on writes. Bearer API token (sha256-hashed) skips CSRF. Login is limited to 10/min per IP, and the account locks for 15 min after 5 failures. The web app proxies `/api/*` to the API (Next rewrites), so cookies stay same-origin.

## ADR-009 · Mock providers (2026-11-06)
MockProvider looks up `fixtures/llm/<task>/<hash12>.json` first, then a deterministic per-task generator that only quotes input text, so mock outputs pass the same truth validators as live. MockEmbeddingProvider is a hashed bag of words with bigrams (384-d), so cosine tracks lexical overlap and dedupe/cluster tests stay deterministic.

## ADR-010 · Playwright uses installed Chrome locally (2026-11-06)
The sandbox blocked the Playwright browser download (cdn.playwright.dev ENOTFOUND from node). Locally, e2e uses `channel: "chrome"` (installed Google Chrome; override with `PW_CHANNEL`). CI uses the bundled Chromium.

## ADR-011 · Ledger writes in their own transaction (2026-11-06)
`llm_calls` rows are committed independently of the caller's transaction, so failed or blocked calls still count toward the budget even when the caller rolls back.

## ADR-012 · Starter source pack verified live (2026-11-06)
`scripts/verify_sources.py` probed all 59 sources in `config/sources.yaml`. **54 enabled sources returned entries**; 5 are credential/flag-gated (Reddit, Product Hunt, X, IMAP, capture) and disabled by default. Changes from the spec's examples after verification:
- **Anthropic has no official RSS** (`/rss.xml`, `/news/rss.xml`, `/news/feed` all 404). Using the community mirror `Olshansk/rss-feeds` (tier 2, noted in `terms_note`). Primary-source tracing links to anthropic.com.
- LangChain blog (no entries at any feed URL), Mistral and Meta AI (no feeds) were dropped. Moneycontrol returns 503 to non-browser clients, so it was replaced by Analytics India Magazine and MediaNama.
- Karpathy YouTube channel id corrected to `UCYO_jab_esuFRV4b17AJtAw` (taken from the channel page).
- GitHub watched-repo releases use public `releases.atom` feeds (no API quota). GitHub's robots.txt allows `/trending` and `releases.atom`.
- Network behaviour of this host: ~60 parallel requests cause timeouts and disconnects. The polite client caps global concurrency at 6, with a 45 s timeout, 2 retries, 1 s per-host spacing, 3 s for arXiv (its API terms) and 0.1 s for the HN Firebase API.

## ADR-013 · Ingest pipeline shape (2026-11-06)
- Fetches run concurrently per source (each in its own transaction). **Dedupe + prefilter run afterwards as one sequential "screening" pass, oldest first**, so every item is compared with committed items from all sources. Doing it inline missed cross-source duplicates.
- Near-duplicate = SimHash ≤ 3 bits **or** embedding cosine ≥ 0.95 **or** 3-shingle containment ≥ 0.90 among the 5 nearest embedding neighbours. Containment was added because syndicated copies of short feed items change SimHash too much. On the fixture set, same-event rewrites reach 0.84 containment and true copies 1.0.
- When two sources race to insert the same canonical URL, the loser's signal metadata (HN points, stars) is merged into the winning row.
- Full-page text extraction is not done at ingest for feed items (the feed body is used). It happens for captures and, from M2, for items that pass the prefilter, which saves thousands of page fetches a day.
- Mock mode only fetches fixture sources (`params.fixture=true`) through `FixtureTransport`, so mock mode never touches the network.
- Captures are a user-directed single-page fetch, so robots.txt is not applied (crawlers/feeds still honour it). Captures have a 4 s timeout and always create an item.
- Prefilter keywords match case-insensitively with plural tolerance. A lone, generic, one-word keyword hit counts half (it stopped "former agents" in a history story from passing).

## ADR-014 · Fictional fixture corpus (2026-11-06)
Tests and the mock-mode demo use `signal_core.fixtures_corpus`. Every company, product and event in it is fictional (Nimbus AI, Orchid Labs, Kestrel, Tessera, Digital Standards Board…) and all URLs are `.example`. Demo content therefore can never be mistaken for real news, which honours the never-invent-facts rule even in demo mode. Secondary outlets deterministically paraphrase the shared fact sentences (names and numbers verbatim). Twenty syndicated copies provide the dedupe recall set.

## ADR-015 · Scoring, clustering and judgement details (2026-11-06)
- **One judge call per story.** The spec rates impact and durability with the LLM and relevance with P3. To save calls, P3 `relevance_judge` also returns impact, durability and content/build/learn potentials (balanced tier, top 60 only). The deterministic pass runs first; the judge refines only the top of the list.
- **Thresholds are per embedding model.** `scoring.yaml` keeps the spec defaults (join 0.82, merge 0.88) for bge-small. Measured on the fixture corpus, same-event pairs score ≥ 0.82 and different events have p95 0.67. The mock embedder gets calibrated overrides (join 0.42, merge 0.60). Relevance maps raw cosine onto 0–1 with a per-embedder `[cos_at_0, cos_at_1]` scale.
- **Entity compatibility rule for joining.** If both sides name *specific* entities (models, products, repos, papers), they must share one. Otherwise ≥ 1 shared entity is enough, and if either side has none, cosine alone decides. Without this, "Nimbus-4 launch" and "Nimbus-3 price cut" (same company, cosine 0.865 with bge) merged.
- Enriched entities are kept only if they literally appear in the item (anti-hallucination), and quote spans must be verbatim (`signal_core.truth`). Insight sentences without a resolvable `[item_id]` are dropped. If nothing verifiable survives, an extractive cited summary is stored instead.
- **Preference model.** L2 logistic regression in numpy (no scikit-learn), retrained after each explicit feedback and nightly. It needs ≥ 6 labelled stories; before that `learned = 0.5`. With the spec's 0.05 weight, feedback moves rankings gently: the acceptance test checks that scores and order change, not that the #1 story falls.
- **Topic nudges** are bounded to ±20% per calendar month. At a month boundary the previous drift is folded into the base weight (capped 0–2), so learning persists while each month's change stays bounded.
- Embedding with fastembed uses batch 16 and texts clipped to 1,200 characters. The default batch tried to allocate 3 GB in ONNX attention on this machine.
- Ingest is two-phase (network fetch with no DB connection held, then short per-source transactions). Holding a session per concurrent fetch exhausted the pool (20 connections) during the live run.

## ADR-017 · SSRF guard on outbound fetches (2026-11-07)
Flagged by the automated security review. Captures arrive with the API token (bookmarklet, Telegram), so a crafted URL could make the server fetch internal addresses. `PoliteClient` now has a guard, on by default for real network access (`SIGNAL_SSRF_GUARD`): http(s) only, every resolved address must be public (no private, loopback, link-local, multicast, reserved, unspecified or IPv4-mapped internal addresses), redirects are followed manually and each hop re-validated (max 5). Source create/update and `/capture` return 422 for blocked URLs. Injected transports (mock fixtures, tests) bypass the guard, and the test suite disables it globally because respx `.example` hosts don't resolve; the guard has its own unit tests. Residual risk: DNS rebinding between check and connect (no IP pinning). Acceptable for a single-user local app; revisit if hosted.

## ADR-018 · Studio implementation choices (2026-11-07)
- **One writer template** (`prompts/writer/v1.md`) with the platform spec, format rules and rubric injected, instead of near-duplicate `writer_<platform>` files. The grader gets the platform-specific rubric (§7.5 variants). Same behaviour, a third of the prompts to maintain.
- **AI-tell scan = deterministic scanner + the grader's `ai_phrases`.** The grader already reads the draft with fresh context and lists AI-sounding phrases, so a separate LLM pass would double the cost for the same signal. Deterministic hits (banned phrases/patterns, em dash, numbered lessons, bold Unicode, hashtag/emoji/length limits) block Ready. LLM-flagged phrases are advisory highlights.
- **Ready gate** blocks on: blocking AI-tell issues, fact-check `unsupported`, factual sentences (numbers / proper names) not covered by a sourced claim, claims citing unknown ids, high safety flags, and 16+ words copied from a source (§7.8 "quotes under 15 words"). An override needs a written reason (≥ 5 chars) and is stored with the overridden reasons. A human edit re-enters the gate.
- **Ask-me answers** are stored as `raw_materials` (origin `ask_me`; consent toggle → `public`, otherwise `private`) and passed to the writer as `r:<id>` facts. Skipping means the writer gets no personal facts. For build-log seeds the log is the only source of personal facts.
- Every writer call is `user_initiated` (the user is waiting), so budget degrade paths never block an interactive draft at the hard limit. They only downgrade deep → balanced.
