# Progress

Status legend: ☐ not started · ◐ in progress · ☑ done (all acceptance criteria pass, `scripts/dev.py check` green)

| # | Milestone | Status | Date | Commit |
|---|---|---|---|---|
| — | Kickoff: spec read, CLAUDE.md + docs created, §0.3 asked | ☑ | 2026-11-06 | |
| M0 | Foundation | ☐ | | |
| M1 | Ingestion | ☐ | | |
| M2 | Enrichment, clustering, scoring | ☐ | | |
| M3 | Daily Brief + core UI | ☐ | | |
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
- [ ] `make up` (`scripts/dev.py up`) starts everything
- [ ] `make test` passes in mock mode
- [ ] login works
- [ ] `/health` green
- [ ] an LLM call through the router writes a ledger row
- [ ] invalid config fails fast with a clear error

### M1 Ingestion
- [ ] ingest is idempotent on recorded fixtures (second run adds 0 items)
- [ ] near-duplicates detected in fixture set ≥ 95%
- [ ] a broken source is flagged after 3 failures
- [ ] live mode fetches ≥ 500 items/day from the starter pack (measured or projected from one live run)
- [ ] capture of a URL creates an item in < 5 s

### M2 Enrichment, clustering, scoring
- [ ] cluster purity ≥ 0.9 on labelled fixture set
- [ ] same-event items from 3 sources form one story
- [ ] insight fields all populated with valid citations
- [ ] invalid quote spans are rejected
- [ ] feedback changes subsequent rankings (test)

### M3 Daily Brief + core UI
- [ ] brief auto-generates at the configured time in user TZ
- [ ] brief ≤ 7 stories with diversity
- [ ] completing triage marks habit day
- [ ] watches trigger on fixture event
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
- 2026-11-06 — Kickoff. Spec converted to docs/SPEC.md. Verified Claude CLI headless flags and terms (ADR-001).
