"""Real-data benchmark for RADAR prefilter, clustering, ranking and Ask retrieval (ADR-026).

- `build` (once, live mode, scratch DB copy): sample real items, label them with Claude, export fixtures/bench/.
- `run`: recompute every metric from the committed labels and embeddings (offline, deterministic).
"""
