import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../api";

afterEach(() => vi.restoreAllMocks());

describe("api client", () => {
  it("sends the CSRF cookie as a header on writes", async () => {
    document.cookie = "signal_csrf=tok123";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { headers: { "content-type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await api("/settings", { method: "PUT", body: { a: 1 } });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/settings");
    expect(init.headers["x-csrf-token"]).toBe("tok123");
    expect(init.credentials).toBe("include");
  });

  it("throws ApiError with the server detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "nope" }), { status: 403, headers: { "content-type": "application/json" } }),
      ),
    );
    await expect(api("/x")).rejects.toEqual(new ApiError(403, "nope"));
  });
});
