import { describe, expect, it } from "vitest";
import { countText, relocate, splitHighlights, type SpanIssue } from "../highlight";

const issue = (start: number, end: number, severity = "error", message = "m"): SpanIssue => ({
  type: "t",
  message,
  start,
  end,
  severity,
});

describe("splitHighlights", () => {
  it("returns the whole text when there are no spans", () => {
    expect(splitHighlights("hello", [])).toEqual([{ text: "hello", messages: [] }]);
    expect(splitHighlights("", [])).toEqual([]);
  });

  it("marks spans with their severity and keeps the text intact", () => {
    const t = "This is a game-changer — really.";
    const segs = splitHighlights(t, [issue(10, 22, "warn", "ai"), issue(23, 24, "error", "dash")]);
    expect(segs.map((s) => s.text).join("")).toBe(t);
    expect(segs.find((s) => s.text === "game-changer")).toMatchObject({ severity: "warn", messages: ["ai"] });
    expect(segs.find((s) => s.text === "—")).toMatchObject({ severity: "error", messages: ["dash"] });
  });

  it("merges overlaps (error wins) and ignores invalid spans", () => {
    const segs = splitHighlights("abcdefgh", [issue(1, 5, "warn", "w"), issue(3, 7, "error", "e"), issue(-1, -1), issue(5, 2)]);
    expect(segs).toEqual([
      { text: "a", messages: [] },
      { text: "bc", severity: "warn", messages: ["w"] },
      { text: "de", severity: "error", messages: ["w", "e"] },
      { text: "fg", severity: "error", messages: ["e"] },
      { text: "h", messages: [] },
    ]);
  });

  it("clamps spans past the end", () => {
    expect(splitHighlights("abc", [issue(1, 99)])).toEqual([
      { text: "a", messages: [] },
      { text: "bc", severity: "error", messages: ["m"] },
    ]);
  });
});

describe("relocate", () => {
  it("follows the flagged snippet after edits and drops vanished ones", () => {
    const orig = "We delve into it. Then delve again.";
    const cur = "Intro line. We delve into it. Then we stop.";
    const out = relocate([issue(3, 8), issue(23, 28)], orig, cur);
    expect(out).toHaveLength(2);
    expect(cur.slice(out[0].start, out[0].end)).toBe("delve");
    expect(relocate([issue(3, 8)], orig, "No such word")).toEqual([]);
    expect(relocate([issue(-1, -1)], orig, orig)).toEqual([]);
  });
});

describe("countText", () => {
  it("counts words (ignoring URLs), lines, emoji and hashtags", () => {
    expect(countText("One two https://x.example/a\n\n#ai rocks 🚀")).toEqual({
      words: 5,
      chars: 41,
      lines: 2,
      emoji: 1,
      hashtags: 1,
    });
  });
});
