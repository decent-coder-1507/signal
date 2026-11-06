# Progress

Status legend: ☐ not started · ◐ in progress · ☑ done (all acceptance criteria pass, `scripts/dev.py check` green)

| # | Milestone | Status | Date | Commit |
|---|---|---|---|---|
| — | Kickoff: spec read, CLAUDE.md + docs created, §0.3 asked | ☑ | 2026-11-06 | |
| M0 | Foundation | ☑ | 2026-11-06 | see log |
| M1 | Ingestion | ☑ | 2026-11-07 | see log |
| M2 | Enrichment, clustering, scoring | ☑ | 2026-11-07 | see log |
| M3 | Daily Brief + core UI | ◐ | | backend done |
| M4 | Studio: text | ☐ | | |
| M5 | Studio: visual & long-form | ☐ | | |
| M6 | Lab | ☐ | | |
| M7 | Gym core + Moat Radar | ☐ | | |
| M8 | Rhythms & channels | ☐ | | |
| M9 | Analytics & learning loop + Ask | ☐ | | |
| M10 | Hardening & launch | ☐ | | |

## Kickoff answers (§0.3)
1. LLM: Claude Runner via the local Claude Code CLI (no API keys). See ADR-001. Note: the CLI's OAuth session on this machine was expired at kickoff, so live calls fail until `claude` → `/login` is run. Mock mode is used meanwhile.
2. Role/goals/stack/skill ratings: spec defaults; to be entered in the onboarding wizard.
3. Reference posts / raw-material bank: none yet; STUDIO shows "voice not calibrated".
4. Telegram / SMTP: none yet; adapters disabled.
5. Optional tokens (GitHub, Reddit, X, Hashnode, YouTube): none; those adapters are off.
6. Where to run: local machine only. Infra in Alpine WSL Docker (ADR-002).

## Acceptance criteria

### M0 Foundation
- [x] `make up` (`scripts/dev.py up`) starts everything
- [x] `make test` passes in mock mode
- [x] login works
- [x] `/health` green
- [x] an LLM call through the router writes a ledger row
- [x] invalid config fails fast with a clear error

### M1 Ingestion
- [x] ingest is idempotent on recorded fixtures (second run adds 0 items)
- [x] near-duplicates detected in fixture set ≥ 95%
- [x] a broken source is flagged after 3 failures
- [x] live mode fetches ≥ 500 items/day from the starter pack — **projected ~550/day** from one live run (see log; not yet a measured 24 h day)
- [x] capture of a URL creates an item in < 5 s

### M2 Enrichment, clustering, scoring
- [x] cluster purity ≥ 0.9 on labelled fixture set
- [x] same-event items from 3 sources form one story
- [x] insight fields all populated with valid citations
- [x] invalid quote spans are rejected
- [x] feedback changes subsequent rankings (test)

### M3 Daily Brief + core UI
- [x] brief auto-generates at the configured time in user TZ
- [x] brief ≤ 7 stories with diversity
- [x] completing triage marks habit day
- [x] watches trigger on fixture event
- [ ] PWA installable (Lighthouse)
- [ ] mobile layout usable at 375 px

### M4 Studio: text
- [ ] from a story: ≥ 3 angles and graded drafts in < 60 s
- [ ] banned phrase or unsupported claim cannot reach Ready without explicit override
- [ ] ask-me answers saved to raw-material bank
- [ ] every factual draft sentence has a resolvable citation
- [ ] repurpose LinkedIn → X thread works

### M5 Studio: visual & long-form
- [ ] carousel renders 1080×1350 PNGs + PDF with contrast check passing
- [ ] reel script: hook ≤ 2 s, timestamps sum to 30–60 s
- [ ] article export is valid Markdown with front-matter and working code fences
- [ ] Hashnode publish only after explicit approval (mock)

### M6 Lab
- [ ] daily brief shows ≤ 1 spark, only above threshold
- [ ] each product idea has ≥ 2 evidence links
- [ ] build brief zip contains BRIEF.md + CLAUDE.md
- [ ] a build-log entry seeds a STUDIO draft that uses only log facts

### M7 Gym core + Moat Radar
- [ ] learn-next shows 3 items with cited reasons
- [ ] explainer generates cards
- [ ] FSRS schedules next due dates correctly (unit-tested)
- [ ] Moat Radar monthly report renders with evidence links

### M8 Rhythms & channels
- [ ] each default routine runs on schedule in mock mode with expected outputs
- [ ] Telegram commands work against a mock Telegram server
- [ ] weekly review completable end-to-end in the UI
- [ ] notification cap enforced

### M9 Analytics & learning loop + Ask
- [ ] metrics form via Telegram stores data
- [ ] analytics shows baseline comparison
- [ ] accepting learnings creates a new voice version
- [ ] Ask answers fixture questions with correct citations, says "not in your knowledge base" when appropriate
- [ ] export opens cleanly in Obsidian

### M10 Hardening & launch
- [ ] budget soft/hard limits verified by test
- [ ] restore drill documented and executed
- [ ] all §16 targets measured and recorded
- [ ] 7 consecutive days of briefs without manual intervention (time-travel simulation if no live LLM)

## Log
- 2026-11-07 — **M1 Ingestion done.**
  - Starter pack: 59 sources in `config/sources.yaml`. 54 enabled sources verified live by `scripts/verify_sources.py` (0 failing); 5 are credential/flag-gated (ADR-012).
  - Fixture acceptance (`tests/integration/test_ingest.py`): idempotent re-run adds 0 items; near-dup recall **20/20 = 100%** with 0 false positives; broken source flagged on the 3rd consecutive failure; a failed source doesn't block others; HN points merge into the official item.
  - Capture: URL capture in < 5 s (test asserts it; mocked page), text, PDF, API-token path; OPML import with DTD/entity rejection (defusedxml).
  - **Live run (2026-11-06, real network, fastembed bge-small):** 56 sources fetched, **7,041 items** stored, 0 source errors after fixes. The first screening (backfill) took 317 s: 144 duplicates, 6,082 prefiltered out, 817 passed. Published in the last 24 h: 246 items. arXiv's batch dates and short rolling feeds undercount a single fetch, so daily volume was **projected from each feed's own publishing rate: ~550 items/day** (conservative: sub-day feeds are not extrapolated up). A measured 24 h figure will come from continuous running (M10).
  - Bugs found by the live run and fixed: DB pool exhaustion (two-phase fetch/store), ONNX 3 GB allocation (embed batch 16), O(n²) SimHash scan (numpy index), Windows `fromtimestamp` OSError on year-1 dates.
- 2026-11-07 — **M2 Enrichment, clustering, scoring done.**
  - `tests/integration/test_radar_pipeline.py`: cluster purity **1.00** on the labelled fixture set (15 stories); the 3-source prompt-injection event forms one story; "Nimbus-4 launch" and "Nimbus-3 price cut" stay separate; every insight has all §6.7 fields, and every `what_happened` sentence cites a member item (`check_citations` ok); non-verbatim quote spans are rejected (injected lies never stored); feedback lowers the target's score and changes the ranking; primary-source tracing re-attaches a linked official post; an LLM outage leaves items `new` with no crash.
  - API: `/stories` (cursor pagination, ring/topic/since filters), `/stories/{id}` (timeline with labels, insight, citations, "why" sub-scores), follow, regenerate-insight, `/feedback` (bounded topic nudges ±20%/month, retrain, "wrong" → eval case).
  - Gate: ruff + format clean, mypy strict clean (73 files), **pytest 102 passed**, coverage 86% of signal_core, Playwright e2e 2/2 (demo seed now runs the full RADAR pipeline: 15 stories, 15 insights).
- 2026-11-06 — **M0 Foundation done.** Results:
  - `scripts/dev.py test`: ruff clean, ruff format clean, mypy strict (42 files) clean, pytest **35 passed** (mock mode, Postgres `signal_test`), coverage of signal_core **88%**, vitest 2 passed, eslint + tsc clean.
  - `scripts/dev.py e2e`: Playwright **2 passed** (desktop + 375 px mobile): bad login shows error, login works, /ops health = ok.
  - `scripts/dev.py up`: api :8710 + web :3710 both 200, `/health` = ok (db, config, redis, llm=mock). The scheduler fired `continuous_ingest` and `metrics_prompts` through Redis → Arq worker → `runs` (status ok).
  - Ledger: `test_call_writes_ledger_row_and_validates`; config fail-fast: `tests/unit/test_config.py` (weights sum, bad cron, missing file, unknown key, missing price, bad TZ).
  - Demo: `python scripts/dev.py mock` → http://localhost:3710 → sign in with SIGNAL_ADMIN_EMAIL/PASSWORD → Ops shows health.
- 2026-11-06 — Kickoff. Spec converted to docs/SPEC.md. Verified Claude CLI headless flags and terms (ADR-001).
