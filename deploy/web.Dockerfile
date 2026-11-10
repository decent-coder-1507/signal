# syntax=docker/dockerfile:1
FROM node:24-slim AS build
# Next bakes rewrite destinations in at build time, so the API address must be known here, not only at runtime.
ARG SIGNAL_API_URL=http://api:8710
ENV SIGNAL_API_URL=${SIGNAL_API_URL}
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web ./apps/web
# Slow links: few parallel downloads, and retries that resume from the cached store (ADR-023).
RUN --mount=type=cache,id=pnpm-store,target=/root/.local/share/pnpm/store     for i in 1 2 3 4 5 6; do pnpm install --frozen-lockfile --network-concurrency=2 && break; echo "retry $i"; sleep 5; done  && pnpm --filter @signal/web build

FROM node:24-slim
RUN corepack enable
WORKDIR /app
COPY --from=build /app /app
ENV NODE_ENV=production PORT=3710
USER node
WORKDIR /app/apps/web
# Run Next directly: no Corepack/pnpm download at container start.
CMD ["node", "node_modules/next/dist/bin/next", "start", "-p", "3710"]
