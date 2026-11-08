"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Play, RefreshCw } from "lucide-react";
import { Fragment, useState } from "react";
import { BarChart } from "@/components/charts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { get, post, put } from "@/lib/api";
import { errMsg } from "@/lib/hooks";
import { fmtDateTime, humanize } from "@/lib/labels";
import type { Routine, Source } from "@/lib/types";

const usd = (v: number | null | undefined, d = 2) => (v == null ? "—" : `$${v.toFixed(d)}`);

type Health = {
  status: string;
  mode: string;
  checks: Record<string, unknown> & { llm: { provider: string; healthy: boolean | null; last_error: string | null } };
};

export function HealthTab() {
  const health = useQuery({ queryKey: ["health"], queryFn: () => get<Health>("/health"), refetchInterval: 30_000 });
  const h = health.data;
  return (
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
                <dd>{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
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
  );
}

type Run = { id: string; name: string; status: string; started_at: string; finished_at: string | null; cost_usd: number | null; outputs: Record<string, unknown>; log: string };

export function RunsTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const runs = useQuery({ queryKey: ["ops", "runs"], queryFn: () => get<Run[]>("/runs?limit=50") });
  const routines = useQuery({ queryKey: ["routines"], queryFn: () => get<Routine[]>("/routines") });
  const [open, setOpen] = useState<string | null>(null);
  const detail = useQuery({ queryKey: ["ops", "run", open], queryFn: () => get<Run>(`/runs/${open}`), enabled: !!open });
  const [routine, setRoutine] = useState("");
  const runNow = useMutation({
    mutationFn: (id: string) => post<Run>(`/routines/${id}/run-now`),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["ops", "runs"] });
      toast(`${r.name}: ${r.status}`, r.status === "failed" ? "bad" : "good");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const chosen = routine || routines.data?.[0]?.id || "";
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="Routine" value={chosen} onChange={(e) => setRoutine(e.target.value)} className="min-h-8 rounded-md border border-border bg-surface px-2 text-sm">
          {(routines.data ?? []).map((r) => (
            <option key={r.id} value={r.id}>
              {r.name}
            </option>
          ))}
        </select>
        <Button size="sm" disabled={!chosen || runNow.isPending} onClick={() => runNow.mutate(chosen)}>
          <Play size={14} aria-hidden /> {runNow.isPending ? "Running…" : "Run now"}
        </Button>
      </div>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full min-w-[640px] text-sm">
          <thead className="bg-surface-2 text-left text-xs text-muted">
            <tr>
              <th className="px-3 py-2 font-medium">Run</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Started</th>
              <th className="px-3 py-2 font-medium">Duration</th>
              <th className="px-3 py-2 text-right font-medium">Cost</th>
            </tr>
          </thead>
          <tbody>
            {(runs.data ?? []).map((r) => (
              <Fragment key={r.id}>
                <tr className="cursor-pointer border-t border-border hover:bg-surface-2" onClick={() => setOpen(open === r.id ? null : r.id)}>
                  <td className="px-3 py-1.5 font-mono text-xs">
                    <button type="button" aria-expanded={open === r.id} className="underline-offset-2 hover:underline">
                      {r.name}
                    </button>
                  </td>
                  <td className="px-3 py-1.5">
                    <Badge tone={r.status === "success" || r.status === "ok" ? "good" : r.status === "failed" ? "bad" : "warn"}>{r.status}</Badge>
                  </td>
                  <td className="px-3 py-1.5 text-xs text-muted">{fmtDateTime(r.started_at)}</td>
                  <td className="px-3 py-1.5 text-xs tabular-nums text-muted">
                    {r.finished_at ? `${((Date.parse(r.finished_at) - Date.parse(r.started_at)) / 1000).toFixed(1)} s` : "—"}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{usd(r.cost_usd, 3)}</td>
                </tr>
                {open === r.id && (
                  <tr className="border-t border-border bg-surface-2">
                    <td colSpan={5} className="px-3 py-2">
                      <pre data-testid="run-log" className="max-h-80 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px]">
                        {detail.data?.log || (detail.isLoading ? "Loading…" : "(empty log)")}
                      </pre>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

type Call = {
  id: string;
  created_at: string;
  task: string;
  tier: string;
  model: string;
  provider: string;
  status: string;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: number | null;
  latency_ms: number | null;
  cache_hit: boolean;
  error: string | null;
};

export function LedgerTab() {
  const [task, setTask] = useState("");
  const q = useQuery({ queryKey: ["ops", "ledger", task], queryFn: () => get<Call[]>(`/llm-calls?limit=100${task ? `&task=${encodeURIComponent(task)}` : ""}`) });
  const rows = q.data ?? [];
  const tasks = Array.from(new Set(rows.map((r) => r.task))).sort();
  return (
    <div className="space-y-3">
      <select aria-label="Filter by task" value={task} onChange={(e) => setTask(e.target.value)} className="min-h-8 rounded-md border border-border bg-surface px-2 text-sm">
        <option value="">All tasks</option>
        {tasks.map((t) => (
          <option key={t}>{t}</option>
        ))}
      </select>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full min-w-[860px] text-xs" data-testid="ledger">
          <thead className="bg-surface-2 text-left text-muted">
            <tr>
              {["When", "Task", "Tier", "Model", "Status", "Tokens in/out", "Latency", "Cost", "Cache"].map((h) => (
                <th key={h} className="px-2 py-1.5 font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} className="border-t border-border" title={c.error ?? undefined}>
                <td className="whitespace-nowrap px-2 py-1 text-muted">{fmtDateTime(c.created_at)}</td>
                <td className="px-2 py-1 font-mono">{c.task}</td>
                <td className="px-2 py-1">{c.tier}</td>
                <td className="px-2 py-1 text-muted">
                  {c.model} <span className="text-[10px]">({c.provider})</span>
                </td>
                <td className={clsx("px-2 py-1", c.status === "ok" || c.status === "success" ? "text-good" : "text-bad")}>{c.status}</td>
                <td className="px-2 py-1 tabular-nums">
                  {c.input_tokens ?? "—"} / {c.output_tokens ?? "—"}
                </td>
                <td className="px-2 py-1 tabular-nums">{c.latency_ms != null ? `${c.latency_ms} ms` : "—"}</td>
                <td className="px-2 py-1 tabular-nums">{usd(c.cost_usd, 4)}</td>
                <td className="px-2 py-1">{c.cache_hit ? "hit" : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

type Costs = {
  month_spent: number;
  limit: number;
  soft_limit?: number;
  state: "ok" | "soft" | "hard" | string;
  projected: number;
  calls_today?: number;
  max_calls_per_day?: number;
  cache_hits?: number;
  note?: string;
  by_day: { date: string; cost: number }[];
  by_task: { task: string; cost: number; calls: number }[];
  by_tier: { tier: string; cost: number; calls: number }[];
  by_routine: { routine: string; cost: number }[];
};

export function CostsTab() {
  const q = useQuery({ queryKey: ["ops", "costs"], queryFn: () => get<Costs>("/costs") });
  const c = q.data;
  if (!c) return <p className="text-sm text-muted">{q.error ? errMsg(q.error) : "Loading…"}</p>;
  const soft = c.soft_limit ?? c.limit * 0.8;
  const pctOf = (v: number) => `${Math.min(100, (v / Math.max(c.limit, 1e-9)) * 100)}%`;
  return (
    <div className="space-y-4">
      <Card data-testid="budget">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold">Budget this month</h2>
          <Badge tone={c.state === "ok" ? "good" : c.state === "soft" ? "warn" : "bad"}>{c.state}</Badge>
        </div>
        <p className="mt-1 font-serif text-2xl font-semibold tabular-nums">
          {usd(c.month_spent)} <span className="text-sm font-normal text-muted">of {usd(c.limit, 0)} · projected {usd(c.projected)}</span>
        </p>
        <div
          className="relative mt-3 h-3 rounded-full bg-surface-2"
          role="progressbar"
          aria-label="Budget used"
          aria-valuemin={0}
          aria-valuemax={c.limit}
          aria-valuenow={c.month_spent}
          data-testid="budget-bar"
        >
          <div className={clsx("h-full rounded-full", c.state === "hard" ? "bg-bad" : c.state === "soft" ? "bg-warn" : "bg-accent")} style={{ width: pctOf(c.month_spent) }} />
          <div className="absolute inset-y-[-3px] w-px border-l border-dashed border-text/60" style={{ left: pctOf(c.projected) }} title={`projected ${usd(c.projected)}`} />
          <div className="absolute inset-y-[-4px] w-0.5 bg-warn" style={{ left: pctOf(soft) }} title={`soft limit ${usd(soft)}`} />
          <div className="absolute inset-y-[-4px] right-0 w-0.5 bg-bad" title={`hard limit ${usd(c.limit)}`} />
        </div>
        <p className="mt-2 text-xs text-muted">
          Soft limit {usd(soft)} (cheaper tiers) · hard limit {usd(c.limit)} (deterministic fallbacks)
          {c.calls_today != null && ` · ${c.calls_today}${c.max_calls_per_day ? ` / ${c.max_calls_per_day}` : ""} calls today`}
          {c.cache_hits != null && ` · ${c.cache_hits} cache hits`}
        </p>
        {c.note && <p className="mt-1 text-xs text-muted">{c.note}</p>}
      </Card>
      <Card>
        <h2 className="mb-2 text-sm font-semibold">By day</h2>
        <BarChart label="Cost by day" bars={c.by_day.map((d) => ({ x: d.date, y: d.cost }))} format={(v) => `$${v.toFixed(2)}`} />
      </Card>
      <div className="grid gap-4 md:grid-cols-3">
        <CostTable title="By task" rows={c.by_task.map((r) => [r.task, r.cost, r.calls])} />
        <CostTable title="By tier" rows={c.by_tier.map((r) => [r.tier, r.cost, r.calls])} />
        <CostTable title="By routine" rows={c.by_routine.map((r) => [r.routine, r.cost, null])} />
      </div>
    </div>
  );
}

function CostTable({ title, rows }: { title: string; rows: [string, number, number | null][] }) {
  return (
    <Card>
      <h2 className="mb-2 text-sm font-semibold">{title}</h2>
      {rows.length === 0 ? (
        <p className="text-sm text-muted">—</p>
      ) : (
        <table className="w-full text-xs">
          <tbody>
            {rows.map(([k, cost, calls]) => (
              <tr key={k} className="border-t border-border">
                <td className="py-1 font-mono">{k}</td>
                <td className="py-1 text-right tabular-nums">{usd(cost, 3)}</td>
                {calls != null && <td className="py-1 text-right tabular-nums text-muted">{calls}×</td>}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

type EvalReport = {
  id: string;
  created_at: string;
  passed: boolean;
  metrics: Record<string, { value: number; target: number; passed: boolean }>;
  regressions?: string[];
  cases?: Record<string, number>;
  user_reports?: number;
  provider?: string;
};

export function EvalsTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["ops", "evals"], queryFn: () => get<EvalReport | null>("/evals/report") });
  const run = useMutation({
    mutationFn: () => post<EvalReport>("/evals/run"),
    onSuccess: (r) => {
      qc.setQueryData(["ops", "evals"], r);
      toast(r.passed ? "Evals passed" : "Evals failed — see metrics", r.passed ? "good" : "bad");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const r = q.data;
  return (
    <div className="space-y-3" data-testid="evals">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted">{r ? `Last run ${fmtDateTime(r.created_at)}${r.provider ? ` · ${r.provider}` : ""}` : "No eval run yet."}</p>
        <Button size="sm" variant={r ? "secondary" : "primary"} disabled={run.isPending} onClick={() => run.mutate()}>
          <RefreshCw size={14} aria-hidden /> {run.isPending ? "Running evals…" : "Run evals"}
        </Button>
      </div>
      {r && (
        <Card>
          <div className="mb-2 flex items-center gap-2">
            <Badge tone={r.passed ? "good" : "bad"}>{r.passed ? "passed" : "failed"}</Badge>
            {!!r.regressions?.length && <span className="text-xs text-bad">Regressions: {r.regressions.join(", ")}</span>}
          </div>
          <table className="w-full text-sm" data-testid="eval-metrics">
            <thead className="text-left text-xs text-muted">
              <tr>
                <th className="py-1 font-medium">Metric</th>
                <th className="py-1 text-right font-medium">Value</th>
                <th className="py-1 text-right font-medium">Target</th>
                <th className="py-1 text-right font-medium" />
              </tr>
            </thead>
            <tbody>
              {Object.entries(r.metrics ?? {}).map(([k, m]) => (
                <tr key={k} className="border-t border-border">
                  <td className="py-1">{humanize(k)}</td>
                  <td className="py-1 text-right tabular-nums">{typeof m.value === "number" ? m.value.toFixed(3) : String(m.value)}</td>
                  <td className="py-1 text-right tabular-nums text-muted">{typeof m.target === "number" ? m.target.toFixed(2) : String(m.target)}</td>
                  <td className="py-1 text-right">{m.passed ? <span className="text-good">✓</span> : <span className="text-bad">✗</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {(r.cases || r.user_reports != null) && (
            <p className="mt-2 text-xs text-muted">
              {r.cases && Object.entries(r.cases).map(([k, v]) => `${v} ${k} cases`).join(" · ")}
              {r.user_reports != null && ` · ${r.user_reports} from “Report inaccuracy”`}
            </p>
          )}
        </Card>
      )}
    </div>
  );
}

export function SourceHealthTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["sources"], queryFn: () => get<Source[]>("/sources") });
  const refresh = () => qc.invalidateQueries({ queryKey: ["sources"] });
  const patch = useMutation({
    mutationFn: (v: { id: string; enabled: boolean }) => put(`/sources/${v.id}`, { enabled: v.enabled }),
    onSuccess: (_d, v) => {
      refresh();
      toast(v.enabled ? "Re-enabled — flag cleared" : "Disabled", "good");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const fetchNow = useMutation({
    mutationFn: (id: string) => post<{ status: string; error: string | null }>(`/sources/${id}/fetch`),
    onSuccess: (r) => {
      refresh();
      toast(r.error ? `Still failing: ${r.error}` : "Fetched fine", r.error ? "bad" : "good");
    },
  });
  const rows = [...(q.data ?? [])].sort((a, b) => Number(!!b.health?.flagged) - Number(!!a.health?.flagged) || (b.health?.consecutive_failures ?? 0) - (a.health?.consecutive_failures ?? 0));
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full min-w-[700px] text-sm">
        <thead className="bg-surface-2 text-left text-xs text-muted">
          <tr>
            <th className="px-3 py-2 font-medium">Source</th>
            <th className="px-3 py-2 font-medium">Health</th>
            <th className="px-3 py-2 font-medium">Usefulness</th>
            <th className="px-3 py-2 font-medium">Last fetched</th>
            <th className="px-3 py-2" />
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.id} className={clsx("border-t border-border", s.health?.flagged && "bg-warn/5")}>
              <td className="px-3 py-1.5">
                <span className="font-medium">{s.name}</span> <span className="text-xs text-muted">{s.type}</span>
                {!s.enabled && <Badge tone="muted">disabled</Badge>}
              </td>
              <td className="px-3 py-1.5 text-xs">
                {s.health?.flagged ? (
                  <span className="text-warn">{String(s.health.flagged)}</span>
                ) : (s.health?.consecutive_failures ?? 0) > 0 ? (
                  <span className="text-warn">{s.health?.consecutive_failures} failures</span>
                ) : (
                  <span className="text-good">ok</span>
                )}
              </td>
              <td className="px-3 py-1.5 tabular-nums text-xs">{s.usefulness != null ? s.usefulness.toFixed(2) : "—"}</td>
              <td className="px-3 py-1.5 text-xs text-muted">{fmtDateTime(s.last_fetched_at)}</td>
              <td className="whitespace-nowrap px-3 py-1.5 text-right">
                {s.health?.flagged || !s.enabled ? (
                  <Button size="sm" variant="ghost" onClick={() => patch.mutate({ id: s.id, enabled: true })}>
                    Fix &amp; re-enable
                  </Button>
                ) : null}
                {s.enabled && (
                  <Button size="sm" variant="ghost" onClick={() => patch.mutate({ id: s.id, enabled: false })}>
                    Disable
                  </Button>
                )}
                <Button size="sm" variant="ghost" disabled={fetchNow.isPending} onClick={() => fetchNow.mutate(s.id)}>
                  Retry
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type Job = { id: string; name: string; key: string; status: string; attempts: number; error: string | null; updated_at: string };

export function DeadLettersTab() {
  const q = useQuery({ queryKey: ["ops", "dead"], queryFn: () => get<Job[]>("/ops/jobs?status=dead") });
  const rows = q.data ?? [];
  if (q.isLoading) return <p className="text-sm text-muted">Loading…</p>;
  if (!rows.length) return <p className="text-sm text-muted">No dead-lettered jobs. Everything retried successfully.</p>;
  return (
    <ul className="space-y-2">
      {rows.map((j) => (
        <li key={j.id} className="rounded-lg border border-border bg-surface p-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-mono">{j.name}</span>
            <span className="text-xs text-muted">
              {j.attempts} attempts · {fmtDateTime(j.updated_at)}
            </span>
          </div>
          <p className="break-all font-mono text-xs text-muted">{j.key}</p>
          {j.error && <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-words text-xs text-bad">{j.error}</pre>}
        </li>
      ))}
    </ul>
  );
}
