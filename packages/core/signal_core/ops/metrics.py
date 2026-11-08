"""Prometheus metrics (§16.4): items fetched, enriched, stories, brief latency, LLM cost/tokens, errors.
Exposed at GET /metrics (API process). Workers run in-process locally, so one registry covers both."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

LLM_CALLS = Counter("signal_llm_calls_total", "LLM calls through the router", ["task", "status", "provider"])
LLM_TOKENS = Counter("signal_llm_tokens_total", "LLM tokens", ["direction"])
LLM_COST = Counter("signal_llm_cost_usd_total", "API-equivalent LLM cost (USD)")
ITEMS_INGESTED = Counter("signal_items_ingested_total", "New items stored", ["source_type"])
ITEMS_ENRICHED = Counter("signal_items_enriched_total", "Items enriched")
STORIES = Gauge("signal_stories_active", "Active stories scored in the last run")
BRIEF_SECONDS = Histogram(
    "signal_brief_seconds", "Brief assembly time", buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 600)
)
JOB_FAILURES = Counter("signal_job_failures_total", "Job attempts that raised", ["job"])
SOURCE_ERRORS = Counter("signal_source_errors_total", "Source fetch errors", ["source"])
ROUTINE_RUNS = Counter("signal_routine_runs_total", "Routine runs", ["routine", "status"])
