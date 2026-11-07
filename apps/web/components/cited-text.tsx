import { citationTooltip, parseCitations, type CitationRef } from "@/lib/citations";

/** Text with citation markers rendered as hoverable superscript footnotes (§9.8). */
export function CitedText({ text, index }: { text: string | null | undefined; index: Map<string, CitationRef> }) {
  const segs = parseCitations(text, index);
  return (
    <>
      {segs.map((s, i) =>
        s.kind === "text" ? (
          <span key={i}>{s.text}</span>
        ) : (
          <sup key={i} className="cite" data-testid="citation">
            {s.ref.url ? (
              <a
                href={s.ref.url}
                target="_blank"
                rel="noopener noreferrer"
                title={citationTooltip(s.ref)}
                aria-label={`Source ${s.ref.n}: ${citationTooltip(s.ref)}`}
              >
                [{s.ref.n}]
              </a>
            ) : (
              <span title={citationTooltip(s.ref)}>[{s.ref.n}]</span>
            )}
          </sup>
        ),
      )}
    </>
  );
}

export function CitationList({ index }: { index: Map<string, CitationRef> }) {
  const refs = [...index.values()];
  if (!refs.length) return null;
  return (
    <ol className="space-y-1 text-xs text-muted">
      {refs.map((r) => (
        <li key={r.id} className="flex gap-1.5">
          <span className="shrink-0 tabular-nums">[{r.n}]</span>
          <span className="min-w-0 break-words">
            {r.source && <span className="font-medium text-text">{r.source}</span>}
            {r.source && (r.title || r.url) && " — "}
            {r.url ? (
              <a className="underline underline-offset-2 hover:text-text" href={r.url} target="_blank" rel="noopener noreferrer">
                {r.title || r.url}
              </a>
            ) : (
              r.title
            )}
          </span>
        </li>
      ))}
    </ol>
  );
}
