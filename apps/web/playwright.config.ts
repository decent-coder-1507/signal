import { defineConfig, devices } from "@playwright/test";

// E2E runs against a dedicated mock-mode stack: api :8711 (db signal_e2e) + web :3711.
// `python scripts/dev.py e2e` resets + seeds signal_e2e before invoking this.
const API_PORT = 8711;
const WEB_PORT = 3711;
const root = "../..";
// Locally we drive the installed Google Chrome (no browser download needed); CI uses bundled Chromium.
const channel = process.env.CI ? undefined : (process.env.PW_CHANNEL ?? "chrome");

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"], ["html", { open: "never" }]],
  use: { baseURL: `http://localhost:${WEB_PORT}`, trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], channel } },
    { name: "mobile", use: { ...devices["Pixel 7"], viewport: { width: 375, height: 812 }, channel }, grep: /@mobile/ },
  ],
  webServer: [
    {
      command: `python -m uv run --directory ${root} uvicorn signal_api.main:app --port ${API_PORT}`,
      url: `http://localhost:${API_PORT}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        SIGNAL_MODE: "mock",
        SIGNAL_DATABASE_URL: "postgresql+asyncpg://signal:signal@localhost:5442/signal_e2e",
        SIGNAL_ADMIN_EMAIL: "owner@e2e.local",
        SIGNAL_ADMIN_PASSWORD: "e2e-password-123",
        SIGNAL_SECRET_KEY: "e2e-secret",
        SIGNAL_DATA_DIR: "data/e2e",
      },
    },
    {
      command: `pnpm next dev -p ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}/login`,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      env: { SIGNAL_API_URL: `http://localhost:${API_PORT}` },
    },
  ],
});
