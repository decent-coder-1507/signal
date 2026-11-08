import { expect, test } from "@playwright/test";
import { ensureOnboarded, login } from "./helpers";

test.describe.serial("M6–M8 Lab, Gym, Moat, Reviews", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await ensureOnboarded(page);
  });

  test("Lab: detect sparks → idea → build brief → zip download", async ({ page }) => {
    test.setTimeout(180_000);
    await page.goto("/lab");
    await page.getByRole("button", { name: "Detect sparks now" }).click();
    await expect(page.getByTestId("toast").first()).toBeVisible({ timeout: 90_000 });
    const card = page.getByTestId("idea-card").first();
    await expect(card).toBeVisible();
    await card.click();
    await expect(page).toHaveURL(/\/lab\/[0-9a-f-]+$/);
    const brief = page.getByTestId("build-brief");
    await brief.getByRole("button", { name: /^(Generate brief|Regenerate)$/ }).click();
    await expect(brief.getByRole("tab").first()).toBeVisible({ timeout: 90_000 });
    await expect(brief.getByRole("tab", { name: "BRIEF.md" })).toBeVisible();
    const [download] = await Promise.all([page.waitForEvent("download"), brief.getByRole("link", { name: /Download \.zip/ }).click()]);
    expect(download.suggestedFilename()).toMatch(/-brief\.zip$/);
  });

  test("Gym: explainer → review every due card by keyboard", async ({ page }) => {
    test.setTimeout(180_000);
    await page.goto("/gym?tab=explain");
    await page.getByLabel("Topic").fill("KV-cache");
    await page.getByRole("button", { name: "Explain", exact: true }).click();
    await expect(page.getByTestId("explainer")).toBeVisible({ timeout: 90_000 });

    await page.getByRole("tab", { name: "Cards" }).click();
    const start = page.getByRole("button", { name: "Start review" });
    await expect(start.or(page.getByTestId("no-cards"))).toBeVisible();
    if (await start.isVisible()) {
      await start.click();
      const review = page.getByRole("dialog", { name: "Card review" });
      for (let i = 0; i < 100; i++) {
        if (await review.getByText("No cards due").isVisible()) break;
        if (await review.getByText("Session done").isVisible()) {
          // more became due while reviewing: start another round
          await review.getByRole("button", { name: "Close", exact: true }).click();
          await start.click();
          continue;
        }
        await expect(review.getByTestId("review-card")).toBeVisible();
        await page.keyboard.press(" ");
        await expect(review.getByTestId("card-back")).toBeVisible();
        const before = await review.getByTestId("review-progress").textContent();
        await page.keyboard.press("3");
        await expect(review.getByTestId("review-progress")).not.toHaveText(before ?? "");
      }
      await expect(review.getByText("No cards due")).toBeVisible();
      await review.getByRole("button", { name: "Close", exact: true }).click();
    }
    await expect(page.getByTestId("no-cards")).toBeVisible();
  });

  test("Moat Radar: generate → a point links to its evidence", async ({ page }) => {
    test.setTimeout(180_000);
    await page.goto("/moat");
    await page.getByRole("button", { name: "Generate", exact: true }).click();
    await expect(page.getByTestId("moat-point").first()).toBeVisible({ timeout: 90_000 });
    const ev = page.getByTestId("moat-evidence").first();
    await expect(ev).toBeVisible();
    await expect(ev).toHaveAttribute("href", /^\/stories\/[0-9a-f-]+$/);
  });

  test("Reviews: weekly review is completable end to end", async ({ page }) => {
    test.setTimeout(240_000);
    await page.goto("/reviews?kind=weekly");
    await page.getByRole("button", { name: /^(Generate weekly review|Generate a new one)$/ }).click();
    const step = page.getByTestId("review-step");
    await expect(step).toBeVisible({ timeout: 120_000 });
    let accepted = false;
    for (let i = 0; i < 12; i++) {
      const finish = page.getByRole("button", { name: "Finish review" });
      if (await finish.isVisible()) break;
      if ((await step.getAttribute("data-step")) === "content_plan" && !accepted) {
        const box = step.getByTestId("content-proposal").locator("input:not([disabled])").first();
        if (await box.count()) {
          await box.check();
          accepted = true;
        }
      }
      const current = await step.getAttribute("data-step");
      await step.getByRole("button", { name: /mark done$/i }).click();
      await expect(step.locator(`xpath=self::*[@data-step!="${current}"]`).or(finish)).toBeVisible();
    }
    expect(accepted).toBeTruthy();
    await page.getByRole("button", { name: "Finish review" }).click();
    await expect(page.getByTestId("review-completed")).toBeVisible();
  });
});
