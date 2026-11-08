# api / worker / scheduler image (VPS deploy, ADR-002). Includes the Claude Code CLI for the Claude Runner and
# postgresql-client for backups. Log the CLI in once inside the worker: `docker compose exec worker claude` → /login
# (credentials persist in the `claude_home` volume). No API keys are used (ADR-001).
FROM python:3.12-slim
ENV UV_LINK_MODE=copy PYTHONUNBUFFERED=1 SIGNAL_RENDER_CHANNEL=
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates gnupg postgresql-client \
      nodejs npm && rm -rf /var/lib/apt/lists/* \
 && npm install -g @anthropic-ai/claude-code \
 && pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker
COPY apps/scheduler ./apps/scheduler
COPY config ./config
COPY prompts ./prompts
COPY alembic.ini ./
RUN uv sync --frozen --all-packages --extra local-embeddings --no-dev \
 && uv run python -m playwright install --with-deps chromium
RUN useradd -m signal && chown -R signal /app
USER signal
