import { describe, expect, it } from "vitest";
import { keyToCommand, navReducer, type NavState } from "../keynav";

describe("navReducer", () => {
  const s0: NavState = { index: -1, count: 3 };

  it("j/k move focus within bounds, starting from nothing focused", () => {
    let s = navReducer(s0, { type: "next" });
    expect(s.index).toBe(0);
    s = navReducer(navReducer(navReducer(s, { type: "next" }), { type: "next" }), { type: "next" });
    expect(s.index).toBe(2);
    s = navReducer(s, { type: "prev" });
    expect(s.index).toBe(1);
    expect(navReducer({ index: 0, count: 3 }, { type: "prev" }).index).toBe(0);
    expect(navReducer({ index: -1, count: 3 }, { type: "prev" }).index).toBe(0);
  });

  it("is a no-op on an empty list and clamps when the list shrinks", () => {
    expect(navReducer({ index: -1, count: 0 }, { type: "next" })).toEqual({ index: -1, count: 0 });
    expect(navReducer({ index: 5, count: 6 }, { type: "count", count: 2 })).toEqual({ index: 1, count: 2 });
    expect(navReducer({ index: 1, count: 3 }, { type: "set", index: 9 }).index).toBe(2);
  });
});

describe("keyToCommand", () => {
  const div = { tagName: "DIV" } as unknown as EventTarget;
  it("maps the §10.2 shortcuts", () => {
    expect(["j", "k", "u", "x", "p", "b", "l", "o", "?"].map((key) => keyToCommand({ key, target: div }))).toEqual([
      "next",
      "prev",
      "useful",
      "skip",
      "post",
      "build",
      "learn",
      "open",
      "help",
    ]);
    expect(keyToCommand({ key: "Enter", target: div })).toBe("open");
    expect(keyToCommand({ key: "z", target: div })).toBeNull();
  });

  it("ignores typing in fields, modifier chords and Enter on buttons", () => {
    expect(keyToCommand({ key: "j", target: { tagName: "INPUT" } as unknown as EventTarget })).toBeNull();
    expect(keyToCommand({ key: "u", target: { tagName: "TEXTAREA" } as unknown as EventTarget })).toBeNull();
    expect(keyToCommand({ key: "j", target: { tagName: "DIV", isContentEditable: true } as unknown as EventTarget })).toBeNull();
    expect(keyToCommand({ key: "k", ctrlKey: true, target: div })).toBeNull();
    expect(keyToCommand({ key: "Enter", target: { tagName: "BUTTON" } as unknown as EventTarget })).toBeNull();
  });
});
