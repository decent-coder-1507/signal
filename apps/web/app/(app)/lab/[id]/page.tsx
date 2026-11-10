"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowLeft, FileDown, FileText, PenLine, Skull } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type ReactNode } from "react";
import { RadarChart } from "@/components/radar-chart";
import { useStartPost } from "@/components/studio/angles-dialog";
import { ReportInaccuracy } from "@/components/report-inaccuracy";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClass } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, inputClass } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { ApiError, get, post } from "@/lib/api";
import { errMsg } from "@/lib/hooks";
import { IDEA_STATUSES, SCORE_KEYS, type IdeaDetail } from "@/lib/lab-types";
import { fmtDateTime, humanize } from "@/lib/labels";
import { Markdown } from "@/lib/markdown";
import { safeUrl } from "@/lib/safe-url";

export default function IdeaPage() {
  const { id } = useParams<{ id: string }>();
  const q = useQuery({ queryKey: ["lab", "idea", id], queryFn: () => get<IdeaDetail>(`/ideas/${id}`) });
  if (q.isLoading) return <p className="text-sm text-muted">Loading idea…</p>;
  if (!q.data)
    return <p className="text-sm text-bad">{q.error instanceof ApiError && q.error.status === 404 ? "Idea not found." : "Could not load this idea."}</p>;
  return <IdeaView idea={q.data} />;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">{title}</h2>
      <div className="text-sm">{children}</div>
    </section>
  );
}

function List({ items }: { items: string[] | null | undefined }) {
  if (!items?.length) return <p className="text-muted">—</p>;
  return (
    <ul className="list-disc space-y-0.5 pl-5">
      {items.map((x, i) => (
        <li key={i}>{x}</li>
      ))}
    </ul>
  );
}

function IdeaView({ idea: i }: { idea: IdeaDetail }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [killing, setKilling] = useState(false);
  const [reason, setReason] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: ["lab"] });
  const setStatus = useMutation({
    mutationFn: (v: { status: string; kill_reason?: string }) => post(`/ideas/${i.id}/status`, v),
    onSuccess: (_d, v) => {
      refresh();
      toast(`Moved to ${humanize(v.status)}`, "good");
      setKilling(false);
    },
    onError: (e) => toast(errMsg(e), "bad"), // capacity guard message comes back as a 422 detail
  });
  const scores = SCORE_KEYS.map((k) => i.scores?.[k] ?? 0);
  return (
    <article className="mx-auto max-w-6xl">
      <Link href="/lab" className="mb-2 inline-flex items-center gap-1 text-sm text-muted hover:text-text">
        <ArrowLeft size={14} aria-hidden /> Lab
      </Link>
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge tone="accent">{humanize(i.type)}</Badge>
        <Badge tone={i.status === "killed" ? "bad" : "muted"} >{humanize(i.status)}</Badge>
        <Badge tone="muted">Lab score {i.lab_score.toFixed(1)}</Badge>
        <Badge tone="muted">{humanize(i.origin)}</Badge>
        <ReportInaccuracy className="ml-auto" targetType="idea" targetId={i.id} context={{ block: "idea" }} />
      </div>
      <h1 className="mt-2 tracking-tight text-2xl font-semibold leading-tight md:text-3xl">{i.title}</h1>
      {i.one_liner && <p className="mt-1 text-muted">{i.one_liner}</p>}
      {i.kill_reason && <p className="mt-2 text-sm text-bad">Killed: {i.kill_reason}</p>}

      <div className="mt-4 flex flex-wrap gap-1.5" role="group" aria-label="Status">
        {IDEA_STATUSES.filter((s) => s !== "killed").map((s) => (
          <Button
            key={s}
            size="sm"
            variant={i.status === s ? "primary" : "secondary"}
            aria-pressed={i.status === s}
            disabled={setStatus.isPending || i.status === s}
            onClick={() => setStatus.mutate({ status: s })}
          >
            {humanize(s)}
          </Button>
        ))}
        <Button size="sm" variant="danger" disabled={i.status === "killed"} onClick={() => setKilling(true)}>
          <Skull size={14} aria-hidden /> Kill
        </Button>
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0 space-y-4">
          <Card className="space-y-4">
            <Section title="Problem">{i.problem || "—"}</Section>
            <Section title="Persona">{i.persona || "—"}</Section>
            <Section title="Why now">{i.why_now || "—"}</Section>
            <Section title="Solution">{i.solution || "—"}</Section>
            <div className="grid gap-4 sm:grid-cols-2">
              <Section title="MVP scope">
                <List items={i.mvp_scope} />
              </Section>
              <Section title="Not in MVP">
                <List items={i.not_in_mvp} />
              </Section>
            </div>
            <Section title="Stack">
              <div className="flex flex-wrap gap-1">
                {(i.stack ?? []).map((s) => (
                  <Badge key={s} tone="muted">
                    {s}
                  </Badge>
                ))}
                {!i.stack?.length && "—"}
              </div>
            </Section>
            <Section title="Effort">
              {i.effort && Object.keys(i.effort).length ? (
                <dl className="flex flex-wrap gap-x-4">
                  {Object.entries(i.effort).map(([k, v]) => (
                    <div key={k} className="flex gap-1">
                      <dt className="text-muted">{humanize(k)}:</dt>
                      <dd>{String(v)}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                "—"
              )}
            </Section>
            <Section title="Risks">
              <List items={i.risks} />
            </Section>
            <Section title="Moat">{i.moat || "—"}</Section>
            <Section title="Validation plan">
              <List items={i.validation_plan} />
            </Section>
            <div className="grid gap-4 sm:grid-cols-2">
              <Section title="Skills it builds">
                <List items={i.learning_skills} />
              </Section>
              <Section title="Content plan">
                <List items={i.content_plan} />
              </Section>
            </div>
          </Card>
          <BriefPanel idea={i} />
          <BuildLog idea={i} />
        </div>
        <aside className="min-w-0 space-y-4">
          <Card>
            <h2 className="label">Scores</h2>
            <RadarChart label="Idea scores" axes={SCORE_KEYS.map((k) => humanize(k))} max={10} series={[{ name: "score", values: scores, color: "var(--accent)" }]} />
            <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
              {SCORE_KEYS.map((k, n) => (
                <div key={k} className="flex justify-between">
                  <dt className="text-muted">{humanize(k)}</dt>
                  <dd className="tabular-nums">{scores[n].toFixed(1)}</dd>
                </div>
              ))}
            </dl>
          </Card>
          <Card>
            <h2 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Evidence</h2>
            {i.evidence_links.length === 0 ? (
              <p className="text-sm text-muted">No linked evidence.</p>
            ) : (
              <ul className="space-y-2 text-sm" data-testid="idea-evidence">
                {i.evidence_links.map((e, k) => (
                  <li key={k} className="break-words">
                    {safeUrl(e.url) ? (
                      <a href={safeUrl(e.url)} target="_blank" rel="noopener noreferrer" className="font-medium hover:underline">
                        {e.title}
                      </a>
                    ) : (
                      <span className="font-medium">{e.title}</span>
                    )}
                    {e.note && <p className="text-xs text-muted">{e.note}</p>}
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card>
            <h2 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Prior art</h2>
            {!i.prior_art?.length ? (
              <p className="text-sm text-muted">Nothing similar found in what SIGNAL has seen.</p>
            ) : (
              <ul className="space-y-1 text-sm">
                {i.prior_art.map((p) => (
                  <li key={p.id} className="break-words">
                    {safeUrl(p.url) ? (
                      <a href={safeUrl(p.url)} target="_blank" rel="noopener noreferrer" className="hover:underline">
                        {p.title}
                      </a>
                    ) : (
                      p.title
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </aside>
      </div>

      <Dialog open={killing} onClose={() => setKilling(false)} title="Kill this idea?">
        <p className="text-sm text-muted">Killing ideas is healthy. Say why, so future sparks learn from it.</p>
        <form
          className="mt-3 space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (reason.trim()) setStatus.mutate({ status: "killed", kill_reason: reason.trim() });
          }}
        >
          <Field label="Reason">
            <textarea className={inputClass} rows={3} value={reason} onChange={(e) => setReason(e.target.value)} required />
          </Field>
          <Button type="submit" variant="danger" disabled={!reason.trim() || setStatus.isPending}>
            Kill idea
          </Button>
        </form>
      </Dialog>
    </article>
  );
}

function BriefPanel({ idea: i }: { idea: IdeaDetail }) {
  const qc = useQueryClient();
  const toast = useToast();
  const gen = useMutation({
    mutationFn: () => post<{ version: number; files: Record<string, string> }>(`/ideas/${i.id}/brief`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["lab", "idea", i.id] });
      toast("Build brief generated", "good");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const files = i.brief?.files ?? {};
  const names = Object.keys(files);
  const [tab, setTab] = useState<string | null>(null);
  const cur = tab && files[tab] != null ? tab : names[0];
  return (
    <Card data-testid="build-brief">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">
          <FileText size={16} aria-hidden /> Build brief {i.brief && <span className="text-xs font-normal text-muted">v{i.brief.version}</span>}
        </h2>
        <div className="flex gap-2">
          <Button size="sm" variant={i.brief ? "secondary" : "primary"} disabled={gen.isPending} onClick={() => gen.mutate()}>
            {gen.isPending ? "Generating…" : i.brief ? "Regenerate" : "Generate brief"}
          </Button>
          {i.brief && (
            <a className={buttonClass("secondary", "sm")} href={`/api/ideas/${encodeURIComponent(i.id)}/brief.zip`} download>
              <FileDown size={14} aria-hidden /> Download .zip
            </a>
          )}
        </div>
      </div>
      {names.length > 0 ? (
        <>
          <div role="tablist" aria-label="Brief files" className="mt-3 flex gap-1 overflow-x-auto border-b border-border">
            {names.map((n) => (
              <button
                key={n}
                role="tab"
                type="button"
                aria-selected={n === cur}
                onClick={() => setTab(n)}
                className={clsx("-mb-px shrink-0 border-b-2 px-3 py-1.5 font-mono text-xs", n === cur ? "border-accent" : "border-transparent text-muted")}
              >
                {n}
              </button>
            ))}
          </div>
          <div className="mt-3 max-h-[32rem] overflow-auto" role="tabpanel">
            <Markdown source={files[cur]} />
          </div>
        </>
      ) : (
        <p className="mt-2 text-sm text-muted">A ready-to-build pack (BRIEF.md, CLAUDE.md, EXPERIMENT.md) for Claude Code.</p>
      )}
    </Card>
  );
}

function BuildLog({ idea: i }: { idea: IdeaDetail }) {
  const qc = useQueryClient();
  const toast = useToast();
  const startPost = useStartPost();
  const [text, setText] = useState("");
  const add = useMutation({
    mutationFn: () => post(`/ideas/${i.id}/logs`, { text: text.trim() }),
    onSuccess: () => {
      setText("");
      qc.invalidateQueries({ queryKey: ["lab", "idea", i.id] });
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="card-title">Build log</h2>
        {i.logs.length > 0 && (
          <Button size="sm" onClick={() => startPost({ seed_type: "build_log", seed_id: i.id, title: i.title })}>
            <PenLine size={14} aria-hidden /> Draft a post from this log
          </Button>
        )}
      </div>
      <form
        className="mt-3 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim().length >= 2) add.mutate();
        }}
      >
        <label className="sr-only" htmlFor="log-input">
          Log entry
        </label>
        <input id="log-input" className={inputClass + " mt-0"} value={text} onChange={(e) => setText(e.target.value)} placeholder="What did you try, learn or ship?" />
        <Button type="submit" disabled={text.trim().length < 2 || add.isPending}>
          Log
        </Button>
      </form>
      {i.logs.length === 0 ? (
        <p className="mt-3 text-sm text-muted">No entries yet. Logs are the only source of personal facts for build posts.</p>
      ) : (
        <ol className="relative mt-4 space-y-3 border-l border-border pl-4">
          {[...i.logs].reverse().map((lg) => (
            <li key={lg.id} className="relative">
              <span className="absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-surface bg-signal glow" aria-hidden />
              <p className="text-xs text-muted">{fmtDateTime(lg.logged_at)}</p>
              <p className="whitespace-pre-wrap text-sm">{lg.text}</p>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
