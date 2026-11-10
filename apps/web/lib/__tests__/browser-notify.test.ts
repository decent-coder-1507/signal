import { describe, expect, it } from "vitest";
import { freshNotifications, notificationBody, notificationHref, notificationTitle } from "../browser-notify";
import type { Notification } from "../types";

const n = (id: string, kind: string, created_at: string, payload: Record<string, unknown> = {}, read = false): Notification => ({
  id,
  kind,
  created_at,
  payload,
  read,
});

describe("browser notifications", () => {
  it("shows only unread, interrupt-worthy notifications newer than the opt-in, oldest first", () => {
    const list = [
      n("3", "watch", "2026-11-10T08:00:00Z", { watch: "MCP", title: "MCP spec v2", story_id: "s1" }),
      n("2", "brief", "2026-11-10T07:30:00Z", { brief_id: "b1", title: "Your daily brief is ready (6 stories)" }),
      n("1", "brief", "2026-11-09T07:30:00Z", { brief_id: "b0" }),
      n("4", "metrics_prompt", "2026-11-10T09:00:00Z"),
      n("5", "cards", "2026-11-10T09:30:00Z", { due: 3, title: "3 cards due for review" }, true),
    ];
    expect(freshNotifications(list, "2026-11-10T00:00:00Z").map((x) => x.id)).toEqual(["2", "3"]);
    expect(freshNotifications(list, null)).toEqual([]); // not opted in yet → nothing old floods in
  });

  it("titles and links each kind", () => {
    const watch = n("3", "watch", "2026-11-10T08:00:00Z", { watch: "MCP", title: "MCP spec v2", story_id: "s1" });
    expect(notificationTitle(watch)).toBe("Watch fired: MCP");
    expect(notificationBody(watch)).toBe("MCP spec v2");
    expect(notificationHref(watch)).toBe("/stories/s1");
    const brief = n("2", "brief", "2026-11-10T07:30:00Z", { brief_id: "b1", title: "Your daily brief is ready" });
    expect(notificationTitle(brief)).toBe("Your daily brief is ready");
    expect(notificationHref(brief)).toBe("/brief");
    expect(notificationHref(n("6", "weekly", "x", { brief_id: "w" }))).toBe("/reviews");
    expect(notificationHref(n("7", "cards", "x", { due: 2 }))).toBe("/gym");
    expect(notificationTitle(n("7", "cards", "x", { due: 2 }))).toBe("Cards are due");
  });
});
