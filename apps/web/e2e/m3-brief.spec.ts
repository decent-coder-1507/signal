import { chromium, expect, test } from "@playwright/test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ensureBrief, login } from "./helpers";

test.describe.serial("M3 brief flow", () => {
  test("onboarding → brief → feedback → story → done → today → routines → watch", async ({ page }) => {
    test.setTimeout(180_000);
    await login(page);
    if (!/\/onboarding/.test(page.url())) await page.goto("/onboarding");

    // 1. Onboarding wizard (8 steps)
    await expect(page.getByRole("heading", { name: "About you" })).toBeVisible();
    await page.getByLabel("Role").fill("AI engineer at VANCO");
    await page.getByLabel("Goals").fill("Ship production LLM systems\nBuild a public voice");
    for (const title of ["Topics", "Skills", "Voice", "Baseline", "Sources", "Schedule", "Budget"]) {
      await page.getByRole("button", { name: /^Next/ }).click();
      await expect(page.getByRole("heading", { name: title })).toBeVisible();
    }
    await page.getByRole("button", { name: /^Finish/ }).click();
    await expect(page).toHaveURL(/\/brief$/, { timeout: 90_000 });

    // 2. Brief with stories
    const cards = page.getByTestId("story-card");
    await expect(cards.first()).toBeVisible();
    expect(await cards.count()).toBeGreaterThanOrEqual(1);

    // 3. Keyboard: j focuses the first story, u records "useful"
    await page.keyboard.press("j");
    await expect(cards.first()).toHaveAttribute("data-focused", "true");
    await page.keyboard.press("u");
    await expect(page.getByTestId("toast").filter({ hasText: "Marked useful" })).toBeVisible();
    await expect(cards.first().getByTestId("feedback-state")).toHaveText("Marked useful");

    // 4. Story page
    await cards.first().getByRole("heading").getByRole("link").click();
    await expect(page).toHaveURL(/\/stories\//);
    await expect(page.getByRole("heading", { name: "Why it matters to you" })).toBeVisible();
    await expect(page.getByTestId("timeline-item").first()).toBeVisible();
    const cite = page.getByTestId("citation").first();
    await expect(cite).toBeVisible();
    await expect(cite).toHaveText(/^\[\d+\]$/);
    await expect(page.getByTestId("what-happened")).not.toContainText(/\[[0-9a-f]{8}-[0-9a-f]{4}/);

    // 5. Mark the brief done
    await page.goto("/brief");
    await page.getByRole("button", { name: "Mark brief done" }).click();
    await expect(page.getByRole("button", { name: "Brief done" })).toBeVisible();

    // 6. Today shows habit progress
    await page.goto("/");
    await expect(page.getByTestId("habit-progress")).toBeVisible();
    await expect(page.getByTestId("step-brief")).toHaveAttribute("data-done", "true");

    // 7. Settings → Routines lists daily_brief
    await page.goto("/settings");
    await page.getByRole("tab", { name: "Routines" }).click();
    await expect(page.getByTestId("routine").filter({ hasText: "daily_brief" })).toBeVisible();

    // 8. Create a watch
    await page.getByRole("tab", { name: "Watches" }).click();
    await page.getByLabel("Watch for").fill("Any new MCP spec version");
    await page.getByRole("button", { name: "Create watch" }).click();
    await expect(page.getByTestId("watch").filter({ hasText: "Any new MCP spec version" })).toBeVisible();
  });
});

test.describe("M3 mobile & PWA", () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test("no horizontal overflow at 375px on /brief and / @mobile", async ({ page }) => {
    await login(page);
    await ensureBrief(page);
    for (const path of ["/brief", "/"]) {
      await page.goto(path);
      if (path === "/brief") await expect(page.getByTestId("story-card").first()).toBeVisible();
      else await expect(page.getByTestId("habit-progress")).toBeVisible();
      const width = await page.evaluate(() => document.documentElement.scrollWidth);
      expect(width, `${path} scrollWidth`).toBeLessThanOrEqual(375);
    }
  });

  test("app is installable (no installability errors) @mobile", async ({ baseURL }, testInfo) => {
    // Playwright's default contexts are incognito, where Chrome never offers install ("in-incognito").
    // A persistent profile behaves like a normal browser window (ADR-016 replaces the Lighthouse PWA check).
    const dir = mkdtempSync(join(tmpdir(), "signal-pwa-"));
    const ctx = await chromium.launchPersistentContext(dir, {
      channel: testInfo.project.use.channel,
      baseURL,
      viewport: { width: 375, height: 812 },
    });
    try {
      const page = ctx.pages()[0] ?? (await ctx.newPage());
      await login(page);
      await page.goto("/");
      await expect(page.getByTestId("habit-progress")).toBeVisible();
      await page.waitForFunction(async () => !!(await navigator.serviceWorker?.getRegistration("/")));
      const client = await ctx.newCDPSession(page);
      const { installabilityErrors } = await client.send("Page.getInstallabilityErrors");
      expect(installabilityErrors).toEqual([]);
    } finally {
      await ctx.close();
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
