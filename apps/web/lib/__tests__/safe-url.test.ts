import { describe, expect, it } from "vitest";
import { safeUrl } from "../safe-url";

describe("safeUrl", () => {
  it("allows only absolute http(s) URLs", () => {
    expect(safeUrl("https://nimbus.example/post?a=1")).toBe("https://nimbus.example/post?a=1");
    expect(safeUrl("http://news.example/x")).toBe("http://news.example/x");
    expect(safeUrl("javascript:alert(1)")).toBeUndefined();
    expect(safeUrl("JaVaScRiPt:alert(1)")).toBeUndefined();
    expect(safeUrl("data:text/html,<script>alert(1)</script>")).toBeUndefined();
    expect(safeUrl("/relative/path")).toBeUndefined();
    expect(safeUrl("not a url")).toBeUndefined();
    expect(safeUrl(null)).toBeUndefined();
    expect(safeUrl(undefined)).toBeUndefined();
  });
});
