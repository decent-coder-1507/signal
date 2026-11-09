import type { ReactNode } from "react";

export type Tone = "neutral" | "accent" | "good" | "warn" | "bad" | "info" | "muted" | "hot";

/** Chip (ADR-025): soft fills in light, outlined mono chips in dark. Styling lives in globals.css `.chip`. */
export function Badge({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className="chip" data-tone={tone}>
      {children}
    </span>
  );
}
