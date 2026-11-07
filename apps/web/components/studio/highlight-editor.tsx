"use client";

import clsx from "clsx";
import { useRef } from "react";
import { countText, splitHighlights, type SpanIssue } from "@/lib/highlight";

const SHARED = "whitespace-pre-wrap break-words px-3 py-2 font-sans text-[15px] leading-relaxed";

/**
 * Textarea with live AI-tell highlights: a backdrop renders the same text with <mark>s behind a transparent
 * textarea, scrolled in sync. Errors are red, warnings amber; hovering a word shows nothing (textarea is on
 * top), so the issue list next to the editor carries the messages.
 */
export function HighlightEditor({
  value,
  onChange,
  issues,
  label,
  minRows = 8,
  testId,
}: {
  value: string;
  onChange: (v: string) => void;
  issues: SpanIssue[];
  label: string;
  minRows?: number;
  testId?: string;
}) {
  const back = useRef<HTMLDivElement>(null);
  const segs = splitHighlights(value, issues);
  return (
    <div className="relative rounded-md border border-border bg-surface focus-within:border-accent">
      <div ref={back} aria-hidden className={clsx(SHARED, "pointer-events-none absolute inset-0 overflow-hidden text-transparent")}>
        {segs.map((s, i) =>
          s.severity ? (
            <mark
              key={i}
              data-severity={s.severity}
              className={clsx("rounded-sm text-transparent", s.severity === "error" ? "bg-bad/25" : "bg-warn/25")}
            >
              {s.text}
            </mark>
          ) : (
            <span key={i}>{s.text}</span>
          ),
        )}
        {/* keep a trailing newline visible so heights match */}
        {"\n"}
      </div>
      <textarea
        aria-label={label}
        data-testid={testId}
        value={value}
        rows={Math.max(minRows, value.split("\n").length + 1)}
        onChange={(e) => onChange(e.target.value)}
        onScroll={(e) => {
          if (back.current) back.current.scrollTop = e.currentTarget.scrollTop;
        }}
        className={clsx(SHARED, "relative block w-full resize-y bg-transparent text-text caret-text outline-none")}
      />
    </div>
  );
}

export function Counters({ text, limit, testId = "counters" }: { text: string; limit?: number; testId?: string }) {
  const c = countText(text);
  return (
    <dl data-testid={testId} className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted">
      {(
        [
          ["Words", c.words],
          ["Lines", c.lines],
          ["Emoji", c.emoji],
          ["Hashtags", c.hashtags],
        ] as const
      ).map(([k, v]) => (
        <div key={k} className="flex gap-1">
          <dt>{k}</dt>
          <dd className="tabular-nums text-text">{v}</dd>
        </div>
      ))}
      <div className="flex gap-1">
        <dt>Chars</dt>
        <dd className={clsx("tabular-nums", limit && c.chars > limit ? "font-semibold text-bad" : "text-text")}>
          {c.chars}
          {limit ? ` / ${limit}` : ""}
        </dd>
      </div>
    </dl>
  );
}
