// Live highlighting of AI-tell issues (§7.5): the API returns issues with [start, end) spans into the text it
// scanned. These helpers re-locate those spans in the text being edited and split it into marked segments.

export type Severity = "error" | "warn";

export type SpanIssue = { type: string; message: string; start: number; end: number; severity: string };

export type HlSegment = { text: string; severity?: Severity; messages: string[] };

const sev = (s: string): Severity => (s === "error" ? "error" : "warn");

/**
 * Move issue spans from `original` (what the server scanned) into `current` (what is in the editor now): the
 * flagged snippet is searched in `current`, preferring the occurrence closest to its old position. Issues
 * without a span, or whose snippet no longer exists, are dropped (they still appear in the issue list).
 */
export function relocate(issues: SpanIssue[], original: string, current: string): SpanIssue[] {
  const out: SpanIssue[] = [];
  for (const i of issues) {
    if (i.start < 0 || i.end <= i.start || i.end > original.length) continue;
    const snippet = original.slice(i.start, i.end);
    if (!snippet) continue;
    if (original === current) {
      out.push(i);
      continue;
    }
    let best = -1;
    let from = 0;
    for (;;) {
      const at = current.indexOf(snippet, from);
      if (at < 0) break;
      if (best < 0 || Math.abs(at - i.start) < Math.abs(best - i.start)) best = at;
      from = at + 1;
    }
    if (best >= 0) out.push({ ...i, start: best, end: best + snippet.length });
  }
  return out;
}

/**
 * Split text into segments by issue spans. Overlapping spans merge their messages; an "error" anywhere in an
 * overlap wins over "warn". Out-of-range spans are clamped; empty or inverted spans are ignored.
 */
export function splitHighlights(text: string, issues: SpanIssue[]): HlSegment[] {
  const n = text.length;
  const valid = issues
    .map((i) => ({ ...i, start: Math.max(0, i.start), end: Math.min(n, i.end) }))
    .filter((i) => i.end > i.start);
  if (!valid.length) return text ? [{ text, messages: [] }] : [];
  const cuts = new Set<number>([0, n]);
  for (const i of valid) {
    cuts.add(i.start);
    cuts.add(i.end);
  }
  const points = [...cuts].sort((a, b) => a - b);
  const out: HlSegment[] = [];
  for (let k = 0; k < points.length - 1; k++) {
    const a = points[k];
    const b = points[k + 1];
    if (a === b) continue;
    const covering = valid.filter((i) => i.start <= a && i.end >= b);
    const seg: HlSegment = { text: text.slice(a, b), messages: covering.map((i) => i.message) };
    if (covering.length) seg.severity = covering.some((i) => sev(i.severity) === "error") ? "error" : "warn";
    const prev = out[out.length - 1];
    if (prev && prev.severity === seg.severity && prev.messages.join("|") === seg.messages.join("|")) prev.text += seg.text;
    else out.push(seg);
  }
  return out;
}

const URL_RE = /https?:\/\/\S+/g;
const EMOJI_RE = /\p{Extended_Pictographic}/gu;
const HASHTAG_RE = /(^|\s)#\w+/g;

/** Client-side mirror of signal_core.studio.aitell.counters, for live counts while typing. */
export function countText(text: string) {
  const lines = text.split("\n").filter((l) => l.trim());
  return {
    words: text.replace(URL_RE, "").split(/\s+/).filter(Boolean).length,
    chars: text.length,
    lines: lines.length,
    emoji: (text.match(EMOJI_RE) ?? []).length,
    hashtags: (text.match(HASHTAG_RE) ?? []).length,
  };
}
