// ⌘K / Ctrl+K search palette state (§11, Library "search anywhere").

import { safeUrl } from "./safe-url";

export type SearchResult = {
  id: string;
  kind: string;
  title: string;
  snippet: string;
  url: string | null;
  href: string;
  date: string | null;
};

export type PaletteState = { open: boolean; query: string; kind: string; results: SearchResult[]; active: number };

export type PaletteAction =
  | { type: "open" }
  | { type: "close" }
  | { type: "toggle" }
  | { type: "query"; query: string }
  | { type: "kind"; kind: string }
  | { type: "results"; results: SearchResult[] }
  | { type: "move"; delta: number };

export const initialPalette: PaletteState = { open: false, query: "", kind: "", results: [], active: 0 };

export function paletteReducer(s: PaletteState, a: PaletteAction): PaletteState {
  switch (a.type) {
    case "open":
      return { ...s, open: true, active: 0 };
    case "close":
      return { ...s, open: false };
    case "toggle":
      return s.open ? { ...s, open: false } : { ...s, open: true, active: 0 };
    case "query":
      return { ...s, query: a.query, active: 0, results: a.query.trim() ? s.results : [] };
    case "kind":
      return { ...s, kind: a.kind, active: 0 };
    case "results":
      return { ...s, results: a.results, active: 0 };
    case "move": {
      const n = s.results.length;
      if (!n) return s;
      return { ...s, active: (s.active + a.delta + n) % n };
    }
  }
}

/** True for ⌘K (mac) or Ctrl+K (others). */
export function isPaletteShortcut(e: { key: string; metaKey?: boolean; ctrlKey?: boolean }): boolean {
  return e.key.toLowerCase() === "k" && !!(e.metaKey || e.ctrlKey);
}

/** Where a result goes. Items have no in-app page, so they open their original (http(s) only). */
export function resultTarget(r: SearchResult): { href: string; external: boolean } | null {
  if (r.kind === "item") {
    const u = safeUrl(r.url);
    return u ? { href: u, external: true } : null;
  }
  if (r.kind === "explainer") return { href: `/gym?tab=explain`, external: false };
  if (r.kind === "build_log") return { href: r.href.replace(/^\/lab\?log=.*/, "/lab"), external: false };
  if (r.kind === "note") return { href: "/library?tab=notes", external: false };
  return r.href.startsWith("/") && !r.href.startsWith("//") ? { href: r.href, external: false } : null;
}

export const KIND_LABEL: Record<string, string> = {
  story: "Story",
  item: "Article",
  idea: "Idea",
  note: "Note",
  explainer: "Explainer",
  build_log: "Build log",
};
