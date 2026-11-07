import { expect, type Page } from "@playwright/test";

export const EMAIL = "owner@e2e.local";
export const PASSWORD = "e2e-password-123";

type Cookie = Awaited<ReturnType<ReturnType<Page["context"]>["cookies"]>>[number];
let cachedSession: Cookie[] | null = null;

async function uiLogin(page: Page) {
  for (let attempt = 0; attempt < 2; attempt++) {
    await page.goto("/login");
    await page.getByLabel("Email").fill(EMAIL);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    const alert = page.getByRole("form", { name: "Sign in" }).getByRole("alert");
    await Promise.race([
      page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 15_000 }),
      alert.waitFor({ timeout: 15_000 }),
    ]).catch(() => undefined);
    // The API rate-limits logins (10/min per IP); wait the window out once if a long run hits it.
    if (await alert.filter({ hasText: "too many" }).isVisible()) {
      await page.waitForTimeout(61_000);
      continue;
    }
    await expect(page).not.toHaveURL(/\/login/);
    cachedSession = (await page.context().cookies()).filter((c) => c.name.startsWith("signal_"));
    return;
  }
  throw new Error("login rate-limited twice");
}

/**
 * Signs in. A fresh e2e DB is not onboarded, so this may land on /onboarding — both are fine. After the first UI
 * login in a worker the session cookies are reused, which keeps long runs under the API's login rate limit.
 */
export async function login(page: Page) {
  if (cachedSession) {
    await page.context().addCookies(cachedSession);
    const res = await page.request.get("/api/me");
    if (res.ok()) {
      const me = (await res.json()) as { onboarded: boolean };
      await page.goto(me.onboarded ? "/" : "/onboarding");
      return;
    }
    cachedSession = null;
  }
  await uiLogin(page);
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

/** The M3 spec onboards through the UI; other specs must not depend on run order. */
export async function ensureOnboarded(page: Page) {
  const me = await apiCall<{ onboarded: boolean }>(page, "GET", "/me");
  if (!me.onboarded)
    await apiCall(page, "POST", "/onboarding/complete", { role: "AI engineer", goals: ["Ship production LLM systems"] });
}

export async function storyIds(page: Page, n = 5): Promise<string[]> {
  const r = await apiCall<{ items: { id: string }[] }>(page, "GET", `/stories?limit=${n}`);
  return r.items.map((x) => x.id);
}
