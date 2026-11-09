import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { ensureBrief, ensureOnboarded, login, storyIds } from "./helpers";

/**
 * Visual QA (ADR-025): full-page screenshots of the main screens in light + dark, desktop + 375px mobile.
 * No pixel assertions — the PNGs land in docs/design/screens/ for human review.
 * Tagged @mobile so the mobile project runs it too. Run alone with `python scripts/dev.py e2e visual`.
 */

type Shot = { name: string; path: string | ((p: Page) => Promise<string>); ready: (p: Page) => Promise<void> };

const SHOTS: Shot[] = [
  { name: "today", path: "/", ready: (p) => expect(p.getByTestId("habit-progress")).toBeVisible() },
  { name: "brief", path: "/brief", ready: (p) => expect(p.getByTestId("story-card").first()).toBeVisible() },
  {
    name: "story",
    path: async (p) => `/stories/${(await storyIds(p, 1))[0]}`,
    ready: (p) => expect(p.getByTestId("timeline")).toBeVisible(),
  },
  { name: "studio", path: "/studio", ready: (p) => expect(p.getByRole("heading", { name: "Studio" })).toBeVisible() },
  { name: "lab", path: "/lab", ready: (p) => expect(p.getByTestId("lab-column-spark").or(p.getByRole("heading", { name: "Lab" })).first()).toBeVisible() },
  { name: "gym", path: "/gym?tab=progress", ready: (p) => expect(p.getByTestId("time-split")).toBeVisible() },
  { name: "ask", path: "/ask", ready: (p) => expect(p.getByLabel("Question")).toBeVisible() },
  { name: "ops", path: "/ops", ready: (p) => expect(p.getByTestId("health-status")).toBeVisible() },
  { name: "ops-costs", path: "/ops?tab=costs", ready: (p) => expect(p.getByTestId("budget-bar")).toBeVisible() },
];

test.describe("visual screenshots @mobile", () => {
  test.describe.configure({ timeout: 240_000 });

  for (const scheme of ["light", "dark"] as const) {
    test(`main screens in ${scheme} @mobile`, async ({ page }, testInfo) => {
      const out = join(testInfo.config.rootDir, "..", "..", "..", "docs", "design", "screens");
      mkdirSync(out, { recursive: true });
      const device = testInfo.project.name === "mobile" ? "mobile" : "desktop";
      await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
      await login(page);
      await ensureOnboarded(page);
      await ensureBrief(page);
      for (const s of SHOTS) {
        const path = typeof s.path === "string" ? s.path : await s.path(page);
        await page.goto(path);
        await s.ready(page);
        await page.waitForLoadState("networkidle").catch(() => undefined);
        await page.evaluate(() => document.fonts.ready);
        // Hide the Next.js dev-mode badge; it is not part of the app.
        await page.addStyleTag({ content: "nextjs-portal { display: none !important; }" });
        await page.screenshot({ path: join(out, `${s.name}-${scheme}-${device}.png`), fullPage: true });
        const width = await page.evaluate(() => document.documentElement.scrollWidth);
        const viewport = page.viewportSize()?.width ?? 0;
        expect.soft(width, `${s.name} (${scheme}, ${device}) horizontal overflow`).toBeLessThanOrEqual(viewport);
      }
    });
  }
});
