import { expect, test } from "@playwright/test";
import { ensureOnboarded, login } from "./helpers";

test.describe.serial("M9/M10 Ask, Library, Analytics, Ops", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await ensureOnboarded(page);
  });

  test("Ask: cited answer, then not-in-KB with a watch offer", async ({ page }) => {
    test.setTimeout(120_000);
    await page.goto("/ask");
    const input = page.getByLabel("Question");
    await input.fill("What did Nimbus AI release?");
    await page.getByRole("button", { name: "Ask", exact: true }).click();
    const first = page.getByTestId("answer").first();
    await expect(first.getByTestId("citation").first()).toBeVisible({ timeout: 60_000 });
    await expect(first).not.toContainText(/\[[0-9a-f]{8}-[0-9a-f]{4}/);
    await expect(page).toHaveURL(/\/ask\?t=/);

    await input.fill("What did the Martian parliament decide?");
    await page.getByRole("button", { name: "Ask", exact: true }).click();
    const nokb = page.getByTestId("answer").nth(1).getByTestId("not-in-kb");
    await expect(nokb).toBeVisible({ timeout: 60_000 });
    await nokb.getByRole("button", { name: "Create watch" }).click();
    await expect(nokb.getByRole("button", { name: "Watching" })).toBeVisible();
  });

  test("Search palette opens with Ctrl+K and finds a story", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("habit-progress")).toBeVisible(); // shell (and the palette) mounted
    await page.keyboard.press("Control+k");
    const box = page.getByRole("combobox", { name: "Search everything" });
    await expect(box).toBeVisible();
    await box.fill("Nimbus");
    await expect(page.getByRole("dialog", { name: "Search" }).locator("li[role=option]").first()).toBeVisible({ timeout: 20_000 });
    await page.keyboard.press("Escape");
    await expect(box).toBeHidden();
  });

  test("Library: markdown export downloads", async ({ page }) => {
    await page.goto("/library?tab=export");
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("link", { name: "Download" }).first().click(),
    ]);
    expect(download.suggestedFilename()).toBe("signal-vault.zip");
  });

  test("Analytics renders after entering a baseline post", async ({ page }) => {
    await page.goto("/analytics");
    const form = page.getByRole("form", { name: "Baseline post" });
    await expect(form).toBeVisible();
    await form.getByLabel("Posted on").fill("2026-10-01");
    await form.getByLabel("Post URL").fill("https://linkedin.example/posts/baseline-1");
    await form.getByLabel("Impressions").fill("1200");
    await form.getByLabel("Reactions").fill("30");
    await form.getByLabel("Comments").fill("4");
    await form.getByRole("button", { name: "Add baseline post" }).click();
    await expect(page.getByTestId("toast").filter({ hasText: "Baseline post added" })).toBeVisible();
    await expect(page.getByTestId("platform-summary").or(page.getByTestId("analytics-empty"))).toBeVisible();
    await expect(page.getByRole("heading", { name: "Experiments" })).toBeVisible();
  });

  test("Ops: costs budget bar and evals report", async ({ page }) => {
    test.setTimeout(180_000);
    await page.goto("/ops?tab=costs");
    await expect(page.getByTestId("budget-bar")).toBeVisible();
    await page.getByRole("tab", { name: "Evals" }).click();
    const evals = page.getByTestId("evals");
    await expect(evals).toBeVisible();
    if (await evals.getByText("No eval run yet.").isVisible()) {
      await evals.getByRole("button", { name: "Run evals" }).click();
    }
    await expect(evals.getByTestId("eval-metrics")).toBeVisible({ timeout: 150_000 });
  });
});
