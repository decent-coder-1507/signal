import clsx from "clsx";
import type { ReactNode } from "react";

export type Tone = "neutral" | "accent" | "good" | "warn" | "bad" | "info" | "muted";

export function Badge({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={clsx(
        "inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium leading-4",
        tone === "neutral" && "border-border bg-surface-2 text-text",
        tone === "muted" && "border-border text-muted",
        tone === "accent" && "border-accent/40 bg-accent/10 text-accent",
        tone === "good" && "border-good/40 bg-good/10 text-good",
        tone === "warn" && "border-warn/40 bg-warn/10 text-warn",
        tone === "bad" && "border-bad/40 bg-bad/10 text-bad",
        tone === "info" && "border-info/40 bg-info/10 text-info",
      )}
    >
      {children}
    </span>
  );
}
