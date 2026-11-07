import { expect, test, type Page } from "@playwright/test";
import { apiCall, ensureOnboarded, login, storyIds } from "./helpers";

async function openPostDialog(page: Page, storyId: string) {
  await page.goto(`/stories/${storyId}`);
  await page.getByRole("group", { name: "Story actions" }).getByRole("button", { name: "Post", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByTestId("angle").first()).toBeVisible({ timeout: 30_000 });
  return dialog;
}

test.describe.serial("M4/M5 Studio", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await ensureOnboarded(page);
  });

  test("ask-me: answer becomes a raw-material bank entry", async ({ page }) => {
    test.setTimeout(120_000);
    const [, , sid] = await storyIds(page);
    const dialog = await openPostDialog(page, sid);
    await dialog.locator('[data-testid=angle][data-needs-input="true"]').first().click();
    await dialog.getByRole("button", { name: /^Draft \d/ }).click();
    await expect(page).toHaveURL(/\/studio\/drafts\//);
    const ask = page.getByTestId("ask-me");
    await expect(ask).toBeVisible();
    const answer = "We ran a coding agent on our monorepo last sprint and it caught two flaky tests.";
    await ask.locator("textarea").first().fill(answer);
    await ask.getByRole("button", { name: "Use my answers" }).click();
    await expect(page.getByTestId("scorecard")).toBeVisible({ timeout: 60_000 });

    await page.goto("/studio?tab=raw");
    await expect(page.getByTestId("raw-material").filter({ hasText: answer })).toBeVisible();
  });

  test("story → angle → LinkedIn draft → thread → approve → publish-assist → Published", async ({ page }) => {
    test.setTimeout(180_000);
    const [sid] = await storyIds(page);
    const dialog = await openPostDialog(page, sid);
    await dialog.locator("[data-testid=angle]:not([data-needs-input])").first().click();
    // exactly LinkedIn
    for (const cb of await dialog.getByRole("checkbox").all()) {
      const name = (await cb.evaluate((el) => el.parentElement?.textContent ?? "")).trim();
      if (name.startsWith("LinkedIn") && !name.includes("carousel")) await cb.check();
      else await cb.uncheck();
    }
    await dialog.getByRole("button", { name: "Draft 1 post" }).click();
    await expect(page).toHaveURL(/\/studio\/drafts\//, { timeout: 60_000 });
    await expect(page.getByTestId("scorecard")).toBeVisible();
    await expect(page.getByTestId("score-total")).toBeVisible();
    await expect(page.getByTestId("counters")).toContainText("Words");
    const linkedinUrl = page.url();

    // Repurpose → X thread
    await page.getByRole("group", { name: "Repurpose" }).getByRole("button", { name: "X thread" }).click();
    await expect(page).not.toHaveURL(linkedinUrl, { timeout: 60_000 });
    const posts = page.getByTestId("thread-post");
    await expect(posts.first()).toBeVisible();
    const n = await posts.count();
    expect(n).toBeGreaterThanOrEqual(4);
    expect(n).toBeLessThanOrEqual(10);
    await expect(page.getByRole("navigation", { name: "Platform versions" }).getByRole("link", { name: "LinkedIn" })).toBeVisible();
    const draftId = page.url().split("/").pop()!;

    // Approve (with an override when the quality gate blocks)
    await page.getByRole("button", { name: "Approve" }).click();
    const assistBtn = page.getByRole("button", { name: "Publish-assist" });
    await expect(assistBtn.or(page.getByTestId("gate-reasons"))).toBeVisible();
    if (await page.getByTestId("gate-reasons").isVisible()) {
      await page.getByLabel("Override reason").fill("Reviewed manually; numbers checked against the sources");
      await page.getByRole("button", { name: "Override with reason" }).click();
    }
    await expect(assistBtn).toBeVisible();

    // Publish-assist → Posted
    await assistBtn.click();
    const assist = page.getByRole("dialog", { name: "Publish-assist" });
    await expect(assist.getByTestId("assist-text")).toBeVisible();
    await assist.getByLabel("Posted URL").fill("https://x.example/srijoy/status/123");
    await assist.getByRole("button", { name: "Posted" }).click();
    await expect(page.getByTestId("publish-panel")).toContainText("published");

    await page.goto("/studio");
    await expect(page.getByTestId("column-published").locator(`a[href="/studio/drafts/${draftId}"]`)).toBeVisible();
  });

  test("carousel draft renders ≥ 6 slide images", async ({ page }) => {
    test.setTimeout(240_000);
    const [, sid] = await storyIds(page);
    const ideas = await apiCall<{ id: string; needs_input: unknown[] }[]>(page, "POST", "/studio/angles", { seed_type: "story", seed_id: sid });
    const idea = ideas.find((i) => i.needs_input.length === 0) ?? ideas[0];
    const [draft] = await apiCall<{ id: string }[]>(page, "POST", "/studio/drafts", {
      content_idea_id: idea.id,
      platforms: ["instagram_carousel"],
      skip_questions: true,
    });
    await page.goto(`/studio/drafts/${draft.id}`);
    await expect(page.getByTestId("slide-editor")).toBeVisible();
    await page.getByRole("button", { name: /^(Render|Re-render)$/ }).click();
    const imgs = page.getByTestId("slide-image");
    await expect(imgs.nth(5)).toBeVisible({ timeout: 180_000 });
    expect(await imgs.count()).toBeGreaterThanOrEqual(6);
    // images actually load through the authenticated proxy
    const src = await imgs.first().getAttribute("src");
    const res = await page.request.get(src!);
    expect(res.status(), `GET ${src}`).toBe(200);
    expect(res.headers()["content-type"]).toContain("image/png");
    await expect
      .poll(() => imgs.first().evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0), { timeout: 15_000 })
      .toBe(true);
  });
});
