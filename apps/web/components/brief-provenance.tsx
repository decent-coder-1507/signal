"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { useState, type ReactNode } from "react";
import { get } from "@/lib/api";
import { fmtDateTime } from "@/lib/labels";

export type Provenance = {
  brief_id: string;
  generated_at: string;
  timezone: string;
  period_start: string;
  period_end: string;
  sources: { scanned: number; fetches: number; errors: number };
  items: { in_window: number; passed_prefilter: number };
  stories: { considered: number; eligible: number | null; shown: number; quick_hits: number };
  ai: {
    scope: "run" | "window";
    calls: number;
    cached: number;
    failed: number;
    cost_usd: number;
    models: { model: string; calls: number }[];
    tasks: { task: string; calls: number }[];
  };
  citations: { total: number; verified: number };
  degraded: boolean;
  run: { id: string; name: string; status: string } | null;
};

function Row({ label, value, testId }: { label: string; value: ReactNode; testId?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border py-1.5 last:border-0">
      <dt className="text-muted">{label}</dt>
      <dd className="num text-right font-medium" data-testid={testId}>
        {value}
      </dd>
    </div>
  );
}

/** "How this brief was made" — collapsible, loads on first open. Everything comes from stored rows (no AI call). */
export function BriefProvenance({ briefId }: { briefId: string }) {
  const [open, setOpen] = useState(false);
  const q = useQuery({
    queryKey: ["brief", briefId, "provenance"],
    queryFn: () => get<Provenance>(`/briefs/${briefId}/provenance`),
    enabled: open,
  });
  const p = q.data;
  return (
    <details
      className="group mt-5 bento p-5"
      data-testid="brief-provenance"
      onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}
    >
      <summary className="card-title flex cursor-pointer list-none items-center justify-between">
        How this brief was made
        <ChevronDown size={16} className="transition-transform group-open:rotate-180" aria-hidden />
      </summary>
      {!p ? (
        <p className="mt-2 text-sm text-muted">{q.error ? "Could not load the details." : "Loading…"}</p>
      ) : (
        <div className="mt-3 grid gap-x-8 text-sm sm:grid-cols-2">
          <dl>
            <Row label="Sources scanned" value={p.sources.scanned} testId="prov-sources" />
            <Row label="Items in the window" value={p.items.in_window} testId="prov-items" />
            <Row label="Passed the prefilter" value={p.items.passed_prefilter} />
            <Row label="Stories considered" value={p.stories.eligible != null ? `${p.stories.considered} (${p.stories.eligible} above the bar)` : p.stories.considered} />
            <Row label="Stories shown" value={`${p.stories.shown}${p.stories.quick_hits ? ` + ${p.stories.quick_hits} quick hits` : ""}`} testId="prov-shown" />
          </dl>
          <dl>
            <Row
              label={p.ai.scope === "run" ? "AI calls (this run)" : "AI calls (around generation)"}
              value={`${p.ai.calls}${p.ai.cached ? ` · ${p.ai.cached} cached` : ""}${p.ai.failed ? ` · ${p.ai.failed} failed` : ""}`}
              testId="prov-ai-calls"
            />
            <Row label="Models" value={p.ai.models.length ? p.ai.models.map((m) => `${m.model} ×${m.calls}`).join(", ") : "none"} />
            <Row label="Citations verified" value={`${p.citations.verified} / ${p.citations.total}`} testId="prov-citations" />
            <Row label="Degraded" value={p.degraded ? "yes" : "no"} testId="prov-degraded" />
            <Row label="Generated" value={`${fmtDateTime(p.generated_at)} IST`} />
          </dl>
          <p className="mt-3 text-xs text-muted sm:col-span-2">
            Window {fmtDateTime(p.period_start)} → {fmtDateTime(p.period_end)}.{" "}
            {p.run ? `Routine ${p.run.name} (${p.run.status}).` : "Generated on demand."} Citations count as verified when they still
            resolve to a stored source item; every story sentence was checked against its sources when it was written.
          </p>
        </div>
      )}
    </details>
  );
}
