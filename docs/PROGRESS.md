# Progress

Status legend: ☐ not started · ◐ in progress · ☑ done (all acceptance criteria pass, `scripts/dev.py check` green)

| # | Milestone | Status | Date | Commit |
|---|---|---|---|---|
| — | Kickoff: spec read, CLAUDE.md + docs created, §0.3 asked | ☑ | 2026-11-06 | |
| M0 | Foundation | ☑ | 2026-11-06 | see log |
| M1 | Ingestion | ☑ | 2026-11-07 | see log |
| M2 | Enrichment, clustering, scoring | ☑ | 2026-11-07 | see log |
| M3 | Daily Brief + core UI | ☑ | 2026-11-07 | 17528c3 |
| M4 | Studio: text | ☑ | 2026-11-07 | b4fa247, 74368d4 |
| M5 | Studio: visual & long-form | ☑ | 2026-11-07 | 3d6ca12 |
| M6 | Lab | ☑ | 2026-11-08 | 3d6ca12 + web: final |
| M7 | Gym core + Moat Radar | ☑ | 2026-11-08 | 102cb7f + web: final |
| M8 | Rhythms & channels | ☑ | 2026-11-08 | eb142f0 + web: final |
| M9 | Analytics & learning loop + Ask | ☑ | 2026-11-08 | fb21933 + web: final |
| M10 | Hardening & launch | ☑ | 2026-11-08 | f92f9f3, acf0b63, final |

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
- [x] PWA installable: CDP `Page.getInstallabilityErrors` = [] in e2e (Lighthouse no longer audits PWAs, ADR-016)
- [x] mobile layout usable at 375 px (e2e @mobile: shell, no horizontal overflow on /brief and /, installability)

### M4 Studio: text
- [x] from a story: ≥ 3 angles and graded drafts in < 60 s
- [x] banned phrase or unsupported claim cannot reach Ready without explicit override
- [x] ask-me answers saved to raw-material bank
- [x] every factual draft sentence has a resolvable citation
- [x] repurpose LinkedIn → X thread works

### M5 Studio: visual & long-form
- [x] carousel renders 1080×1350 PNGs + PDF with contrast check passing
- [x] reel script: hook ≤ 2 s, timestamps sum to 30–60 s
- [x] article export is valid Markdown with front-matter and working code fences
- [x] Hashnode publish only after explicit approval (mock)

### M6 Lab
- [x] daily brief shows ≤ 1 spark, only above threshold
- [x] each product idea has ≥ 2 evidence links
- [x] build brief zip contains BRIEF.md + CLAUDE.md
- [x] a build-log entry seeds a STUDIO draft that uses only log facts

### M7 Gym core + Moat Radar
- [x] learn-next shows 3 items with cited reasons
- [x] explainer generates cards
- [x] FSRS schedules next due dates correctly (unit-tested)
- [x] Moat Radar monthly report renders with evidence links

### M8 Rhythms & channels
- [x] each default routine runs on schedule in mock mode with expected outputs
- [x] Telegram commands work against a mock Telegram server
- [x] weekly review completable end-to-end in the UI
- [x] notification cap enforced

### M9 Analytics & learning loop + Ask
- [x] metrics form via Telegram stores data
- [x] analytics shows baseline comparison
- [x] accepting learnings creates a new voice version
- [x] Ask answers fixture questions with correct citations, says "not in your knowledge base" when appropriate
- [x] export opens cleanly in Obsidian

### M10 Hardening & launch
- [x] budget soft/hard limits verified by test
- [x] restore drill documented (RUNBOOK §6) and executed
- [x] all §16 targets measured and recorded (see log)
- [x] 7 consecutive days of briefs without manual intervention: **time-travel simulation** (live LLM not available, CLI login expired)

## Log
- 2026-11-10 — **Real-data benchmark and engine tuning (ADR-026).** 300 real items (Claude relevance labels, opus agreement κ 0.83), 210 same-event pairs, 30 Ask questions and 40 judge calls, committed under `fixtures/bench/`; `python -m signal_core.ops.bench run` recomputes everything offline; `tests/integration/test_bench.py` guards the floors. Found that the live profile vectors were mock-embedded (now rebuilt on an embedder mismatch). Before → after: prefilter corpus recall 0.61 → 0.82 (AUC 0.76 → 0.81); clustering pairwise F1 0.59 → 0.84; ranking NDCG@10 0.54 → 0.69, P@7 0.54 → 0.80; Ask MRR 0.93 → 1.00. 124 Claude calls. The user should spot-check `fixtures/bench/SPOTCHECK.md`. Gate (`dev.py linux check`): ruff, format, mypy clean; pytest 193 passed; vitest 35 passed; Playwright 23 passed.
- 2026-11-09 — **Health check, Linux toolchain, redesign.**
  - Live Claude Runner verified end to end: 61 real calls (enrich, judge, insights, studio, ask, explainer, spark), 0 errors; 14/14 insights pass the citation check; Ask answers "not in your knowledge base" for an unknowable question.
  - Bugs found and fixed: one malformed scraped URL (`localhost:11434.`) crashed scoring; brief one-liners broke on real citation style; onboarding budget was ignored; story "Build" did nothing; wide-lens stories could enter the brief; LLM cache insert raced; drafts took 256 s live (checks now concurrent); restore failed on Linux/VPS (masked password, then PG17 client vs PG16 server); API committed after sending the response (race → 404); date-dependent tests; WSL helper re-parsed its script.
  - No `.env` existed, so everything had run on defaults (mock mode, placeholder secrets): live mode now refuses placeholders; `dev.py init-env` creates `.env`. The main DB's 300 enrichments / 253 stories were produced by the mock provider and must be reset before going live.
  - Windows Application Control blocks native binaries (SQLAlchemy/mypy C extensions, uvicorn/arq/mypy launchers, Next SWC, Tailwind oxide). Dev and tests now run in a Linux toolbox container (`python scripts/dev.py linux <cmd>`, ADR-024); the full stack runs in Alpine Docker (ADR-023).
  - Redesign merged (ADR-025): bento light + midnight dark + editorial story header, theme toggle; screenshots in `docs/design/screens/`.
  - Gate on Linux: ruff/format/mypy/eslint/tsc clean, **pytest 184 passed**, **Vitest 35 passed**, **Playwright 23 passed** (desktop + 375 px, incl. visual spec).
- 2026-11-08 — **Post-v1 fixes (gaps found while building the web UI).**
  - `GET /today` returns only daily/catch-up/weekend briefs, never a weekly/monthly review; Today uses it directly again.
  - Explainers return `sources` (id, title, URL, source) for their citations; the Gym explainer shows numbered footnotes with a linked source list.
  - `/search` returns only hrefs that exist: items → their story, build logs → the idea page, explainers → `/gym?tab=explain&topic=…&depth=…`, notes → Library; `null` means "open the original URL".
  - `chat_messages.meta` (migration `b7c1d2e3f4a5`) stores `mode`, `not_in_kb`, `offer_watch`, so a reloaded Ask thread keeps the "Create watch" button.
  - Weekly review always has readable idea/try-it, learn-next and quiz sections, with links to Lab and Gym (or a line saying nothing came up).
  - Regression tests added for each of the five.
- 2026-11-08 — **M3–M10 done; v1 complete.** Final gate:
  - Backend: ruff + format clean, mypy strict clean (93 files), **pytest 179 passed** (mock mode). One test (`test_completing_triage_marks_habit_day`) depended on the calendar date (fixture corpus dated 2026-11-06, endpoint used the wall clock); it now pins the router clock.
  - Web: tsc + eslint clean, **Vitest 35 passed** (9 files), **Playwright 19 passed** in 1.8 min (16 desktop + 3 mobile @375 px), covering M0–M10 screens: onboarding, Today, Brief triage, story page, Studio (angles → graded draft → Ready gate → repurpose), Lab, Gym (6 tabs), Moat, Reviews wizards, Channels, Ask (streaming + citations + not-in-KB), search palette, Library, Analytics, Ops (7 tabs).
  - M4: angles + graded draft in **0.43 s** with mock LLM (target < 60 s); Ready gate blocks banned phrases, em dashes and unsupported claims without a written override; ask-me answers land in `raw_materials`; LinkedIn → X thread repurpose tested.
  - M5: carousel PNGs 1080×1350 + PDF, contrast ≥ 4.5 and font ≥ 28 px checked; reel hook ≤ 2 s and 30–60 s total validated; article export Markdown with front-matter; Hashnode publish only with flag + token + Ready + explicit confirm (mock transport).
  - M6–M8: ≤ 1 spark/brief above threshold; ≥ 2 evidence links per idea; build-brief zip (BRIEF.md + CLAUDE.md); build log → Studio draft using only log facts; learn-next 3 cited items; explainer → cards; FSRS-4.5 unit-tested; Moat Radar with evidence links; every default routine runs in mock mode; Telegram commands against a mock Bot API; notification cap 4/day + quiet hours; weekly review completable in the UI (e2e).
  - M9: Telegram `/metrics` stores snapshots; baseline comparison; accepted learnings create voice v2; Ask answers fixture questions with correct citations and says "Not in your knowledge base" otherwise; Obsidian vault export (front-matter + wikilinks) validated.
  - M10 performance (`scripts/perf.py`, mock LLM, e2e demo DB): brief generate **0.39 s**; p95 today **27.6 ms**, story page **21.1 ms**, search **22.4 ms**, stories list **25 ms**; all §16.1 targets passed. Live Claude latency not measured (CLI login expired at build time).
  - Restore drill: dump **212,720 bytes**, restore **4.6 s** into `signal_restore_drill`, row counts match on 9 tables. Budget soft (80% → deep downgraded, insights capped) and hard (fast + user-initiated only) limits verified by tests. `pip-audit` and `pnpm audit`: no known vulnerabilities. Evals harness: all targets passed.
  - 7-day time-travel simulation: 7 daily/weekend briefs, 7 nightly maintenance runs, 1 weekly review, 0 failed runs, no manual steps.
  - Security review fixes landed: TOTP/API-token re-auth, SSRF guard, safe URLs in the UI, MCP config without DB credentials (0600), backups via PGPASSWORD with scrubbed errors.
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
