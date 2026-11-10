import { expect, test } from "@playwright/test";
import { apiCall, ensureBrief, ensureOnboarded, login, PASSWORD } from "./helpers";

// ADR-027: trust + in-app usage — demo badge, "How this brief was made", report inaccuracy, change password,
// engine quality, install card, Telegram gone from Channels.
test.describe.serial("Trust and in-app usage", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await ensureOnboarded(page);
  });

  test("demo-data badge in the shell @mobile", async ({ page }) => {
    await page.goto("/");
    const badge = page.locator('[data-testid="mode-badge"]:visible');
    await expect(badge).toHaveCount(1);
    await expect(badge).toHaveText("Demo data");
    await expect(badge).toHaveAttribute("data-mode", "mock");
  });

  test("brief: how it was made + report inaccuracy on a story card", async ({ page }) => {
    await ensureBrief(page);
    await page.goto("/brief");
    const card = page.getByTestId("story-card").first();
    await expect(card).toBeVisible();

    const panel = page.getByTestId("brief-provenance");
    await panel.getByText("How this brief was made").click();
    await expect(panel.getByTestId("prov-shown")).toHaveText(/^\d+/);
    await expect(panel.getByTestId("prov-citations")).toHaveText(/^\d+ \/ \d+$/);
    await expect(panel.getByTestId("prov-degraded")).toHaveText(/^(yes|no)$/);
    await expect(panel.getByTestId("prov-ai-calls")).toHaveText(/^\d+/);

    await card.getByRole("button", { name: "Report inaccuracy" }).click();
    await expect(card.getByRole("button", { name: "Reported as inaccurate" })).toBeDisabled();
    await expect(page.getByTestId("toast").filter({ hasText: "Reported as inaccurate" })).toBeVisible();
  });

  test("settings: change password, then change it back", async ({ page }) => {
    const next = "e2e-password-rotated-456";
    await page.goto("/settings?tab=security");
    const form = page.getByRole("form", { name: "Change password" });
    await form.getByLabel("Current password").fill(PASSWORD);
    await form.getByLabel(/^New password/).fill("too-short");
    await expect(form.getByRole("alert")).toContainText("At least 12 characters");
    await form.getByLabel(/^New password/).fill(next);
    await form.getByLabel("Repeat new password").fill(next);
    await form.getByRole("button", { name: "Change password" }).click();
    await expect(page.getByTestId("toast").filter({ hasText: "Password changed" })).toBeVisible();
    await expect(form.getByLabel("Current password")).toHaveValue("");
    // Restore, so other specs (and re-runs) can still sign in.
    await apiCall(page, "POST", "/auth/password", { current_password: next, new_password: PASSWORD });
  });

  test("channels: in-app + browser notifications, no Telegram", async ({ page }) => {
    await page.goto("/settings?tab=channels");
    await expect(page.getByTestId("browser-notify")).toBeVisible();
    await expect(page.getByRole("switch", { name: "Enable browser notifications" })).toBeVisible();
    await expect(page.getByRole("tabpanel")).not.toContainText("Telegram");
  });

  test("today: install card appears on beforeinstallprompt and can be dismissed", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("habit-progress")).toBeVisible(); // shell mounted, install listener registered
    await page.evaluate(() => {
      const e = new Event("beforeinstallprompt", { cancelable: true }) as Event & { prompt?: () => Promise<void> };
      e.prompt = async () => undefined;
      window.dispatchEvent(e);
    });
    const install = page.getByTestId("install-card");
    await expect(install).toContainText("Install SIGNAL");
    await install.getByRole("button", { name: "Dismiss install card" }).click();
    await expect(install).toBeHidden();
  });

  test("ops: engine quality shows benchmark metrics and the spot check", async ({ page }) => {
    await page.goto("/ops?tab=quality");
    const q = page.getByTestId("engine-quality");
    await expect(q).toContainText("Prefilter recall");
    await expect(q.getByTestId("bench-metrics")).toBeVisible();
    await expect(q.getByRole("button", { name: "Run benchmark" })).toBeEnabled();
    await expect(page.getByTestId("spotcheck")).toContainText(/Not reviewed yet|agree/);
  });
});
