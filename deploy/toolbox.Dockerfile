# syntax=docker/dockerfile:1
# Linux dev/test toolbox (ADR-024): the same `scripts/dev.py` commands, run on Linux so Windows Application Control
# can't block native binaries. The repo is mounted at /workspace; Linux packages live in Docker volumes
# (/venv, node_modules, Playwright browsers), never mixed with the Windows ones on the host.
FROM node:24-slim AS node

FROM python:3.12-slim
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && ln -s /usr/local/lib/node_modules/corepack/dist/corepack.js /usr/local/bin/corepack \
 && corepack enable \
 && apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates postgresql-client \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv
# Chromium's system libraries belong in the image (a --rm container can't keep apt installs). Version = uv.lock.
RUN pip install --no-cache-dir playwright==1.64.1 \
 && playwright install-deps chromium \
 && pip uninstall -y playwright && rm -rf /var/lib/apt/lists/*
ENV CI=1 UV_PROJECT_ENVIRONMENT=/venv UV_LINK_MODE=copy PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    SIGNAL_RENDER_CHANNEL= COREPACK_ENABLE_DOWNLOAD_PROMPT=0 PYTHONUNBUFFERED=1
WORKDIR /workspace
ENTRYPOINT ["sh", "deploy/toolbox-entrypoint.sh"]
CMD ["python", "scripts/dev.py", "check"]
