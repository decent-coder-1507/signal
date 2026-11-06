import { expect, type Page } from "@playwright/test";

export const EMAIL = "owner@e2e.local";
export const PASSWORD = "e2e-password-123";

export async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).not.toHaveURL(/\/login/);
}
