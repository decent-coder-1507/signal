# syntax=docker/dockerfile:1
# api / worker / scheduler image (VPS deploy, ADR-002). Includes the Claude Code CLI for the Claude Runner and
# postgresql-client for backups. Log the CLI in once inside the worker: `docker compose exec worker claude` → /login
# (credentials persist in the `claude_home` volume). No API keys are used (ADR-001).
FROM python:3.12-slim
ENV UV_LINK_MODE=copy PYTHONUNBUFFERED=1 SIGNAL_RENDER_CHANNEL= PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates gnupg postgresql-client \
      nodejs npm && rm -rf /var/lib/apt/lists/* \
 && npm install -g @anthropic-ai/claude-code \
 && pip install --no-cache-dir uv
WORKDIR /app
# Layer order matters on slow links (ADR-023): dependencies and Chromium only rebuild when the lockfile
# changes; a code change only re-copies source and re-installs the four workspace packages.
COPY pyproject.toml uv.lock ./
COPY packages/core/pyproject.toml packages/core/
COPY apps/api/pyproject.toml apps/api/
COPY apps/worker/pyproject.toml apps/worker/
COPY apps/scheduler/pyproject.toml apps/scheduler/
RUN --mount=type=cache,target=/root/.cache/uv     uv sync --frozen --all-packages --extra local-embeddings --no-dev --no-install-workspace
RUN for i in 1 2 3 4 5; do uv run --no-sync python -m playwright install --with-deps chromium && exit 0;       echo "chromium download retry $i"; sleep 10; done; exit 1
COPY packages ./packages
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker
COPY apps/scheduler ./apps/scheduler
COPY config ./config
COPY prompts ./prompts
COPY alembic.ini ./
RUN --mount=type=cache,target=/root/.cache/uv     uv sync --frozen --all-packages --extra local-embeddings --no-dev
RUN useradd -m signal && mkdir -p /app/data && chown -R signal /app /ms-playwright
USER signal
