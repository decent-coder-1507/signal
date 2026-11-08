import { describe, expect, it } from "vitest";
import { initialPalette, isPaletteShortcut, paletteReducer, resultTarget, type SearchResult } from "../search-palette";
import { parseAll, SseParser, sseJson } from "../sse";

describe("SSE parsing", () => {
  it("parses token and done events across arbitrary chunk boundaries", () => {
    const raw = 'event: token\ndata: "Nimbus AI "\n\nevent: token\ndata: "released Nimbus-4 "\n\nevent: done\ndata: {"thread_id":"t1","citations":[]}\n\n';
    const p = new SseParser();
    const evs = [];
    for (let i = 0; i < raw.length; i += 7) evs.push(...p.feed(raw.slice(i, i + 7)));
    evs.push(...p.end());
    expect(evs.map((e) => e.event)).toEqual(["token", "token", "done"]);
    expect(evs.slice(0, 2).map((e) => sseJson<string>(e.data)).join("")).toBe("Nimbus AI released Nimbus-4 ");
    expect(sseJson<{ thread_id: string }>(evs[2].data)).toEqual({ thread_id: "t1", citations: [] });
  });

  it("handles CRLF, comments, multi-line data and a trailing event without blank line", () => {
    const evs = parseAll(': keep-alive\r\nevent: token\r\ndata: a\r\ndata: b\r\n\r\nevent: done\ndata: {}');
    expect(evs).toEqual([
      { event: "token", data: "a\nb" },
      { event: "done", data: "{}" },
    ]);
    expect(sseJson("not json")).toBe("not json");
  });
});

const r = (id: string, kind = "story", extra: Partial<SearchResult> = {}): SearchResult => ({
  id,
  kind,
  title: id,
  snippet: "",
  url: null,
  href: `/stories/${id}`,
  date: null,
  ...extra,
});

describe("search palette reducer", () => {
  it("opens, wraps selection and resets on new results", () => {
    let s = paletteReducer(initialPalette, { type: "toggle" });
    expect(s.open).toBe(true);
    s = paletteReducer(s, { type: "query", query: "nimbus" });
    s = paletteReducer(s, { type: "results", results: [r("a"), r("b"), r("c")] });
    s = paletteReducer(s, { type: "move", delta: -1 });
    expect(s.active).toBe(2);
    s = paletteReducer(s, { type: "move", delta: 1 });
    expect(s.active).toBe(0);
    s = paletteReducer(s, { type: "query", query: "" });
    expect(s.results).toEqual([]);
    expect(paletteReducer(s, { type: "move", delta: 1 })).toBe(s);
    expect(paletteReducer(s, { type: "toggle" }).open).toBe(false);
  });

  it("detects ⌘K / Ctrl+K and maps result targets safely", () => {
    expect(isPaletteShortcut({ key: "k", metaKey: true })).toBe(true);
    expect(isPaletteShortcut({ key: "K", ctrlKey: true })).toBe(true);
    expect(isPaletteShortcut({ key: "k" })).toBe(false);
    expect(resultTarget(r("s1"))).toEqual({ href: "/stories/s1", external: false });
    expect(resultTarget(r("i0", "item", { url: "https://n.example/a", href: "/stories/s9" }))).toEqual({ href: "/stories/s9", external: false });
    expect(resultTarget(r("i1", "item", { url: "https://n.example/a", href: null }))).toEqual({ href: "https://n.example/a", external: true });
    expect(resultTarget(r("i2", "item", { url: "javascript:alert(1)", href: null }))).toBeNull();
    expect(resultTarget(r("e1", "explainer", { href: "/gym?tab=explain&topic=KV-cache&depth=deep" }))).toEqual({
      href: "/gym?tab=explain&topic=KV-cache&depth=deep",
      external: false,
    });
    expect(resultTarget(r("x", "story", { href: "//evil.example" }))).toBeNull();
  });
});
