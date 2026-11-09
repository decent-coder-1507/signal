"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, Lightbulb, Upload } from "lucide-react";
import { useState } from "react";
import { LineChart } from "@/components/charts";
import { PageTitle } from "@/components/shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, inputClass } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { api, get, post, put } from "@/lib/api";
import { errMsg } from "@/lib/hooks";
import { fmtDate, fmtDateTime, humanize } from "@/lib/labels";
import { safeUrl } from "@/lib/safe-url";

type PlatformSummary = {
  posts: number;
  median_impressions: number | null;
  median_engagement: number | null;
  baseline: { impressions: number; engagement: number; posts: number } | null;
  vs_baseline_impressions: number | null;
  trend: { date: string; impressions: number; engagement: number }[];
};
type Summary = {
  by_platform: Record<string, PlatformSummary>;
  breakdowns: Record<string, Record<string, { n: number; median_engagement: number; caution: boolean }>>;
  top_posts: { publication_id: string; platform: string; url: string; published_at: string; impressions: number; engagement: number; variables: Record<string, unknown> }[];
  posts_measured: number;
};
type Publication = { id: string; platform: string; url: string; published_at: string; is_baseline: boolean; variables: Record<string, unknown> };
type Experiment = {
  id: string;
  name: string;
  variable: string;
  variants: string[];
  start: string;
  end: string | null;
  result: { variants: Record<string, { n: number; median_engagement: number }>; winner: string | null; note: string } | null;
};
type Learning = {
  id: string;
  created_at: string;
  status: string;
  findings: string[];
  voice_rule_changes: Record<string, unknown>;
  add_banned_phrases: string[];
  best_times: Record<string, string[]>;
  angle_preferences: string[];
  caveats: string;
};

const pct = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);
const num = (v: number | null | undefined) => (v == null ? "—" : Math.round(v).toLocaleString("en-IN"));

export default function AnalyticsPage() {
  const q = useQuery({ queryKey: ["analytics", "summary"], queryFn: () => get<Summary>("/analytics/summary") });
  const s = q.data;
  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <PageTitle sub="Your posts against your own baseline — directional, small samples flagged.">Analytics</PageTitle>
      {q.isLoading ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : q.error ? (
        <p className="text-sm text-bad">{errMsg(q.error)}</p>
      ) : (
        s && (
          <>
            {Object.keys(s.by_platform).length === 0 ? (
              <Card data-testid="analytics-empty">
                <p className="text-sm text-muted">No measured posts yet. Add a few baseline posts below so SIGNAL has something to compare against.</p>
              </Card>
            ) : (
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3" data-testid="platform-summary">
                {Object.entries(s.by_platform).map(([p, v]) => (
                  <Card key={p}>
                    <div className="mb-2 flex items-baseline justify-between">
                      <h2 className="tracking-tight text-lg font-semibold">{humanize(p)}</h2>
                      <span className="text-xs text-muted">{v.posts} posts</span>
                    </div>
                    <dl className="grid grid-cols-3 gap-2 text-center">
                      <div>
                        <dd className="num text-xl font-semibold">{num(v.median_impressions)}</dd>
                        <dt className="text-[11px] text-muted">median impr.</dt>
                      </div>
                      <div>
                        <dd className="num text-xl font-semibold">{pct(v.median_engagement)}</dd>
                        <dt className="text-[11px] text-muted">median eng.</dt>
                      </div>
                      <div>
                        <dd className={`num text-xl font-semibold ${v.vs_baseline_impressions == null ? "" : v.vs_baseline_impressions >= 1 ? "text-good" : "text-warn"}`}>
                          {v.vs_baseline_impressions == null ? "—" : `${v.vs_baseline_impressions.toFixed(2)}×`}
                        </dd>
                        <dt className="text-[11px] text-muted">vs baseline</dt>
                      </div>
                    </dl>
                    <div className="mt-2">
                      <LineChart label={`${p} impressions trend`} points={v.trend.map((t) => ({ x: t.date, y: t.impressions }))} baseline={v.baseline?.impressions ?? null} />
                    </div>
                    {!v.baseline && <p className="mt-1 text-xs text-muted">No baseline yet for {humanize(p)}.</p>}
                  </Card>
                ))}
              </div>
            )}
            {Object.keys(s.breakdowns).length > 0 && <Breakdowns b={s.breakdowns} />}
            {s.top_posts.length > 0 && (
              <Card>
                <h2 className="card-title mb-2">Top posts</h2>
                <ol className="space-y-1.5 text-sm">
                  {s.top_posts.map((t) => (
                    <li key={t.publication_id} className="flex flex-wrap items-center gap-2">
                      <Badge tone="muted">{humanize(t.platform)}</Badge>
                      {safeUrl(t.url) ? (
                        <a href={safeUrl(t.url)} target="_blank" rel="noopener noreferrer" className="min-w-0 flex-1 truncate hover:underline">
                          {t.url}
                        </a>
                      ) : (
                        <span className="min-w-0 flex-1 truncate">{t.url}</span>
                      )}
                      <span className="text-xs tabular-nums text-muted">
                        {num(t.impressions)} impr · {pct(t.engagement)} · {fmtDate(t.published_at)}
                      </span>
                    </li>
                  ))}
                </ol>
              </Card>
            )}
          </>
        )
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <BaselineForm />
        <MetricsForm />
      </div>
      <CsvImport />
      <Experiments />
      <Learnings />
    </div>
  );
}

function Breakdowns({ b }: { b: Summary["breakdowns"] }) {
  return (
    <Card>
      <h2 className="card-title mb-1">What seems to work</h2>
      <p className="mb-3 text-xs text-muted">Median engagement per variable value. Rows marked “small sample” are noise until proven otherwise.</p>
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {Object.entries(b).map(([variable, vals]) => (
          <div key={variable} className="min-w-0">
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">{humanize(variable)}</h3>
            <table className="w-full text-sm">
              <tbody>
                {Object.entries(vals)
                  .sort((a, c) => c[1].median_engagement - a[1].median_engagement)
                  .map(([v, r]) => (
                    <tr key={v} className="border-t border-border">
                      <td className="py-1 pr-2">{v}</td>
                      <td className="py-1 text-right tabular-nums">{pct(r.median_engagement)}</td>
                      <td className="py-1 pl-2 text-right text-xs text-muted">
                        n={r.n} {r.caution && <Badge tone="warn">small sample</Badge>}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </Card>
  );
}

function useRefresh() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ["analytics"] });
}

function BaselineForm() {
  const toast = useToast();
  const refresh = useRefresh();
  const [platform, setPlatform] = useState("linkedin");
  const [url, setUrl] = useState("");
  const [date, setDate] = useState("");
  const [impressions, setImpressions] = useState("");
  const [reactions, setReactions] = useState("");
  const [comments, setComments] = useState("");
  const [reposts, setReposts] = useState("");
  const add = useMutation({
    mutationFn: () =>
      post("/analytics/baseline", {
        platform,
        url: url.trim(),
        published_at: new Date(`${date}T09:00:00`).toISOString(),
        impressions: Number(impressions) || 0,
        reactions: Number(reactions) || 0,
        comments: Number(comments) || 0,
        reposts: Number(reposts) || 0,
      }),
    onSuccess: () => {
      toast("Baseline post added", "good");
      setUrl("");
      setImpressions("");
      setReactions("");
      setComments("");
      setReposts("");
      refresh();
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const n = (label: string, v: string, set: (x: string) => void) => (
    <Field label={label}>
      <input type="number" min={0} className={inputClass} value={v} onChange={(e) => set(e.target.value)} />
    </Field>
  );
  return (
    <Card>
      <h2 className="card-title mb-1">Add a baseline post</h2>
      <p className="mb-3 text-xs text-muted">One of your last 10 posts from before SIGNAL — the yardstick for everything after.</p>
      <form
        className="space-y-3"
        aria-label="Baseline post"
        onSubmit={(e) => {
          e.preventDefault();
          if (safeUrl(url.trim()) && date) add.mutate();
        }}
      >
        <div className="grid grid-cols-2 gap-2">
          <Field label="Platform">
            <select className={inputClass} value={platform} onChange={(e) => setPlatform(e.target.value)}>
              <option value="linkedin">LinkedIn</option>
              <option value="x">X</option>
              <option value="instagram">Instagram</option>
            </select>
          </Field>
          <Field label="Posted on">
            <input type="date" className={inputClass} value={date} onChange={(e) => setDate(e.target.value)} required />
          </Field>
        </div>
        <Field label="Post URL">
          <input type="url" className={inputClass} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" required />
        </Field>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {n("Impressions", impressions, setImpressions)}
          {n("Reactions", reactions, setReactions)}
          {n("Comments", comments, setComments)}
          {n("Reposts", reposts, setReposts)}
        </div>
        <Button type="submit" variant="primary" disabled={!safeUrl(url.trim()) || !date || !impressions || add.isPending}>
          Add baseline post
        </Button>
      </form>
    </Card>
  );
}

function MetricsForm() {
  const toast = useToast();
  const refresh = useRefresh();
  const pubs = useQuery({ queryKey: ["analytics", "publications"], queryFn: () => get<Publication[]>("/publications") });
  const own = (pubs.data ?? []).filter((p) => !p.is_baseline);
  const [pid, setPid] = useState("");
  const [horizon, setHorizon] = useState<"48h" | "7d" | "custom">("48h");
  const [vals, setVals] = useState<Record<string, string>>({});
  const fields = ["impressions", "reactions", "comments", "reposts", "saves", "profile_views", "followers_gained"];
  const add = useMutation({
    mutationFn: () => post<{ engagement: number }>(`/publications/${pid || own[0]?.id}/metrics`, { horizon, ...Object.fromEntries(fields.map((f) => [f, Number(vals[f]) || 0])) }),
    onSuccess: (r) => {
      toast(`Recorded — engagement ${pct(r.engagement)}`, "good");
      setVals({});
      refresh();
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const chosen = pid || own[0]?.id || "";
  return (
    <Card>
      <h2 className="card-title mb-1">Log metrics for a post</h2>
      <p className="mb-3 text-xs text-muted">Check at 48 h and 7 days — a one-minute habit.</p>
      {own.length === 0 ? (
        <p className="text-sm text-muted">No published posts yet. Mark a draft as Posted in Studio first.</p>
      ) : (
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate();
          }}
        >
          <div className="grid grid-cols-[1fr_auto] gap-2">
            <Field label="Post">
              <select className={inputClass} value={chosen} onChange={(e) => setPid(e.target.value)}>
                {own.map((p) => (
                  <option key={p.id} value={p.id}>
                    {humanize(p.platform)} · {fmtDate(p.published_at)} · {p.url.slice(0, 40)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Horizon">
              <select className={inputClass} value={horizon} onChange={(e) => setHorizon(e.target.value as typeof horizon)}>
                <option value="48h">48 h</option>
                <option value="7d">7 days</option>
                <option value="custom">Other</option>
              </select>
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {fields.map((f) => (
              <Field key={f} label={humanize(f)}>
                <input type="number" className={inputClass} value={vals[f] ?? ""} onChange={(e) => setVals((v) => ({ ...v, [f]: e.target.value }))} />
              </Field>
            ))}
          </div>
          <Button type="submit" variant="primary" disabled={add.isPending}>
            Save metrics
          </Button>
        </form>
      )}
    </Card>
  );
}

function CsvImport() {
  const toast = useToast();
  const refresh = useRefresh();
  const [file, setFile] = useState<File | null>(null);
  const [platform, setPlatform] = useState("linkedin");
  const imp = useMutation({
    mutationFn: () => {
      const f = new FormData();
      f.set("file", file!);
      return api<Record<string, number>>(`/metrics/import-csv?platform=${platform}`, { method: "POST", form: f });
    },
    onSuccess: (r) => {
      toast(`Imported: ${Object.entries(r).map(([k, v]) => `${v} ${k}`).join(", ")}`, "good");
      refresh();
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  return (
    <Card>
      <h2 className="card-title mb-2">Import a CSV export</h2>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (file) imp.mutate();
        }}
      >
        <Field label="Platform">
          <select className={inputClass} value={platform} onChange={(e) => setPlatform(e.target.value)}>
            <option value="linkedin">LinkedIn</option>
            <option value="x">X</option>
          </select>
        </Field>
        <label className="text-sm">
          <span className="sr-only">CSV file</span>
          <input type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="block text-sm file:mr-2 file:rounded-md file:border file:border-border file:bg-surface-2 file:px-3 file:py-1.5" />
        </label>
        <Button type="submit" disabled={!file || imp.isPending}>
          <Upload size={14} aria-hidden /> Import
        </Button>
      </form>
    </Card>
  );
}

const VARIABLES = ["hook_type", "length_bucket", "format", "time_slot", "emoji_count", "voice_version", "label"];

function Experiments() {
  const toast = useToast();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["analytics", "experiments"], queryFn: () => get<Experiment[]>("/experiments") });
  const [name, setName] = useState("");
  const [variable, setVariable] = useState("hook_type");
  const [variants, setVariants] = useState("");
  const [start, setStart] = useState(() => new Date().toISOString().slice(0, 10));
  const refresh = () => qc.invalidateQueries({ queryKey: ["analytics", "experiments"] });
  const add = useMutation({
    mutationFn: () => post("/experiments", { name: name.trim(), variable, variants: variants.split(",").map((v) => v.trim()).filter(Boolean), start }),
    onSuccess: () => {
      toast("Experiment started", "good");
      setName("");
      setVariants("");
      refresh();
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const end = useMutation({ mutationFn: (id: string) => put(`/experiments/${id}`, {}), onSuccess: refresh, onError: (e) => toast(errMsg(e), "bad") });
  const running = (q.data ?? []).some((e) => !e.end);
  return (
    <Card>
      <h2 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
        <FlaskConical size={16} aria-hidden /> Experiments
      </h2>
      <p className="mb-3 text-xs text-muted">One variable at a time; results stay directional until each variant has enough posts.</p>
      <ul className="mb-4 space-y-2">
        {(q.data ?? []).map((e) => (
          <li key={e.id} className="rounded-md border border-border p-3 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium">{e.name}</span>
              <span className="flex items-center gap-2 text-xs text-muted">
                {humanize(e.variable)} · {fmtDate(e.start)} – {e.end ? fmtDate(e.end) : "running"}
                {!e.end && (
                  <Button size="sm" variant="ghost" onClick={() => end.mutate(e.id)}>
                    End now
                  </Button>
                )}
              </span>
            </div>
            {e.result && (
              <div className="mt-2">
                <table className="w-full text-xs">
                  <tbody>
                    {e.variants.map((v) => (
                      <tr key={v} className="border-t border-border">
                        <td className="py-1">
                          {v} {e.result?.winner === v && <Badge tone="good">leading</Badge>}
                        </td>
                        <td className="py-1 text-right tabular-nums">{pct(e.result?.variants[v]?.median_engagement)}</td>
                        <td className="py-1 text-right text-muted">n={e.result?.variants[v]?.n ?? 0}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-1 text-xs text-warn">{e.result.note}</p>
              </div>
            )}
          </li>
        ))}
      </ul>
      {!running && (
        <form
          className="grid gap-2 sm:grid-cols-[1fr_10rem_1fr_9rem_auto] sm:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate();
          }}
        >
          <Field label="Name">
            <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} required />
          </Field>
          <Field label="Variable">
            <select className={inputClass} value={variable} onChange={(e) => setVariable(e.target.value)}>
              {VARIABLES.map((v) => (
                <option key={v} value={v}>
                  {humanize(v)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Variants" hint="Comma-separated, at least two.">
            <input className={inputClass} value={variants} onChange={(e) => setVariants(e.target.value)} required />
          </Field>
          <Field label="Start">
            <input type="date" className={inputClass} value={start} onChange={(e) => setStart(e.target.value)} />
          </Field>
          <Button type="submit" disabled={!name.trim() || variants.split(",").filter((v) => v.trim()).length < 2 || add.isPending}>
            Start
          </Button>
        </form>
      )}
    </Card>
  );
}

function Learnings() {
  const toast = useToast();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["analytics", "learnings"], queryFn: () => get<Learning[]>("/analytics/learnings") });
  const refresh = () => qc.invalidateQueries({ queryKey: ["analytics", "learnings"] });
  const gen = useMutation({ mutationFn: () => post<Learning>("/analytics/learnings"), onSuccess: refresh, onError: (e) => toast(errMsg(e), "bad") });
  const accept = useMutation({
    mutationFn: (id: string) => post<{ voice_version: number }>(`/analytics/learnings/${id}/accept`),
    onSuccess: (r) => {
      refresh();
      qc.invalidateQueries({ queryKey: ["voice"] });
      toast(`Accepted — voice is now v${r.voice_version}`, "good");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  return (
    <Card>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">
          <Lightbulb size={16} aria-hidden /> Learnings
        </h2>
        <Button size="sm" disabled={gen.isPending} onClick={() => gen.mutate()}>
          {gen.isPending ? "Analysing…" : "Propose learnings"}
        </Button>
      </div>
      {(q.data ?? []).length === 0 ? (
        <p className="text-sm text-muted">No proposals yet. They are generated monthly, or on demand.</p>
      ) : (
        <ul className="space-y-3">
          {(q.data ?? []).map((l) => (
            <li key={l.id} className="rounded-md border border-border p-3 text-sm">
              <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs text-muted">{fmtDateTime(l.created_at)}</span>
                {l.status === "proposed" ? (
                  <Button size="sm" variant="primary" disabled={accept.isPending} onClick={() => accept.mutate(l.id)}>
                    Accept → new voice version
                  </Button>
                ) : (
                  <Badge tone="good">{l.status}</Badge>
                )}
              </div>
              <ul className="list-disc space-y-0.5 pl-5">
                {l.findings.map((f, i) => (
                  <li key={i}>{f}</li>
                ))}
              </ul>
              {Object.keys(l.voice_rule_changes).length > 0 && (
                <p className="mt-1 text-xs">
                  <span className="text-muted">Voice changes: </span>
                  {Object.entries(l.voice_rule_changes)
                    .map(([k, v]) => `${humanize(k)} → ${Array.isArray(v) ? v.join(", ") : String(v)}`)
                    .join(" · ")}
                </p>
              )}
              {l.add_banned_phrases.length > 0 && <p className="mt-1 text-xs text-muted">Ban: {l.add_banned_phrases.join(", ")}</p>}
              {l.caveats && <p className="mt-1 text-xs text-warn">{l.caveats}</p>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
