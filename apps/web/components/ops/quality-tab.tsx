"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardTitle, Metric } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { get, post } from "@/lib/api";
import { errMsg } from "@/lib/hooks";
import { fmtDateTime } from "@/lib/labels";

type N = number | null;
export type BenchStatus = {
  latest: {
    variant: string | null;
    origin: "local" | "snapshot";
    finished_at: string | null;
    duration_s: N;
    note?: string;
    labels: { items: number; pairs: number; questions: number; judged: number } | null;
    metrics: {
      prefilter: { recall: N; precision: N; auc: N; recall_pop: N; pass_rate_pop: N };
      cluster: { precision: N; recall: N; f1: N };
      ranking: { "ndcg@10": N; "p@7": N };
      ask: { "recall@5": N; "recall@1": N; mrr: N } | null;
    };
  } | null;
  running: boolean;
  started_at: string | null;
  error: string | null;
  spotcheck: { rows: number; agree: number; disagree: number; reviewed: boolean };
};

const f = (v: N | undefined, d = 2) => (v == null ? "—" : v.toFixed(d));
const pct = (v: N | undefined) => (v == null ? "—" : `${Math.round(v * 100)}%`);

/** Ops → Engine quality: latest real-data benchmark (ADR-026) + the label spot check. */
export function QualityTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({
    queryKey: ["ops", "bench"],
    queryFn: () => get<BenchStatus>("/ops/bench"),
    refetchInterval: (query) => (query.state.data?.running ? 5_000 : false),
  });
  const run = useMutation({
    mutationFn: () => post<BenchStatus & { started: boolean }>("/ops/bench/run"),
    onSuccess: (r) => {
      qc.setQueryData(["ops", "bench"], r);
      toast(r.started ? "Benchmark started — this takes a few minutes" : "A benchmark is already running", "good");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const s = q.data;
  if (!s) return <p className="text-sm text-muted">{q.error ? errMsg(q.error) : "Loading…"}</p>;
  const l = s.latest;
  const m = l?.metrics;
  const sc = s.spotcheck;
  return (
    <div className="space-y-3.5" data-testid="engine-quality">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted" data-testid="bench-when">
          {s.running
            ? `Benchmark running since ${fmtDateTime(s.started_at)}…`
            : l
              ? l.origin === "snapshot"
                ? `Committed benchmark snapshot from ${fmtDateTime(l.finished_at)} (not yet run on this machine).`
                : `Last run ${fmtDateTime(l.finished_at)}${l.duration_s != null ? ` · ${Math.round(l.duration_s)} s` : ""}`
              : "No benchmark run yet."}
        </p>
        <Button size="sm" variant={l ? "secondary" : "primary"} disabled={run.isPending || s.running} onClick={() => run.mutate()}>
          <Play size={14} aria-hidden /> {s.running ? "Running…" : "Run benchmark"}
        </Button>
      </div>
      {s.error && (
        <p role="alert" className="rounded-xl border border-bad/40 bg-bad/10 px-4 py-2.5 text-sm text-bad">
          Last run failed: {s.error}
        </p>
      )}
      {m && (
        <>
          <dl className="grid grid-cols-2 gap-3.5 md:grid-cols-4">
            <Card>
              <Metric label="Prefilter recall" value={f(m.prefilter.recall)} unit={`AUC ${f(m.prefilter.auc)}`} />
            </Card>
            <Card>
              <Metric label="Clustering F1" value={f(m.cluster.f1)} unit={`P ${f(m.cluster.precision)} · R ${f(m.cluster.recall)}`} />
            </Card>
            <Card>
              <Metric label="Ranking NDCG@10" value={f(m.ranking["ndcg@10"])} unit={`P@7 ${f(m.ranking["p@7"])}`} />
            </Card>
            <Card>
              <Metric label="Ask recall@5" value={f(m.ask?.["recall@5"])} unit={m.ask ? `MRR ${f(m.ask.mrr)}` : "not run"} />
            </Card>
          </dl>
          <Card>
            <CardTitle aside={l?.variant ?? undefined}>Details</CardTitle>
            <table className="w-full text-sm" data-testid="bench-metrics">
              <tbody>
                {[
                  ["Prefilter precision (sample)", f(m.prefilter.precision)],
                  ["Prefilter recall, corpus estimate", f(m.prefilter.recall_pop)],
                  ["Prefilter pass rate, corpus estimate", pct(m.prefilter.pass_rate_pop)],
                  ["Ask recall@1", f(m.ask?.["recall@1"])],
                  [
                    "Labelled set",
                    l?.labels ? `${l.labels.items} items · ${l.labels.pairs} pairs · ${l.labels.questions} questions · ${l.labels.judged} judged` : "—",
                  ],
                ].map(([k, v]) => (
                  <tr key={k} className="border-t border-border first:border-0">
                    <td className="py-1.5 text-muted">{k}</td>
                    <td className="py-1.5 text-right tabular-nums">{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-xs text-muted">
              Real-data benchmark (ADR-026): 300 items labelled by Claude, replayed through the product engines. Labels are model
              judgements, never shown as facts.{l?.note ? ` Note: ${l.note}.` : ""}
            </p>
          </Card>
        </>
      )}
      <Card data-testid="spotcheck">
        <CardTitle>Label spot check</CardTitle>
        {sc.reviewed ? (
          <p className="text-sm">
            <Badge tone={sc.disagree > 5 ? "bad" : "good"}>
              {sc.agree} / {sc.agree + sc.disagree} agree
            </Badge>{" "}
            <span className="text-muted">
              {sc.agree + sc.disagree < sc.rows ? `${sc.rows - sc.agree - sc.disagree} of ${sc.rows} still unmarked. ` : ""}
              {sc.disagree > 5 ? "More than 5 disagreements: the labeller prompt needs work before trusting the numbers." : ""}
            </span>
          </p>
        ) : (
          <p className="text-sm text-muted">
            Not reviewed yet. Mark each of the {sc.rows} rows in <code>fixtures/bench/SPOTCHECK.md</code> y or n.
          </p>
        )}
      </Card>
    </div>
  );
}
