// Citation markers in generated text look like `[0193…uuid]` (or `[r:uuid]` for raw-material facts, §9.8).
// We never show raw ids: each marker becomes a numbered footnote that links to the cited source.

export type Citation = {
  id: string;
  url?: string | null;
  source?: string | null;
  title?: string | null;
  tier?: number | null;
  role?: string | null;
};

export type CitationRef = Citation & { n: number };

export type Segment = { kind: "text"; text: string } | { kind: "cite"; ref: CitationRef };

export const CITE_RE = /\[(r:)?([0-9a-fA-F-]{8,36})\]/g;

/** Number citations by their position in the list (1-based), so numbering is stable across fields of a story. */
export function citationIndex(citations: Citation[] | null | undefined): Map<string, CitationRef> {
  const m = new Map<string, CitationRef>();
  (citations ?? []).forEach((c) => {
    if (!m.has(c.id)) m.set(c.id, { ...c, n: m.size + 1 });
  });
  return m;
}

/**
 * Split text into plain-text and citation segments. Markers whose id is not in the index are dropped
 * (they cannot be resolved to a stored item), and whitespace left before a dropped marker is trimmed.
 * Adjacent duplicate markers collapse into one footnote.
 */
export function parseCitations(text: string | null | undefined, index: Map<string, CitationRef>): Segment[] {
  if (!text) return [];
  const out: Segment[] = [];
  let last = 0;
  let prevCite: string | null = null;
  const push = (t: string) => {
    if (!t) return;
    const prev = out[out.length - 1];
    if (prev && prev.kind === "text") prev.text += t;
    else out.push({ kind: "text", text: t });
  };
  for (const m of text.matchAll(CITE_RE)) {
    const start = m.index ?? 0;
    const between = text.slice(last, start);
    if (between.trim()) prevCite = null;
    const ref = index.get(m[2]) ?? index.get(m[2].toLowerCase());
    if (ref) {
      push(between.replace(/\s+$/, ""));
      if (prevCite !== ref.id) out.push({ kind: "cite", ref });
      prevCite = ref.id;
    } else {
      push(between.replace(/\s+$/, ""));
    }
    last = start + m[0].length;
  }
  push(text.slice(last));
  return out;
}

/** Plain text with all markers removed (for titles, aria labels, clipboard). */
export function stripCitations(text: string | null | undefined): string {
  if (!text) return "";
  return text.replace(/\s*\[(r:)?[0-9a-fA-F-]{8,36}\]/g, "").trim();
}

export function citationTooltip(c: Citation): string {
  return [c.source, c.title].filter(Boolean).join(" — ") || c.url || "source";
}
