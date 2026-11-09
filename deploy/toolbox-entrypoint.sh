#!/bin/sh
# Toolbox bootstrap (ADR-024): idempotent, fast when everything is already installed in the volumes.
set -e
cd /workspace

retry() { # slow links (ADR-023): retry downloads, resuming from caches
  n=1
  until "$@"; do
    [ "$n" -ge 5 ] && return 1
    echo "retry $n: $*"; n=$((n + 1)); sleep 5
  done
}

echo "toolbox: python deps"
retry uv sync --frozen --all-packages --all-extras -q
echo "toolbox: node deps"
retry pnpm install --frozen-lockfile --network-concurrency=2 --reporter=silent

# Browser system libraries are baked into the image (toolbox.Dockerfile); the browsers themselves live in a volume.
echo "toolbox: browsers"
retry uv run --no-sync python -m playwright install chromium
(cd apps/web && retry pnpm exec playwright install chromium)

exec "$@"
