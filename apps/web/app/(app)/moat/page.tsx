"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, TrendingDown, TrendingUp } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";
import { PageTitle } from "@/components/shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { inputClass } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { get, post } from "@/lib/api";
import { errMsg } from "@/lib/hooks";
import type { MoatPoint, MoatRadar } from "@/lib/lab-types";
import { fmtDate } from "@/lib/labels";
import { safeUrl } from "@/lib/safe-url";

export default function MoatPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const latest = useQuery({ queryKey: ["moat", "latest"], queryFn: () => get<MoatRadar | null>("/moat-radar/latest") });
  const [topic, setTopic] = useState("");
  const [shown, setShown] = useState<MoatRadar | null>(null);
  const gen = useMutation({
    mutationFn: (t: string | null) => post<MoatRadar>(`/moat-radar/generate${t ? `?topic=${encodeURIComponent(t)}` : ""}`),
    onSuccess: (r) => {
      if (!r.topic) qc.setQueryData(["moat", "latest"], r);
      setShown(r.topic ? r : null);
      toast(r.topic ? `Moat Radar for “${r.topic}” ready` : "Moat Radar ready", "good");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const r = shown ?? latest.data;
  return (
    <div className="mx-auto max-w-6xl">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <PageTitle sub="What is becoming commodity, what is gaining value — and what that means for you.">Moat Radar</PageTitle>
        <Button variant="primary" disabled={gen.isPending} onClick={() => gen.mutate(null)}>
          <RefreshCw size={14} aria-hidden /> {gen.isPending ? "Generating…" : "Generate"}
        </Button>
      </div>
      <form
        className="mb-5 flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (topic.trim()) gen.mutate(topic.trim());
        }}
      >
        <label className="min-w-0 flex-1 text-sm sm:max-w-sm">
          Focus on a topic
          <input className={inputClass} value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="e.g. coding agents" />
        </label>
        <Button type="submit" disabled={!topic.trim() || gen.isPending}>
          Generate for topic
        </Button>
        {shown && (
          <Button variant="ghost" onClick={() => setShown(null)}>
            Back to monthly
          </Button>
        )}
      </form>
      {latest.isLoading ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : !r ? (
        <Card>
          <p className="text-sm text-muted">No Moat Radar yet. It runs monthly; generate one now.</p>
        </Card>
      ) : (
        <Report r={r} />
      )}
    </div>
  );
}

function Point({ p, ev }: { p: MoatPoint; ev: MoatRadar["evidence"] }) {
  return (
    <li className="space-y-0.5" data-testid="moat-point">
      <p className="font-medium">{p.claim}</p>
      {p.reasoning && <p className="text-sm text-muted">{p.reasoning}</p>}
      {p.evidence.length > 0 && (
        <p className="flex flex-wrap gap-x-2 gap-y-0.5 text-xs">
          {p.evidence.map((id, i) => {
            const e = ev[id];
            if (!e) return null;
            return (
              <span key={id} className="inline-flex items-center gap-1">
                <Link href={e.story_url.startsWith("/") ? e.story_url : `/stories/${id}`} data-testid="moat-evidence" className="text-accent underline underline-offset-2" title={e.title}>
                  [{i + 1}] {e.title.length > 48 ? e.title.slice(0, 47) + "…" : e.title}
                </Link>
                {safeUrl(e.url) && (
                  <a href={safeUrl(e.url)} target="_blank" rel="noopener noreferrer" className="text-muted" aria-label={`Original source for ${e.title}`}>
                    ↗
                  </a>
                )}
              </span>
            );
          })}
        </p>
      )}
    </li>
  );
}

function Column({ title, icon, points, ev, tone }: { title: string; icon: ReactNode; points: MoatPoint[]; ev: MoatRadar["evidence"]; tone: string }) {
  return (
    <Card>
      <h2 className={`mb-3 flex items-center gap-1.5 font-serif text-lg font-semibold ${tone}`}>
        {icon}
        {title}
      </h2>
      {points.length === 0 ? <p className="text-sm text-muted">Nothing this period.</p> : <ul className="space-y-3">{points.map((p, i) => <Point key={i} p={p} ev={ev} />)}</ul>}
    </Card>
  );
}

function Report({ r }: { r: MoatRadar }) {
  const sc = r.scorecard;
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">
        {r.topic ? `Topic: ${r.topic} · ` : ""}
        {fmtDate(r.period_start)} – {fmtDate(r.period_end)}
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        <Column title="Commoditising" icon={<TrendingDown size={18} aria-hidden />} points={r.commoditising} ev={r.evidence} tone="text-warn" />
        <Column title="Appreciating" icon={<TrendingUp size={18} aria-hidden />} points={r.appreciating} ev={r.evidence} tone="text-good" />
      </div>
      <Card>
        <h2 className="mb-3 font-serif text-lg font-semibold">For you</h2>
        <div className="grid gap-4 md:grid-cols-3">
          {(
            [
              ["Know", r.for_you.know],
              ["Learn", r.for_you.learn],
              ["Stop", r.for_you.stop],
            ] as const
          ).map(([t, pts]) => (
            <div key={t}>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{t}</h3>
              {pts.length === 0 ? <p className="text-sm text-muted">—</p> : <ul className="space-y-3 text-sm">{pts.map((p, i) => <Point key={i} p={p} ev={r.evidence} />)}</ul>}
            </div>
          ))}
        </div>
      </Card>
      <Column title="For builders" icon={null} points={r.for_builders} ev={r.evidence} tone="" />
      <Card>
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="font-serif text-lg font-semibold">Predictions scorecard</h2>
          <span className="text-sm text-muted">
            {sc.resolved} of {sc.total} resolved{sc.accuracy != null && ` · ${Math.round(sc.accuracy * 100)}% right`}
          </span>
        </div>
        {sc.items.length === 0 ? (
          <p className="text-sm text-muted">No predictions yet.</p>
        ) : (
          <ul className="space-y-2 text-sm">
            {sc.items.map((p) => (
              <li key={p.id} className="flex flex-wrap items-start justify-between gap-2">
                <span className="min-w-0 flex-1">{p.text}</span>
                <span className="flex items-center gap-1 text-xs text-muted">
                  made {fmtDate(p.made_on)} · revisit {fmtDate(p.revisit_on)}
                  <Badge tone={p.outcome === "right" ? "good" : p.outcome === "wrong" ? "bad" : "muted"}>{p.outcome ?? "open"}</Badge>
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
