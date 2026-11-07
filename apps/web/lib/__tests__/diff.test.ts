import { describe, expect, it } from "vitest";
import { diffLines, diffStats } from "../diff";

describe("diffLines", () => {
  it("marks added, removed and unchanged lines in order", () => {
    const ops = diffLines("hook\nfact one\nending?", "new hook\nfact one\nending?\nP.S.");
    expect(ops).toEqual([
      { op: "del", text: "hook" },
      { op: "add", text: "new hook" },
      { op: "same", text: "fact one" },
      { op: "same", text: "ending?" },
      { op: "add", text: "P.S." },
    ]);
    expect(diffStats(ops)).toEqual({ added: 2, removed: 1 });
  });

  it("handles empty sides and identical text", () => {
    expect(diffLines("", "a\nb")).toEqual([
      { op: "add", text: "a" },
      { op: "add", text: "b" },
    ]);
    expect(diffLines("a", "")).toEqual([{ op: "del", text: "a" }]);
    expect(diffStats(diffLines("x\ny", "x\ny"))).toEqual({ added: 0, removed: 0 });
  });
});
