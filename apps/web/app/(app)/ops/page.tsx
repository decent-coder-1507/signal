"use client";

import { useQuery } from "@tanstack/react-query";
import { PageTitle } from "@/components/shell";
import { get } from "@/lib/api";

type Health = {
  status: string;
  mode: string;
  checks: Record<string, unknown> & { llm: { provider: string; healthy: boolean | null; last_error: string | null } };
};

export default function OpsPage() {
  const health = useQuery({ queryKey: ["health"], queryFn: () => get<Health>("/health"), refetchInterval: 30_000 });
  const h = health.data;
  return (
    <div>
      <PageTitle sub="Runs, LLM ledger, evals and source health">Ops</PageTitle>
      <section className="rounded-lg border border-border bg-surface p-4" aria-label="System health">
        <h2 className="text-sm font-medium">System health</h2>
        {h ? (
          <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
            <dt className="text-muted">Status</dt>
            <dd data-testid="health-status" className={h.status === "ok" ? "text-good" : "text-warn"}>
              {h.status}
            </dd>
            <dt className="text-muted">Mode</dt>
            <dd>{h.mode}</dd>
            {Object.entries(h.checks)
              .filter(([k]) => k !== "llm")
              .map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-muted">{k}</dt>
                  <dd>{String(v)}</dd>
                </div>
              ))}
            <dt className="text-muted">LLM provider</dt>
            <dd>
              {h.checks.llm.provider}
              {h.checks.llm.healthy === false && <span className="ml-1 text-bad">(unavailable)</span>}
            </dd>
          </dl>
        ) : (
          <p className="mt-2 text-sm text-muted">Checking…</p>
        )}
        {h?.checks.llm.last_error && <p className="mt-2 text-sm text-bad">{h.checks.llm.last_error}</p>}
      </section>
    </div>
  );
}
