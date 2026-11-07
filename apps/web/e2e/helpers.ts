import { expect, type Page } from "@playwright/test";

export const EMAIL = "owner@e2e.local";
export const PASSWORD = "e2e-password-123";

/** Signs in. A fresh e2e DB is not onboarded, so this may land on /onboarding — both are fine. */
export async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

async function csrf(page: Page): Promise<string> {
  const c = (await page.context().cookies()).find((x) => x.name === "signal_csrf");
  return c ? decodeURIComponent(c.value) : "";
}

/** Authenticated JSON call through the web origin's /api proxy (uses the page's session cookies). */
export async function apiCall<T = unknown>(page: Page, method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  const res = await page.request.fetch(`/api${path}`, {
    method,
    headers: method === "GET" ? {} : { "x-csrf-token": await csrf(page), "content-type": "application/json" },
    data: method === "GET" ? undefined : JSON.stringify(body ?? {}),
  });
  expect(res.ok(), `${method} ${path} → ${res.status()}`).toBeTruthy();
  return (await res.json()) as T;
}

/** Makes sure a brief exists (tests must not depend on the onboarding spec having run first). */
export async function ensureBrief(page: Page) {
  const latest = await apiCall<{ id: string } | null>(page, "GET", "/briefs/latest");
  if (!latest) await apiCall(page, "POST", "/briefs/generate", { kind: "daily" });
}
