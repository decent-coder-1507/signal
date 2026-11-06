import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("login, shell and green health @mobile", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("Email").fill("owner@e2e.local");
  await page.getByLabel("Password").fill("wrong-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("form", { name: "Sign in" }).getByRole("alert")).toContainText("invalid credentials");

  await login(page);
  await page.goto("/ops");
  await expect(page.getByTestId("health-status")).toHaveText("ok");
});
