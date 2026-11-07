import type { ReactNode } from "react";
import { safeUrl } from "./safe-url";

// Tiny, safe Markdown renderer for article previews: headings, paragraphs, lists, block quotes, fenced code,
// inline code/bold/italic/links. Builds React nodes (never raw HTML), links pass the http(s) allowlist.

function inline(text: string, key: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)\s]+\))/g;
  let last = 0;
  let k = 0;
  for (const m of text.matchAll(re)) {
    const i = m.index ?? 0;
    if (i > last) out.push(text.slice(last, i));
    const t = m[0];
    const id = `${key}-${k++}`;
    if (t.startsWith("`")) out.push(<code key={id} className="rounded bg-surface-2 px-1 font-mono text-[0.9em]">{t.slice(1, -1)}</code>);
    else if (t.startsWith("**")) out.push(<strong key={id}>{t.slice(2, -2)}</strong>);
    else if (t.startsWith("*")) out.push(<em key={id}>{t.slice(1, -1)}</em>);
    else {
      const lm = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(t)!;
      const href = safeUrl(lm[2]);
      out.push(
        href ? (
          <a key={id} href={href} target="_blank" rel="noopener noreferrer">
            {lm[1]}
          </a>
        ) : (
          lm[1]
        ),
      );
    }
    last = i + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ source }: { source: string }) {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let b = 0;
  // drop YAML front-matter
  if (lines[0]?.trim() === "---") {
    const end = lines.indexOf("---", 1);
    if (end > 0) i = end + 1;
  }
  while (i < lines.length) {
    const line = lines[i];
    const key = `b${b++}`;
    if (!line.trim()) {
      i++;
      continue;
    }
    if (line.startsWith("```")) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) code.push(lines[i++]);
      i++;
      blocks.push(
        <pre key={key} className="overflow-x-auto rounded-md bg-surface-2 p-3 font-mono text-xs">
          <code>{code.join("\n")}</code>
        </pre>,
      );
      continue;
    }
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) {
      const level = h[1].length;
      const cls = level <= 2 ? "mt-4 font-serif text-xl font-semibold" : "mt-3 font-semibold";
      blocks.push(level <= 2 ? <h3 key={key} className={cls}>{inline(h[2], key)}</h3> : <h4 key={key} className={cls}>{inline(h[2], key)}</h4>);
      i++;
      continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items: string[] = [];
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, ""));
      const lis = items.map((t, j) => <li key={j}>{inline(t, `${key}-${j}`)}</li>);
      blocks.push(ordered ? <ol key={key} className="list-decimal space-y-1 pl-5">{lis}</ol> : <ul key={key} className="list-disc space-y-1 pl-5">{lis}</ul>);
      continue;
    }
    if (line.startsWith(">")) {
      const q: string[] = [];
      while (i < lines.length && lines[i].startsWith(">")) q.push(lines[i++].replace(/^>\s?/, ""));
      blocks.push(
        <blockquote key={key} className="border-l-2 border-accent/60 pl-3 text-muted">
          {inline(q.join(" "), key)}
        </blockquote>,
      );
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|>|\s*([-*]|\d+\.)\s)/.test(lines[i])) para.push(lines[i++]);
    blocks.push(<p key={key}>{inline(para.join(" "), key)}</p>);
  }
  return <div className="prose-signal space-y-3 text-[15px] leading-relaxed">{blocks}</div>;
}
